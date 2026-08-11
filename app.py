#!/usr/bin/env python3
"""Sage — the RCC User Guide assistant (Streamlit UI).

Retrieval, chunking, ranking, link resolution and file handling live in the `sage`
package so they can be unit-tested without Streamlit. This module is only the view:
session state, layout, and the tool loop that drives them.
"""

from __future__ import annotations

import hashlib
import html
import logging
import os
import time
import uuid

import streamlit as st
import streamlit.components.v1 as components

from sage import config, feedback, files, history, limits, links, llm, providers
from sage import corpus as corpus_mod
from sage.prompts import SYSTEM_PROMPT
from sage.search import Index
from sage.tools import (
    READ_DOC,
    SEARCH_DOCS,
    TOOL_SCHEMAS,
    ToolRunner,
    gather_context,
)

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.WARNING),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sage.app")

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# (icon, card label, question actually sent). The label is kept short so every
# card is a single line; the question stays conversational for the model.
EXAMPLES = [
    ("🚀", "Connect to Midway via SSH", "How do I connect to Midway via SSH?"),
    ("💾", "Storage quotas", "What are the storage quotas on Midway?"),
    ("⚙️", "Submit a batch job", "How do I submit a batch job with sbatch?"),
    ("🐍", "Set up a Python environment", "How do I set up a Python environment?"),
    ("🎮", "Run PyTorch on GPUs", "How do I run PyTorch on GPUs?"),
    ("📊", "Check my allocation", "How do I check my allocation balance?"),
]

st.set_page_config(
    page_title="Sage — RCC Assistant",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# --- assets ----------------------------------------------------------------


@st.cache_resource(show_spinner=False)
def load_asset(name: str) -> str:
    try:
        with open(os.path.join(STATIC, name), encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        logger.error("Missing static asset %s: %s", name, exc)
        return ""


st.markdown(f"<style>{load_asset('app.css')}</style>", unsafe_allow_html=True)
components.html(f"<script>{load_asset('app.js')}</script>", height=0)


# --- resources -------------------------------------------------------------


@st.cache_resource(show_spinner="Indexing RCC documentation…")
def get_index() -> Index:
    built = corpus_mod.build()
    index = Index(built)
    logger.info("Index ready: %s", corpus_mod.summarize(built))
    return index


def resolve_api_key(provider: str) -> str:
    key = config.api_key(provider)
    if key:
        return key
    try:
        return str(st.secrets.get(config.API_KEY_VARS[provider], ""))
    except Exception:  # no secrets.toml present
        return ""


def configured_providers() -> list[str]:
    """Providers that actually have a key, in preference order."""
    return [name for name in (providers.MISTRAL, providers.OPENCODE)
            if resolve_api_key(name)]


@st.cache_resource(show_spinner=False)
def get_provider(name: str):
    """Cached per provider; the key is read inside so it never becomes a cache key."""
    return providers.build(name, resolve_api_key(name))


@st.cache_resource(show_spinner=False)
def available_models(name: str) -> list[providers.Model]:
    try:
        return get_provider(name).models()
    except Exception as exc:
        logger.warning("Could not list models for %s: %s", name, exc)
        return []


READY = configured_providers()
if not READY:
    st.error(
        "**No API key is set.** Provide `MISTRAL_API_KEY` and/or `OPENCODE_API_KEY` "
        "in the environment or `.streamlit/secrets.toml`, then reload. "
        "OpenCode Zen keys are free and start with `sk-zen-`."
    )
    st.stop()


# --- who is asking ---------------------------------------------------------


def login_configured() -> bool:
    """Is there an OIDC provider for `st.login()` to send anyone to?

    Checked separately from `SAGE_REQUIRE_LOGIN`, because the two failure modes are
    not the same. A missing `[auth]` block with the flag on would lock every reader
    out of a working app — including whoever set the flag — so the flag alone is
    never enough to gate on.
    """
    try:
        return bool(st.secrets.get("auth"))
    except Exception:  # no secrets.toml at all
        return False


def gate() -> None:
    """Require a signed-in, allowed account before the app renders anything."""
    if not (config.REQUIRE_LOGIN and login_configured()):
        if config.REQUIRE_LOGIN:
            # Loud, because the deployment asked to be private and is not.
            logger.error(
                "SAGE_REQUIRE_LOGIN is set but no [auth] section is configured; "
                "the app is running OPEN. Add an OIDC provider to secrets.toml."
            )
        return
    if not getattr(st.user, "is_logged_in", False):
        st.markdown("### Sage — RCC documentation assistant")
        st.write("Sign in with your University account to continue.")
        st.button("Sign in", on_click=st.login, type="primary")
        st.stop()
    if not config.email_allowed(getattr(st.user, "email", "") or ""):
        st.error(
            "That account is outside the domains this deployment allows. "
            "Sign in with your University account."
        )
        st.button("Sign out", on_click=st.logout)
        st.stop()


gate()


def whoami() -> str:
    """A stable key for the rate limiter.

    The signed-in subject when there is one, because that is the only identity a
    reader cannot shed by opening a new tab. Falling back to a per-session id keeps
    the limiter useful when the app is open — it still stops a loop and a leaning
    Enter key — while being honest that it is a courtesy, not enforcement: a new
    private window is a new session.

    Not the IP address, which `st.context` will happily hand over. Campus NAT and the
    VPN put hundreds of people behind one, so a per-IP cap either does nothing or
    locks out a whole building, and on a hosted platform the value can be the
    proxy's rather than the reader's.
    """
    if getattr(st.user, "is_logged_in", False):
        subject = getattr(st.user, "sub", "") or getattr(st.user, "email", "")
        if subject:
            return f"user:{subject}"
    if "session_id" not in st.session_state:
        st.session_state.session_id = uuid.uuid4().hex
    return f"session:{st.session_state.session_id}"


@st.cache_resource(show_spinner=False)
def get_limiter() -> limits.Limiter:
    """One limiter for the whole process.

    `cache_resource` is shared across every session in the process, which is what
    makes the deployment budget a real total rather than a per-tab one. It is also
    the ceiling on this design: the counters live in memory, so they reset when the
    app restarts — which on a platform that hibernates idle apps is roughly daily.
    A deployment that needs the budget to survive a restart needs external storage.
    """
    return limits.Limiter(
        burst=config.RATE_BURST,
        refill_seconds=config.RATE_REFILL_SECONDS,
        daily_turns=config.DAILY_TURNS,
        daily_window=config.DAILY_WINDOW_SECONDS,
        call_budget=config.CALL_BUDGET,
        budget_window=config.BUDGET_WINDOW_SECONDS,
    )

INDEX = get_index()
CORPUS = INDEX.corpus

for key, default in (
    ("messages", []),
    ("processing", False),
    # A list, not one file. Holding one meant the guard below dropped anything
    # offered while a file was already attached, and a second attachment looked from
    # the outside like a control that does nothing.
    ("attachments", []),
    # How many times the user has dismissed each uploaded file with a chip's ✕. The
    # uploader widget still reports them on every rerun — nothing here can reach into
    # it and remove one — so without this they come straight back on the next run. A
    # count rather than a flag, so a file that is deliberately re-picked can return
    # while one merely still being reported cannot.
    ("dropped_uploads", {}),
    # Why a file was refused, keyed the same way, so the reason survives a rerun.
    ("upload_refusals", {}),
    ("uploader_key", 0),
    # Bumped by the Clear button. Rendered into the page for app.js, which is the only
    # side that can reach the text inside Streamlit's chat input.
    ("clear_token", 0),
    # Set by the stop button's callback, which runs before this script does. Read
    # once, at the top, because by the time the transcript is drawn it is too late:
    # the block that draws it hides the last question while `processing` is set.
    ("stop_requested", False),
    # The answer as it arrives, one delta per entry. It lives here rather than in a
    # local because a stop is an interrupted script run — the run holding the local
    # is the one being thrown away — and session state is the only thing that
    # survives it. This is what a stopped turn keeps instead of discarding.
    ("partial", []),
    # Index of the user message being edited in place, or None.
    ("editing", None),
    ("error", None),
    ("error_detail", ""),
    ("model", ""),
    ("notice", ""),
    ("failed_over", False),
    # (label, kind) of a model an automatic failover moved off. Held until the
    # replacement has actually answered, so the notice can never claim a switch
    # worked while an error card below it says it did not.
    ("switched_from", None),
):
    st.session_state.setdefault(key, default)


def model_options() -> list[providers.Model]:
    options: list[providers.Model] = []
    for name in READY:
        options.extend(available_models(name))
    return options


MODELS = model_options()

# What the picker's trigger has to be wide enough for. The stylesheet cannot work this
# out: the lineup is discovered from the provider at runtime, so the longest name it
# can show is known here and nowhere else. Sized to the longest rather than to the
# selected one on purpose — a width that tracked the selection would resize the button
# every time a model was picked, which reflows the row it sits in the corner of.
#
# A second <style> because the stylesheet above is injected before any provider has
# been asked what it serves, and moving that injection later would leave the no-key
# error screen unstyled.
if MODELS:
    st.markdown(
        f"<style>:root {{ --picker-chars: {max(len(m.label) for m in MODELS)}; }}"
        "</style>",
        unsafe_allow_html=True,
    )


def current_model() -> providers.Model:
    """The selected model, falling back to the configured default then anything."""
    for candidate in (st.session_state.model, config.DEFAULT_MODEL):
        chosen = providers.parse_key(candidate)
        if chosen and any(option.key == chosen.key for option in MODELS):
            return chosen
    if MODELS:
        return MODELS[0]
    return providers.Model(READY[0], config.MODEL)


MODEL = current_model()
st.session_state.model = MODEL.key


def fallback_model() -> providers.Model | None:
    """First model from a *different* provider — the way round a spent quota.

    `MODELS` is in preference order, so this is the best alternative, not an
    alphabetical accident.
    """
    return next(
        (option for option in MODELS if option.provider != MODEL.provider), None
    )


# Why a model refused, in words a user can act on.
REASONS = {"quota": "out of credit", "auth": "its key was rejected"}

# Streamlit signals "stop this script and start again" by raising. Matched by class
# name rather than imported, because the module those classes live in has moved
# between versions (`scriptrunner.script_runner` → `scriptrunner_utils.exceptions`)
# and because the test stub raises its own equivalents — a name test covers all
# three, an import covers whichever one happened to be installed when it was written.
CONTROL_FLOW_NAMES = frozenset(
    {"RerunException", "StopException", "Rerun", "Stop", "RerunError"}
)


def is_control_flow(exc: BaseException) -> bool:
    return type(exc).__name__ in CONTROL_FLOW_NAMES


# --- rendering helpers -----------------------------------------------------


def escape(text: str) -> str:
    return html.escape(text, quote=False).replace("\n", "<br>")


def render_user(message: dict, position: int | None = None) -> None:
    """One question in the transcript, and the way back into it.

    `position` is its index in `messages`, and passing None means "not editable" —
    the one caller that does is the turn block, which draws the question it is
    currently answering. A pencil on that one would offer to rewrite a question while
    the answer to it is arriving.
    """
    if position is not None and st.session_state.editing == position:
        render_user_editor(position, message)
        return

    badges = "".join(
        f'<div class="attachment-badge">{item.icon} '
        f"{html.escape(item.filename)}</div>"
        for item in (message.get("attachments") or [])
    )
    # Wrapped in a row of their own. Loose in the bubble they were inline boxes, so the
    # question ran straight on from the last filename with no space at all.
    if badges:
        badges = f'<div class="attachment-badges">{badges}</div>'
    st.markdown(
        f'<div class="user-message"><div class="user-bubble">{badges}'
        f'{escape(message.get("text", ""))}</div></div>',
        unsafe_allow_html=True,
    )
    if position is not None:
        render_edit_hook(position)


def render_edit_hook(position: int) -> None:
    """The clipped button app.js's pencil clicks, one per question.

    The same arrangement as the paperclip and the stop square: the control the reader
    presses is drawn by app.js, in the gutter beside the bubble where there is already
    empty space, and this is the widget that carries the click back to Python. Only a
    `st.button` can do that, and a `st.button` here — in the flow, under every
    question — would be a row of furniture the transcript does not have today.

    So it is taken out of the flow instead, clipped to a pixel exactly as the file
    uploader is. app.js pairs the Nth `.user-message` with the Nth of these, which
    holds because this is rendered immediately after the bubble it belongs to and
    both lists are read in document order.

    Bare, with no `st.container` around it. There was one, and the wrapper was the bug:
    Streamlit reuses a container's DOM node across reruns and relabels its class rather
    than rebuilding it, so after one open-and-cancel the node carrying
    `st-key-edit-hook-0` was the node that had been an answer — still holding the copy
    button app.js had appended to it, because that button is not React's to remove.
    app.js looked inside for `button` and got the copy button. Every pencil on the page
    then copied an answer to the clipboard instead of opening the editor, silently, for
    the rest of the session. Keyed on the widget itself, there is no wrapper to reuse.

    Disabled while an answer generates, for the reason the rating buttons are: the
    click is the rerun, so it would abandon the answer on screen. The stop button is
    the control for that, and it is the one that says so.
    """
    if st.button(
        "Edit this question",
        key=f"edit-open-{position}",
        disabled=st.session_state.processing,
    ):
        st.session_state.editing = position
        st.rerun()


def render_user_editor(position: int, message: dict) -> None:
    """The question, in a box, with the answer under it still on screen.

    Sending replaces this question and drops everything after it, because everything
    after it is a reply to wording that is being withdrawn. That is destructive, and
    it is the reason this is a two-step control rather than an editable bubble that
    resends on blur: the reader has to press Send for the tail of the conversation to
    go.

    The attachments come with it. They belong to the question, not to the text of it,
    and re-uploading three files to fix a typo is not an edit.
    """
    attachments = message.get("attachments") or []
    with st.container(key=f"edit-box-{position}"):
        if attachments:
            st.caption(
                "Still attached: " + ", ".join(item.filename for item in attachments)
            )
        edited = st.text_area(
            "Edit your question",
            value=message.get("text", ""),
            key=f"edit-text-{position}",
            label_visibility="collapsed",
        )
        columns = st.columns([1, 1, 5], gap="small")
        with columns[0]:
            send = st.button(
                "Send", key=f"edit-send-{position}", use_container_width=True
            )
        with columns[1]:
            cancel = st.button(
                "Cancel", key=f"edit-cancel-{position}", use_container_width=True
            )
        asked = (edited or "").strip()
        if send and len(asked) > config.MAX_PROMPT_CHARS:
            # The same cap the composer enforces, said here because this box does not
            # go through it. Nothing is dropped: the text stays in the box.
            over = len(asked) - config.MAX_PROMPT_CHARS
            st.warning(
                f"⚠️ That question is {over:,} characters over the "
                f"{config.MAX_PROMPT_CHARS:,}-character limit."
            )
            send = False
        elif send and not asked:
            st.warning("⚠️ A question cannot be empty.")
            send = False

    if cancel:
        st.session_state.editing = None
        st.rerun()
    if send:
        start_new_turn(asked, attachments, replacing=position)


def citations(chunks: list) -> list[dict]:
    """The Sources strip: one entry per destination, in the order they were read.

    Deduplicated on the URL and not the chunk id, because the id is an index key and
    the URL is what the reader is given. The two come apart wherever indexing cuts
    finer than the published page can be linked: a scraped page is windowed and every
    window shares the page URL, and `search_docs` may return two windows of one page
    (MAX_PER_PAGE allows two sections of any page). "Who is the director of the RCC"
    listed four citations that were two pages. An over-long docs section splits the
    same way and its parts share one anchor.

    The first read of a destination keeps the slot: it is the one the answer was built
    from first, and its label is the page's own name rather than a later cut's.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.url in seen:
            continue
        seen.add(chunk.url)
        out.append(
            {
                "id": chunk.id,
                "label": chunk.label,
                "url": chunk.url,
                "source": chunk.source,
            }
        )
    return out


def related_sections(sources: list[dict], limit: int = 3) -> list[dict]:
    """Sibling sections of the pages actually cited — discovery for free.

    No extra model call: the chunks are already indexed, so neighbouring sections
    of a cited page are known and are always real documentation.

    A lead is somewhere the reader is not already being sent, so what has to be new is
    the destination — the URL — and not the chunk id. Filtering on the id let one page
    arrive three times: asking who directs the RCC cited "Our Team" and then offered
    "Our Team (part 2)", "(part 3)" and "(part 4)", which were three of that page's
    thirteen indexing windows, three identical links, and the link already listed
    directly above them under Sources. Three windows of one page is not discovery, it
    is the citation again with a number after it.

    Showing nothing is the right answer when a page has nothing else to point at, and
    for a scraped page that is always: it has no anchors, so no window of it is ever a
    second destination. `render_sources` omits the block entirely when this is empty.
    """
    seen = {source.get("url", "") for source in sources}
    pages = {source["id"].split("#", 1)[0] for source in sources}
    out: list[dict] = []
    for chunk in CORPUS.chunks:
        if len(out) >= limit:
            break
        page = f"{chunk.source}/{chunk.path}"
        if page not in pages or chunk.url in seen or not chunk.heading:
            continue
        seen.add(chunk.url)
        out.append({"label": chunk.heading, "url": chunk.url})
    return out


def render_notice() -> None:
    """The neutral strip: a failover, or a turn the limiter would not start.

    Rendered on the landing screen too, and that is the point. It used to live inside
    the branch that draws a conversation, so a refusal with nothing on screen yet had
    nowhere to appear: clear the chat, click a starter card with the token bucket
    empty, and the click did nothing at all — no question, no answer, no reason, on a
    screen whose only controls are those cards.
    """
    if st.session_state.notice:
        # `role="status"` because this is often the only account of why a click did
        # nothing, and a reader who cannot see it has no other way to be told.
        st.markdown(
            f'<div class="notice" role="status">'
            f"{html.escape(st.session_state.notice)}</div>",
            unsafe_allow_html=True,
        )


def render_sources(sources: list[dict], related: list[dict]) -> None:
    """The citations under an answer, and the sibling sections worth a look.

    Two lists rather than two rows of identical chips. They used to share every class,
    which left the reader unable to tell what the answer was built from ("Sources")
    from what it merely suggests next ("Related") — and as wrapping chip rows they were
    ragged: a flex row whose first item is the label indents its first line only, so
    every later line dropped back to the container edge, 66px to the left of the line
    above it, measured with six real citations at the 820px content width.

    Sources are numbered, one per line, the way a paper cites: the number is what makes
    a reference list readable, and it lets an answer say "see 2" if it wants to. Related
    is a plain vertical list of leads, no numbers and no source badge, which is the
    difference in kind said in the layout instead of in a heading.
    """
    if not sources:
        return
    items = "".join(
        f'<div class="source-item">'
        f'<a class="source-link" href="{html.escape(source["url"], quote=True)}" '
        f'target="_blank" rel="noopener noreferrer">{html.escape(source["label"])}</a>'
        f'<span class="source-kind">{html.escape(source["source"])}</span></div>'
        for source in sources
    )
    strip = (
        '<div class="sources"><span class="sources-label">Sources</span>'
        f'<div class="source-list">{items}</div></div>'
    )

    if related:
        leads = "".join(
            f'<div class="related-item">'
            f'<a class="related-link" href="{html.escape(item["url"], quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">{html.escape(item["label"])}</a>'
            "</div>"
            for item in related
        )
        strip += (
            '<div class="sources related"><span class="sources-label">Related</span>'
            f'<div class="related-list">{leads}</div></div>'
        )
    st.markdown(strip, unsafe_allow_html=True)


def render_rating(position: int, message: dict) -> None:
    if not feedback.enabled():
        return
    if message.get("rating"):
        st.markdown(
            '<div class="rating-thanks">Thanks — noted.</div>', unsafe_allow_html=True
        )
        return

    with st.container(key=f"rate-{position}"):
        columns = st.columns([1, 1, 12], gap="small")
        for column, verdict, glyph, hint in (
            (columns[0], "up", "👍", "This answered my question"),
            (columns[1], "down", "👎", "This was wrong or unhelpful"),
        ):
            with column:
                if st.button(
                    glyph,
                    key=f"rate-{position}-{verdict}",
                    help=hint,
                    # Not while an answer is arriving. Any click reruns the script,
                    # and a rerun mid-turn abandons the half-written answer and runs
                    # the whole turn again from the first provider call — so rating an
                    # earlier answer while the next one streams silently costs a
                    # second turn and loses the one on screen. `disabled` is what
                    # stops the click reaching the server at all; an inert callback
                    # would not, because the rerun is the click, not the handler.
                    disabled=st.session_state.processing,
                ):
                    question = next(
                        (
                            item.get("text", "")
                            for item in reversed(
                                st.session_state.messages[:position]
                            )
                            if item.get("role") == "user"
                        ),
                        "",
                    )
                    feedback.record_rating(
                        verdict,
                        question,
                        message.get("text", ""),
                        message.get("sources", []),
                    )
                    message["rating"] = verdict
                    st.rerun()


def render_assistant(position: int, message: dict) -> None:
    with st.container(key=f"answer-{position}"):
        with st.chat_message("assistant"):
            text = message.get("text", "")
            if text:
                st.markdown(links.fix_links(text, CORPUS))
            if message.get("stopped"):
                # Said inside the bubble, under the text it belongs to. A stopped
                # answer that ends mid-sentence otherwise reads as a model that broke
                # off on its own, and the difference matters: one is worth retrying
                # and the other is the reader's own doing. It is also the only thing
                # in the bubble when the stop landed before any text, which is what
                # keeps that turn from rendering as nothing at all.
                st.markdown(
                    '<div class="stopped-note">Stopped</div>', unsafe_allow_html=True
                )
        sources = message.get("sources", [])
        render_sources(sources, related_sections(sources))
        # Not on a stopped answer. Rating half a sentence the reader cut off says
        # nothing about whether the app answered the question.
        if not message.get("stopped"):
            render_rating(position, message)


def _detail(exc: BaseException | None) -> str:
    """A one-line, non-secret description of a failure for the details panel."""
    if exc is None:
        return ""
    text = f"{type(exc).__name__}: {exc}"
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    if status:
        text = f"{text}  (HTTP {status})"
    return f"{text}\nmodel={MODEL.key}"[:800]


def status_html(text: str) -> str:
    return (
        '<div class="status-row" role="status" aria-live="polite">'
        '<span class="status-dot" aria-hidden="true"></span>'
        f'<span class="status-text">{html.escape(text)}</span>'
        '<span class="status-dots" aria-hidden="true"><span></span><span></span>'
        "<span></span></span></div>"
    )


def show_status(slot, text: str) -> None:
    slot.empty()
    with slot.container(), st.chat_message("assistant"):
        st.markdown(status_html(text), unsafe_allow_html=True)


def clearing(stream, slot):
    """Yield deltas, dropping the status placeholder as soon as text arrives."""
    cleared = False
    for delta in stream:
        if not cleared:
            slot.empty()
            cleared = True
        yield delta
    if not cleared:
        slot.empty()


def recording(stream):
    """Yield deltas, and keep a copy somewhere a stopped turn can still reach.

    `st.write_stream` accumulates the answer in a local, and a stop throws the run
    holding that local away — so without this the text on screen at the moment of the
    click is gone by the time anything can save it. Session state is what survives an
    interrupted run, which is why the copy goes there and not into a variable.

    One `append` per delta rather than a growing string: an answer arrives in a few
    thousand fragments, and `+=` on a string re-copies the whole answer for each one.
    """
    for delta in stream:
        st.session_state.partial.append(delta)
        yield delta


def argument(call: dict, name: str) -> str:
    """One tool argument, as a string. A model types whatever it likes in there.

    `llm._parse` guarantees a dict and nothing about its values, so a query typed as
    a number — `{"query": 123}` — used to raise AttributeError here and end the turn
    with an error card blaming the network. `sage/tools.py` coerces the same way.
    """
    value = call.get("input", {}).get(name)
    return "" if value is None else str(value).strip()


# The most of a name or a query the status line will say. Neither is written by this
# app — a doc title comes from the corpus and a query from the model — so both need a
# ceiling, and the ceiling has to hold on a phone: at 500px this line has room for
# about 60 characters before it takes a second row, and a progress cue that grows the
# page it sits on is worse than one that says less.
STATUS_MAX = 48


def _short(text: str) -> str:
    """`text`, cut at a word boundary if it is longer than the line has room for."""
    if len(text) <= STATUS_MAX:
        return text
    cut = text[:STATUS_MAX].rsplit(" ", 1)[0] or text[:STATUS_MAX]
    return f"{cut.rstrip(' ,;:—-')}…"


def describe(calls: list[dict]) -> str:
    """Say what is actually happening instead of a generic shimmer.

    The document, not the section of it. `chunk.label` is `"{title} — {heading}"`,
    which is right on a citation chip — that is a link, and the heading says which part
    of a long page it goes to. It is wrong here: this line is on screen for a second
    while a reader waits, and RCC headings are frequently whole questions, so it was
    dragging sentences like "Allocations and Service Units FAQ — How do I check how many
    service units I have remaining on my allocation?" across the page. 146 characters at
    the worst, 38 at the median; the titles alone are 60 and 15. The precise section is
    not lost, it is in the Sources strip under the answer, next to the link that uses
    it — and by then the reader is deciding whether to click, which is when it helps.
    """
    for call in calls:
        if call["name"] == SEARCH_DOCS:
            query = argument(call, "query")
            return (f"Searching the docs for “{_short(query)}”" if query
                    else "Searching the docs")
    for call in calls:
        if call["name"] == READ_DOC:
            path = argument(call, "path")
            chunk = CORPUS.chunk(path)
            title = chunk.doc_title if chunk else path.split("/")[-1]
            return f"Reading {_short(title)}" if title else "Reading documentation"
    return "Working"


def may_start_turn() -> bool:
    """Ask the limiter whether a turn may run, and say why if not.

    One gate, and every path that spends provider calls goes through it. "Try again"
    did not: it set `processing` directly, so a deployment whose call budget was
    spent refused new questions while the button under the error card kept making
    requests, one per click, for as long as anyone cared to click it.

    The refusal goes to `notice`, the same neutral strip a failover uses, so it reads
    as information rather than as an error with a Try-again button that would itself
    be refused.
    """
    verdict = get_limiter().check(whoami(), time.monotonic())
    if verdict.allowed:
        return True
    logger.info("Turn refused for %s: %s", whoami(), verdict.message)
    st.session_state.notice = verdict.message
    return False


def start_new_turn(question: str, attachments=None, replacing: int | None = None) -> None:
    # The one place every turn begins — the composer, the starter cards and an edited
    # question all come through here — so it is the one place a turn can be refused.
    # Checked before any state is touched: a refused question must leave the transcript
    # exactly as it was, or the reader is left looking at their own question with no
    # answer under it and nothing to click, which is the shape of a broken app rather
    # than a busy one.
    #
    # `replacing` is an index into `messages`: everything from there on is dropped and
    # this question takes its place. That is what re-sending an edited question means —
    # the answer below it, and every turn after it, was a reply to wording that no
    # longer exists. Truncating happens AFTER the gate for the same reason the append
    # does: a refused edit must leave the conversation intact, not delete the tail of
    # it and then decline to replace it.
    if not may_start_turn():
        st.rerun()
        return

    if replacing is not None:
        st.session_state.messages = st.session_state.messages[:replacing]

    st.session_state.messages.append(
        {"role": "user", "text": question, "attachments": list(attachments or [])}
    )
    st.session_state.processing = True
    st.session_state.editing = None
    # Belongs to a turn that is over. An abandoned half-answer left here would be
    # committed by the next stop as if it were this turn's.
    st.session_state.partial = []
    st.session_state.stop_requested = False
    st.session_state.error = None
    # Both of these belong to the turn that just ended, and a new question is where
    # they stop being true.
    #
    # `failed_over` is the once-per-turn guard that stops a bad key ping-ponging
    # between providers. Cleared only on a *successful* answer, it survived a failover
    # that then failed for some other reason and stayed set for the rest of the
    # session — so every later quota error showed an error card instead of failing
    # over, until the reader picked a model by hand.
    #
    # `notice` is the "X was unavailable, Y answered instead" line. It renders under
    # the transcript, which puts a notice about the previous turn directly above the
    # new question while the new one generates, reading as if it belonged to it.
    st.session_state.failed_over = False
    st.session_state.notice = ""
    st.session_state.attachments = []
    # Both, together: the widget is reset so its files stop being reported, and the
    # dismissal list is emptied because the keys in it refer to a widget that no
    # longer exists. Leaving stale keys behind would silently refuse a file with the
    # same name later in the conversation.
    st.session_state.dropped_uploads = {}
    st.session_state.upload_refusals = {}
    st.session_state.uploader_key += 1
    st.rerun()


# --- stopping a turn -------------------------------------------------------
#
# A generation could not be called off. The reader who spotted a typo in the question
# a second after sending it had three options, and all of them were worse than
# waiting: touch the page and the rerun restarts the whole turn from the first
# provider call, clear the conversation and lose it, or sit through an answer to a
# question they no longer wanted asked.
#
# The mechanism is Streamlit's own, used deliberately instead of fought. Any widget
# interaction during a run aborts that run — `st.write_stream` raises at its next
# write — and until now the abort was something this file only defended against
# (`interrupted`, and the `disabled=` on the rating buttons). A stop is that same
# abort, asked for on purpose, with one flag set to say so.
#
# The order the pieces run in is what makes it work:
#
#   1. `request_stop` is an `on_click` callback, so it runs BEFORE this script does
#      on the run that follows the click. A button whose value were merely read where
#      it is rendered would be read at the bottom of the page, long after the
#      transcript above it had been drawn for a turn that is no longer running.
#   2. `finish_stopped_turn` runs at the top, before anything is drawn.
#   3. The turn block at the end sees `processing` cleared and does not start again.


def request_stop() -> None:
    st.session_state.stop_requested = True


def finish_stopped_turn() -> None:
    """Keep what arrived before the reader pressed stop, and end the turn there.

    The half-written answer is kept rather than thrown away. It is what was on the
    screen at the moment of the click — often it is the answer, and the reader
    stopped it because they had already read enough — and deleting it would make the
    button destructive in a way nothing about a square suggests.

    A stop with nothing to keep still appends a message, empty. The transcript skips
    an assistant message with no text, so without one the reader is left looking at
    their own question with no reply, no error and nothing to click: the exact dead
    end this file has fixed twice before. `stopped` is what `render_assistant` reads
    to say so, and `history.build` drops an empty assistant turn on its own, so
    nothing empty is ever sent upstream.

    Sources are not kept. They live on the ToolRunner in the run that was abandoned,
    and reconstructing them would mean mirroring every read into session state for a
    Sources strip under an answer that stops mid-sentence. The citations inside the
    text itself survive, because `links.fix_links` resolves those at render time.
    """
    st.session_state.stop_requested = False
    # Not `if processing`: the click races the turn. A stop that lands after the
    # answer has already been committed must not append a second, empty message
    # under it.
    if not st.session_state.processing:
        st.session_state.partial = []
        return

    text = "".join(st.session_state.partial).strip()
    st.session_state.partial = []
    st.session_state.processing = False
    # A failover in flight is off too. Without this the pending switch fires on the
    # next run, `processing` is set again by the `finally` below, and the turn the
    # reader just stopped starts over on a different model.
    st.session_state.pop("failover_to", None)
    st.session_state.switched_from = None
    st.session_state.notice = ""
    st.session_state.error = None
    st.session_state.error_detail = ""
    st.session_state.messages.append(
        {
            "role": "assistant",
            "text": text,
            "sources": [],
            "rating": None,
            "model": MODEL.key,
            "stopped": True,
        }
    )
    logger.info("Turn stopped by the reader after %d characters", len(text))


if st.session_state.stop_requested:
    finish_stopped_turn()


def render_stop_hook() -> None:
    """The Streamlit button app.js clicks, and the only thing that can end a turn.

    Clipped to a pixel, exactly like the file uploader above it, for the same reason:
    the control the reader actually presses is drawn in the composer by app.js, where
    the send button was a moment ago, and this is the widget that carries the click
    back to Python. A `st.button` is the only thing that can — nothing app.js injects
    has a channel to this script.

    Rendered before the turn block and nowhere else. That block ends in `st.rerun()`,
    so a widget declared after it does not exist on the one run where it is needed.
    """
    if not st.session_state.processing:
        return
    st.button("Stop generating", key="stop-generation", on_click=request_stop)


# --- composer strip --------------------------------------------------------

# There is deliberately no caveat line under the input. It went from a popover, to
# three paragraphs under the starter cards, to one 11px line beside the model name,
# and each version was still a permanent fixture at the bottom of every screen for
# something read once and then ignored. Neither half of it is lost: every answer
# carries a Sources strip to the documentation it came from, so "this can be wrong,
# here is what it read" is attached to the thing that might be wrong; and the system
# prompt hands out the Help Desk address (`sage/prompts.py`, `sage/tools.py`) in the
# answer to a question the documentation cannot settle, which is when it is wanted.

has_messages = bool(st.session_state.messages)


def render_model_picker() -> None:
    """Switch provider/model mid-session — the way round a spent API quota.

    A popover of buttons rather than a selectbox, for two reasons that both bit:

    * A selectbox stores its own value under its widget key. After an automatic
      failover set `session_state.model` and reran, the selectbox handed back its
      *previous* value on that run and switched straight back to the provider
      that had just refused. Buttons hold no state, so a programmatic switch
      survives.
    * A selectbox is a block with no intrinsic width, so in a row that sizes its
      children to their content it resolved to zero and the control was invisible.
      A button is sized by its label, exactly like the ℹ️ and 🗑️ beside it.
    """
    if len(MODELS) < 2:
        return
    # One `with`, not two nested: the caption that used to sit between them is gone,
    # and ruff is right that a bare nest reads as if something belonged in the gap.
    with st.popover(MODEL.label), st.container(key="model-list"):
        for index, option in enumerate(MODELS):
            mark = "●" if option.key == MODEL.key else "○"
            if st.button(
                f"{mark}  {option.label}",
                key=f"pick-{index}",
                use_container_width=True,
            ):
                st.session_state.model = option.key
                # A deliberate choice clears the record of the automatic one,
                # so the next quota error can fail over again.
                st.session_state.failed_over = False
                st.session_state.switched_from = None
                st.session_state.notice = ""
                st.rerun()

def render_controls() -> None:
    """One line under the input: Clear and the model picker, in the right corner.

    This row used to be a bar above the conversation, which was wrong twice over.
    It sat in the band Streamlit's own full-width header takes the clicks for, so
    it looked right and did nothing; and on the landing screen — the one screen
    where a new user has to choose a model before asking anything — the picker
    inside it did not render at all. Under the input it is beside the thing it
    affects, on every screen, at the opposite end of the page from that header.

    Clear, then the picker in the corner — it names what will answer, next to the
    button that sends. Nothing else: every extra row here is a slice of a phone
    screen spent on furniture, which is how the bottom of this app came to look, in
    the words of the person using it, nasty.

    One container, not a strip wrapping a row. Two of them meant two sets of layout
    rules for two elements whose identity depends on which one `st.container(key=…)`
    hangs the key off — and the inner rule outranked the outer one, which is how the
    controls ended up stacked in a column in the app while every render in the
    harness had them in a row.

    No `st.columns`: a column has no intrinsic width, which is how the picker came
    to be invisible twice. The row is laid out by CSS instead, so each control is
    as wide as its own label and the worst a broken stylesheet can do is stack them.
    """
    with st.container(key="composer-strip"):
        if has_messages and st.button(
            "🗑️", key="clear", help="Clear this conversation"
        ):
            st.session_state.messages = []
            st.session_state.processing = False
            st.session_state.partial = []
            st.session_state.stop_requested = False
            st.session_state.editing = None
            st.session_state.attachments = []
            st.session_state.dropped_uploads = {}
            st.session_state.upload_refusals = {}
            st.session_state.error = None
            st.session_state.notice = ""
            st.session_state.failed_over = False
            st.session_state.switched_from = None
            st.session_state.uploader_key += 1
            # Nothing here can empty the composer — the text in it is client-side
            # state Streamlit only reads on submit — so clearing the conversation left
            # the last question sitting in the box on the landing screen, over a set of
            # starter cards, as if it were still about to be sent. app.js empties it
            # when this counter moves.
            st.session_state.clear_token += 1
            st.rerun()
        render_model_picker()


# --- body ------------------------------------------------------------------

if not has_messages:
    st.markdown(
        """
        <div class="welcome">
            <h1 class="welcome-title">What can I help you with?</h1>
            <p class="welcome-subtitle">Answers from the official UChicago RCC
            documentation, with citations.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key="examples"):
        for row in range(0, len(EXAMPLES), 2):
            columns = st.columns(2, gap="medium")
            for offset, column in enumerate(columns):
                position = row + offset
                if position >= len(EXAMPLES):
                    continue
                icon, label, question = EXAMPLES[position]
                with column, st.container(key=f"example-card-{position}"):
                    # No `help=`: a tooltip on a card that already says what it
                    # does is just a black box following the cursor around.
                    if st.button(
                        f"{icon} {label}",
                        key=f"example-{position}",
                        use_container_width=True,
                    ):
                        # With the attachments, like any other question. Without
                        # them, a file attached on the landing screen — where the
                        # chips do render — was cleared by the send and never seen.
                        start_new_turn(question, st.session_state.attachments)

    # Under the cards, where a refused starter card can be seen from.
    render_notice()
else:
    # Marker only: app.js keys page-scroll behaviour off its presence — without it
    # the screen is the landing screen, which always starts at the top.
    st.markdown('<div class="chat-container"></div>', unsafe_allow_html=True)

    rendered = st.session_state.messages
    if st.session_state.processing and rendered and rendered[-1]["role"] == "user":
        rendered = rendered[:-1]

    for position, message in enumerate(rendered):
        if message["role"] == "user":
            render_user(message, position)
        elif message.get("text") or message.get("stopped"):
            # `or stopped`: an assistant turn with no text is normally nothing to
            # draw, but a turn stopped before its first token is a thing that
            # happened and the reader has to see that it did.
            render_assistant(position, message)

    render_notice()

    if st.session_state.error and not st.session_state.processing:
        st.markdown(
            '<div class="error-card" role="alert">'
            '<div class="error-title">Could not complete that request</div>'
            f'<div class="error-body">{html.escape(st.session_state.error)}</div></div>',
            unsafe_allow_html=True,
        )
        if st.session_state.error_detail:
            # Streamlit Cloud logs are awkward to reach; surfacing the real
            # exception here is what turns "something went wrong" into a fixable
            # report. Collapsed so it stays out of the way for normal users.
            with st.expander("Technical details"):
                st.code(st.session_state.error_detail, language="text")
        # "Switch to another model" is only useful if switching is one click away
        # from where the advice appears. Sending the user hunting for a control
        # elsewhere on the page is how a spent quota became a dead end.
        alternative = fallback_model()
        with st.container(key="error-actions"):
            # Half-width each, flush with the error card above: narrower columns
            # wrapped the model name onto a second line, which looks broken.
            slots = st.columns(2) if alternative else st.columns([1, 2, 1])
            with slots[0] if alternative else slots[1]:  # centred when alone
                retry = st.button("↻ Try again", key="retry", use_container_width=True)
            switch = False
            if alternative:
                with slots[1]:
                    switch = st.button(
                        f"→ Use {alternative.label}",
                        key="switch-model",
                        use_container_width=True,
                    )
        if retry or switch:
            # Switching model happens either way, before the gate. It costs nothing
            # and it is the remedy the card itself recommends — refusing it while a
            # bucket refills would take the fix away from the reader at the moment
            # they reached for it, and leave "switch to another model and try again"
            # printed above a button that does neither.
            if switch:
                st.session_state.model = alternative.key
                st.session_state.switched_from = None
            # The turn, though, goes through the same gate as a new question: it
            # costs the same one-to-five provider calls, and skipping the check meant
            # a spent deployment budget stopped new questions while this button went
            # on spending, one turn per click. On a refusal the error card and its
            # buttons stay exactly where they are — clearing them would take away the
            # only way back — and the notice above says how long to wait.
            if may_start_turn():
                # On both paths, not just the deliberate switch: "Try again" is the
                # reader asking for another attempt, and leaving the guard set means
                # the retry cannot fail over even though this is a fresh attempt at
                # the question.
                st.session_state.failed_over = False
                st.session_state.error = None
                st.session_state.error_detail = ""
                if st.session_state.messages[-1]["role"] == "user":
                    st.session_state.processing = True
            st.rerun()


# --- input -----------------------------------------------------------------

# `accept_multiple_files`, and no `type=`.
#
# The type filter was a list of extensions the picker would offer, and it is gone for
# the same reason the extension gate in `files.process` went: it refused a pasted
# screenshot outright (the name app.js gives one is not on any list) and it refused
# every cluster file whose extension nobody thought of. `files.process` reads the
# bytes and says yes or no with a reason, which is the check that was doing the work
# anyway.
upload = st.file_uploader(
    "Attach a file",
    accept_multiple_files=True,
    key=f"uploader-{st.session_state.uploader_key}",
    label_visibility="collapsed",
)


def upload_key(item) -> tuple:
    """Identity of an uploaded file across reruns.

    Name, size and a digest of the first 4 KB — not Streamlit's `file_id`, which
    changes on every rerun for the same file in some versions and would re-process and
    re-append one attachment per interaction with the page.

    The digest is there because name and size alone collided: two different
    `config.yaml` files of the same length were one attachment, and the second was
    dropped without a word. 4 KB rather than the whole file so a 10 MB upload is not
    rehashed on every rerun.
    """
    head = item.getvalue()[:4096]
    return (item.name, item.size, hashlib.blake2b(head, digest_size=8).hexdigest())


keyed = [(upload_key(item), item) for item in upload or []]
offered = {key for key, _item in keyed}

# Dismissals are COUNTED, not just remembered, and the count is how many copies of a
# file to skip on this run.
#
# A plain set of keys blacklisted the file outright, so after dismissing a chip the
# user could pick the *same file* again and nothing whatsoever happened — no chip, no
# warning. Worse on the landing screen, where the Clear button that resets this does
# not render, so there was no route back at all short of reloading the page.
#
# Counting keeps the distinction that matters. `accept_multiple_files` accumulates, so
# a re-picked file is reported twice: one dismissal skips the first copy and the second
# is a fresh offer and attaches. A file dismissed and not re-picked is still reported
# once, still skipped, and still does not come back on its own.
dismissed = dict(st.session_state.dropped_uploads)
# Keys the widget has stopped reporting cannot come back, so their counts are dead.
dismissed = {key: count for key, count in dismissed.items() if key in offered}

# Reasons files were refused, so the explanation outlives the run that produced it. A
# bare `st.warning` is discarded whenever the run ends in a rerun — which it does
# whenever a file is dropped while an answer is generating — and the refusal was
# permanent, so the user was left with a file in the uploader, no chip, and no reason.
refusals = {
    key: why
    for key, why in dict(st.session_state.get("upload_refusals", {})).items()
    if key in offered
}

held = {item.key for item in st.session_state.attachments if item.key}
for key, item in keyed:
    if key in held:
        continue
    if dismissed.get(key, 0) > 0:
        dismissed[key] -= 1
        continue
    attachment, error = files.process(item.name, item.getvalue())
    if not error:
        # The per-file limit does not bound the total, and a handful of legal
        # screenshots made one illegal request. Refused here rather than by the
        # provider, which reports it as "this conversation got too long".
        attached = sum(held_item.size for held_item in st.session_state.attachments)
        if attached + item.size > config.MAX_ATTACHED_BYTES:
            limit = config.MAX_ATTACHED_BYTES // (1024 * 1024)
            error = (
                f"{item.name} would put this turn over the {limit} MB total for "
                "attachments. Send what is attached first, or drop something."
            )
    if error:
        # Remembered rather than clearing the whole widget: a bad file among three
        # good ones used to reset the uploader and take the other two with it.
        st.session_state.dropped_uploads[key] = (
            st.session_state.dropped_uploads.get(key, 0) + 1
        )
        refusals[key] = error
        continue
    attachment.size = item.size
    attachment.key = key
    st.session_state.attachments.append(attachment)
    held.add(key)

st.session_state.upload_refusals = refusals
if refusals:
    # In a container of its own, and the key is the point: these land at the end of
    # the page, below the last message, and app.js measures the end of the page to
    # decide how much room the composer needs and where to scroll. It had no idea
    # these existed, so on a conversation the reason a file was refused rendered
    # 65 of its 80 pixels *behind* the input bar — a file that did not attach, and
    # an explanation the reader could not see. `.st-key-upload-notes` is what makes
    # it part of the tail. Created only when there is something to say, so an empty
    # container is never in the way of that measurement.
    with st.container(key="upload-notes"):
        for why in refusals.values():
            st.warning(f"⚠️ {why}")


def render_attachments() -> None:
    """The chips for what is attached, pinned directly above the input box.

    They used to render wherever the script happened to reach them — in the middle of
    the page, under the starter cards, a long way from the box they belong to. They
    are part of the composer, so they are pinned to it: app.js measures this row and
    the page reserves room for it, exactly as it does for the controls underneath.
    """
    if not st.session_state.attachments:
        return
    with st.container(key="attachments"):
        for index, item in enumerate(st.session_state.attachments):
            if st.button(
                # Filename and the ✕, and a truncation warning if there is one. The
                # character and page counts that used to sit here were four chips of
                # arithmetic on a four-file turn, none of it telling the reader
                # anything they did not already know about a file they chose.
                f"{item.icon} {item.filename}"
                + (f" · {item.summary}" if item.summary else "")
                + "  ✕",
                key=f"drop-attachment-{index}",
                help="Remove this attachment",
            ):
                dropped = st.session_state.attachments.pop(index)
                if dropped.key:
                    st.session_state.dropped_uploads[dropped.key] = (
                        st.session_state.dropped_uploads.get(dropped.key, 0) + 1
                    )
                st.rerun()
        if any(item.kind == "image" for item in st.session_state.attachments) and not (
            config.sees_images(MODEL.id)
        ):
            # Said next to the picture, once, rather than discovered when the answer
            # ignores it. The picker is right there.
            st.caption(
                f"{MODEL.label} cannot read images — pick a Pixtral or Claude model "
                "to have this one looked at."
            )

# No `max_chars`. That argument is the only thing that puts Streamlit's "15/8000"
# counter inside the box, and a running character count is noise in a box you type a
# question into — it reads as a form field with a quota. The limit itself is still
# enforced, below, where it costs nothing to look at.
#
# Enforced here rather than hidden with CSS on purpose: the counter's own test id is
# Streamlit's, unversioned, and not visible from this repo, so a rule naming it would
# be a guess that fails silently the day it changes. Not asking for the counter
# cannot fail that way.
# Two prompts, because the box is asking for two different things. On the landing
# screen it is the only instruction on the page about what this app is for, so it names
# the subject. Once an answer is on screen the subject is established and the useful
# thing to say is that the conversation carries: the box takes a follow-up, it is not a
# fresh search that has forgotten what was just asked.
#
# Keyed on an answer existing rather than on there being any messages at all. A question
# that is still generating, or one that failed and left its retry button, has nothing to
# follow up on yet — "ask a follow-up" over an empty answer reads as if one arrived.
answered = any(item["role"] == "assistant" for item in st.session_state.messages)
prompt = st.chat_input(
    "Ask a follow-up question…" if answered else "Ask any question about the RCC…"
)

# The token app.js watches to know the composer should be emptied. A marker element
# rather than a callback, for the same reason `#processing-signal` is one: this file
# cannot touch the textarea, and a value in the DOM is something app.js can compare
# against what it last acted on, so a clear empties the box exactly once.
st.markdown(
    f'<div id="composer-reset" data-token="{st.session_state.clear_token}" hidden></div>',
    unsafe_allow_html=True,
)

# Rendered here, before the turn below: that block ends in `st.rerun()`, so
# anything after it is never reached while an answer is generating — which is
# exactly when a user whose model just ran out of credit reaches for the picker.
# The chips go with it: they are pinned to the composer too, and rendering them up
# where the script first hears about the upload is what put them mid-page.
render_attachments()
render_controls()
render_stop_hook()

if prompt and prompt.strip():
    asked = prompt.strip()
    if len(asked) > config.MAX_PROMPT_CHARS:
        # The cap the counter used to advertise. Said once, at the moment it matters,
        # instead of counted out on screen for every question that was never near it.
        over = len(asked) - config.MAX_PROMPT_CHARS
        # Keyed for the same reason the upload refusals are: this is the end of the
        # page, and app.js has to know it is there or it reserves room to the last
        # message and leaves the explanation under the composer.
        with st.container(key="prompt-notes"):
            st.warning(
                f"⚠️ That question is {over:,} characters over the "
                f"{config.MAX_PROMPT_CHARS:,}-character limit. Shorten it, or attach "
                "the long part as a file."
            )
            # And handed back, because `st.chat_input` empties its box on submit:
            # without this, "shorten it" asks the reader to shorten something the app
            # has just destroyed. The counter that used to enforce this made
            # overrunning impossible in the first place, so losing the text is a
            # regression this pays off.
            with st.expander("Your question, to copy back out", expanded=True):
                st.code(asked, language=None)
    else:
        start_new_turn(asked, st.session_state.attachments)


# --- the turn --------------------------------------------------------------

if st.session_state.processing:
    # Marker element app.js polls to know a generation is in flight.
    st.markdown('<div id="processing-signal" hidden></div>', unsafe_allow_html=True)

    render_user(st.session_state.messages[-1])
    status = st.empty()
    show_status(status, "Thinking")

    answer = st.empty()
    runner = ToolRunner(INDEX)
    final_text = ""
    question = st.session_state.messages[-1].get("text", "")
    # Set only when Streamlit aborts this run from underneath us. The `finally` below
    # must then leave `processing` alone and not issue a rerun of its own: the abort
    # already is one, and clearing the flag on a turn that never finished left the
    # question on screen with no answer, no error and nothing to click.
    interrupted = False

    def fail(message: str, detail: str) -> None:
        """Surface a failure — and drop any notice, which can only contradict it.

        A leftover "retrying with X…" sitting above "could not complete that
        request" is how the UI ended up arguing with itself.
        """
        st.session_state.error = message
        st.session_state.error_detail = detail
        st.session_state.notice = ""
        st.session_state.switched_from = None

    def grounded(messages: list[dict]) -> list[dict]:
        """Retrieve up front, for models that cannot call tools."""
        context, chunks = gather_context(INDEX, question)
        for chunk in chunks:
            runner.sources.append(chunk)
        if not context:
            return messages
        return [
            messages[0],
            {
                "role": "system",
                "content": (
                    "Answer only from these RCC documentation sections. Cite them "
                    "inline as [Title](path) using the exact path in each header, and "
                    "do not restate them at the end — no Sources list and no 'Cited "
                    "from' sentence, because one is printed for you. If they do not "
                    "cover the question, say so.\n\n" + context
                ),
            },
            *messages[1:],
        ]

    # What the deployment budget is actually counting. A turn is one message to the
    # reader and anywhere from one to MAX_TOOL_ROUNDS + 1 requests to the provider,
    # so this — not the message count — is what the shared key is charged for.
    # Cumulative across every round of this turn — see TOOL_RESULT_CHAR_BUDGET.
    tool_chars = 0

    def start(msgs, schemas):
        # Charged as each request is made, not tallied and committed at the end. A
        # turn that fails halfway, or that the reader abandons by touching the page,
        # still cost the provider the calls it made — and a counter that only commits
        # on success drifts loose exactly when things are going wrong and requests
        # are being retried.
        get_limiter().record_calls(1, time.monotonic())
        return llm.start(provider, MODEL.id, msgs, schemas)

    try:
        provider = get_provider(MODEL.provider)
        messages = history.build(
            st.session_state.messages,
            SYSTEM_PROMPT,
            vision=config.sees_images(MODEL.id),
        )
        use_tools = MODEL.supports_tools

        if use_tools:
            try:
                turn = start(messages, TOOL_SCHEMAS)
            except llm.AssistantError as exc:
                if not llm.rejects_tools(exc.original or exc):
                    raise
                # The model does not do tool calls; retrieve up front instead.
                logger.info("%s rejected tools; using single-pass retrieval", MODEL.id)
                use_tools = False
        if not use_tools:
            messages = grounded(messages)
            turn = start(messages, None)

        for round_number in range(config.MAX_TOOL_ROUNDS + 1):
            # Per round, not per turn. `answer.empty()` below wipes the display
            # between rounds, so a stop must keep what is on the screen now — not
            # this round's text appended to a previous round's, which the reader has
            # not been able to see since the tool call that replaced it.
            st.session_state.partial = []
            with answer.container(), st.chat_message("assistant"):
                streamed = st.write_stream(recording(clearing(turn.deltas(), status)))
            # write_stream returns a list when chunks are not all strings.
            if isinstance(streamed, list):
                streamed = "".join(str(part) for part in streamed)
            if streamed:
                final_text = streamed

            if not turn.tool_calls or not use_tools:
                break
            if round_number == config.MAX_TOOL_ROUNDS:
                logger.warning("Tool-round limit reached without a final answer")
                final_text = final_text or (
                    "I wasn't able to finish looking that up. Please try rephrasing "
                    "your question."
                )
                break

            answer.empty()
            show_status(status, describe(turn.tool_calls))
            messages.append(turn.as_message())
            for call in turn.tool_calls:
                result = runner.run(call["name"], call["input"])
                # The budget is cumulative across rounds, which is the whole point:
                # each result is individually legal at MAX_DOC_CHARS and it is the
                # sum that overruns what was trimmed for before the loop started.
                # Clipped rather than dropped, and told so, because a model handed a
                # truncated section can still answer from it or ask for a narrower
                # one — whereas a silent empty result reads as "no such page".
                room = config.TOOL_RESULT_CHAR_BUDGET - tool_chars
                if len(result) > room:
                    result = (
                        result[: max(0, room)]
                        + "\n\n[Truncated: this turn has reached its reading limit. "
                        "Answer from what you have, or say which section you still "
                        "need.]"
                    )
                tool_chars += len(result)
                messages.append(llm.tool_result_message(call, result))
            turn = start(messages, TOOL_SCHEMAS)

        status.empty()

        # An answer that is not there. The turn succeeded — no exception, maybe even a
        # search and a read — and the stream carried nothing but whitespace, which the
        # renderer then had nothing to draw: the transcript skips an assistant message
        # with no text, so what the reader was left with was their own question, no
        # reply, no error card and no button. Raised rather than papered over with a
        # sentence, because the useful thing here is the retry and the model switch the
        # error card already offers.
        if not final_text.strip():
            logger.warning("%s returned an empty answer", MODEL.key)
            raise llm.AssistantError("empty")

        sources = citations(runner.sources)

        # Re-render once with links resolved, so a raw `docs/...md` target never flashes.
        answer.empty()
        st.session_state.messages.append(
            {
                "role": "assistant",
                # Stored stripped, not merely rendered stripped: this text is also what
                # goes back upstream next turn, and a footer in the history is a worked
                # example teaching the model to write another one. Handed the strip's
                # own contents, so an unlabelled list of links can be checked against
                # what the reader is already being shown rather than guessed at.
                #
                # Two passes because the duplication has two shapes: a footer under the
                # answer, and a parenthetical of section titles inside a sentence. The
                # inline one goes first so the footer rules judge the prose that is
                # actually left.
                "text": links.strip_source_footer(
                    links.strip_inline_citations(final_text, sources), CORPUS, sources
                ),
                "sources": sources,
                "rating": None,
                "model": MODEL.key,
            }
        )
        st.session_state.failed_over = False
        # Only now is a failover a fact worth reporting: the replacement model
        # has produced this answer. Any older notice belongs to an older turn.
        switched = st.session_state.switched_from
        st.session_state.switched_from = None
        st.session_state.notice = (
            f"{switched[0]} was unavailable ({REASONS.get(switched[1], switched[1])}), "
            f"so {MODEL.label} answered instead. Pick a different one from the "
            f"model button under the input box."
            if switched
            else ""
        )
        if runner.queries and not sources:
            feedback.record_miss(runner.queries, st.session_state.messages[-2]["text"])
        # A path the corpus does not have is a model inventing a citation. The renderer
        # no longer dresses it up as a working link, which means the only trace it
        # leaves is this line — and a deployment tuning its prompt wants to see it.
        invented = links.unresolved(final_text, CORPUS)
        if invented:
            logger.warning("%s cited %d path(s) that do not exist: %s",
                           MODEL.key, len(invented), ", ".join(invented[:5]))

    except llm.AssistantError as exc:
        status.empty()
        answer.empty()
        alternative = fallback_model()
        if (
            exc.kind in ("quota", "auth")
            and alternative is not None
            and not st.session_state.failed_over
        ):
            # Out of credit on one provider is exactly what the second one is for.
            # Once per turn, so a bad key cannot ping-pong between providers.
            logger.info("%s unusable (%s); failing over to %s",
                        MODEL.key, exc.kind, alternative.key)
            st.session_state.failed_over = True
            st.session_state.failover_to = alternative.key
            st.session_state.switched_from = (MODEL.label, exc.kind)
            # Present tense: the retry has not happened yet. The past-tense
            # version is written only once an answer actually arrives.
            st.session_state.notice = (
                f"{MODEL.label} is unavailable ({REASONS.get(exc.kind, exc.kind)}). "
                f"Retrying with {alternative.label}…"
            )
        else:
            # An "unknown" kind means classify() had nothing to go on, so log the
            # full traceback — otherwise the only signal is a generic message.
            logger.error(
                "Turn failed (%s): %r",
                exc.kind,
                exc.original,
                exc_info=exc.original if exc.kind == "unknown" else None,
            )
            fail(exc.user_message, _detail(exc.original or exc))
    except Exception as exc:  # last-resort guard so the UI never dies
        if is_control_flow(exc):
            # Streamlit's own control flow, not a failure. Re-raised so the rerun or
            # stop it represents actually happens. Still checked here because the
            # hierarchy has moved before and an older build may put these under
            # Exception; on 1.54 the handler below is the one that fires.
            interrupted = True
            raise
        status.empty()
        answer.empty()
        logger.exception("Unexpected failure")
        fail(llm.classify(exc).user_message, _detail(exc))
    except BaseException:
        # Streamlit's control flow does NOT derive from Exception. On 1.54
        # `RerunException.__mro__` is (RerunException, ScriptControlException,
        # BaseException) — so a real rerun, raised at the next `st.*` call inside
        # `st.write_stream` when the reader touches the page mid-answer, sailed past
        # the handler above with `interrupted` still False. The `finally` then cleared
        # `processing` and fired a second `st.rerun()` over the one already in flight,
        # which is exactly the "no answer, no error card, nothing to click" dead end
        # its own comment describes.
        #
        # Below `except Exception`, not above it: an earlier clause wins, so putting
        # BaseException first would make the real-failure handler unreachable.
        #
        # Set for every BaseException, not only the control-flow ones. A
        # KeyboardInterrupt or a SystemExit is also a run that is ending, and calling
        # `st.rerun()` underneath one replaces it with a rerun just the same.
        interrupted = True
        raise
    finally:
        switch_to = st.session_state.pop("failover_to", None)
        if switch_to:
            # `processing` stays True: the same question runs again, on the new
            # model, as soon as the rerun re-enters this block.
            st.session_state.model = switch_to
            st.session_state.error = None
            st.session_state.error_detail = ""
        elif not interrupted:
            st.session_state.processing = False
            # The answer is committed (or the failure is), so the running copy is
            # spent. Left here it would be the text a later stop keeps.
            st.session_state.partial = []
        # Not while interrupted: the abort in flight IS a rerun, and calling another
        # one here replaced it — which left the question on screen with no answer, no
        # error card and nothing to click, because `processing` had been cleared by a
        # turn that never finished.
        if not interrupted:
            st.rerun()
