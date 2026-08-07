#!/usr/bin/env python3
"""Sage — the RCC User Guide assistant (Streamlit UI).

Retrieval, chunking, ranking, link resolution and file handling live in the `sage`
package so they can be unit-tested without Streamlit. This module is only the view:
session state, layout, and the tool loop that drives them.
"""

from __future__ import annotations

import html
import logging
import os

import streamlit as st
import streamlit.components.v1 as components

from sage import config, feedback, files, history, links, llm, providers
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

INDEX = get_index()
CORPUS = INDEX.corpus

for key, default in (
    ("messages", []),
    ("processing", False),
    ("attachment", None),
    ("uploader_key", 0),
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


# --- rendering helpers -----------------------------------------------------


def escape(text: str) -> str:
    return html.escape(text, quote=False).replace("\n", "<br>")


def render_user(message: dict) -> None:
    attachment = message.get("attachment")
    badge = ""
    if attachment is not None:
        badge = (
            f'<div class="attachment-badge">{attachment.icon} '
            f"{html.escape(attachment.filename)}</div>"
        )
    st.markdown(
        f'<div class="user-message"><div class="user-bubble">{badge}'
        f'{escape(message.get("text", ""))}</div></div>',
        unsafe_allow_html=True,
    )


def related_sections(sources: list[dict], limit: int = 3) -> list[dict]:
    """Sibling sections of the pages actually cited — discovery for free.

    No extra model call: the chunks are already indexed, so neighbouring sections
    of a cited page are known and are always real documentation.
    """
    cited = {source["id"] for source in sources}
    pages = {source["id"].split("#", 1)[0] for source in sources}
    out: list[dict] = []
    for chunk in CORPUS.chunks:
        if len(out) >= limit:
            break
        page = f"{chunk.source}/{chunk.path}"
        if page in pages and chunk.id not in cited and chunk.heading:
            out.append({"label": chunk.heading, "url": chunk.url})
    return out


def render_sources(sources: list[dict], related: list[dict]) -> None:
    if not sources:
        return
    chips = "".join(
        f'<a class="source-chip" href="{html.escape(source["url"], quote=True)}" '
        f'target="_blank" rel="noopener noreferrer">{html.escape(source["label"])}'
        f'<span class="source-kind">{html.escape(source["source"])}</span></a>'
        for source in sources
    )
    strip = f'<div class="sources"><span class="sources-label">Sources</span>{chips}</div>'

    if related:
        more = "".join(
            f'<a class="source-chip" href="{html.escape(item["url"], quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">{html.escape(item["label"])}</a>'
            for item in related
        )
        strip += (
            f'<div class="sources"><span class="sources-label">Related</span>{more}</div>'
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
                if st.button(glyph, key=f"rate-{position}-{verdict}", help=hint):
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
            st.markdown(links.fix_links(message.get("text", ""), CORPUS))
        sources = message.get("sources", [])
        render_sources(sources, related_sections(sources))
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


def describe(calls: list[dict]) -> str:
    """Say what is actually happening instead of a generic shimmer."""
    for call in calls:
        if call["name"] == SEARCH_DOCS:
            query = (call["input"].get("query") or "").strip()
            return f"Searching the docs for “{query}”" if query else "Searching the docs"
    for call in calls:
        if call["name"] == READ_DOC:
            path = (call["input"].get("path") or "").strip()
            chunk = CORPUS.chunk(path)
            label = chunk.label if chunk else path.split("/")[-1]
            return f"Reading {label}" if label else "Reading documentation"
    return "Working"


def start_new_turn(question: str, attachment=None) -> None:
    st.session_state.messages.append(
        {"role": "user", "text": question, "attachment": attachment}
    )
    st.session_state.processing = True
    st.session_state.error = None
    st.session_state.attachment = None
    st.session_state.uploader_key += 1
    st.rerun()


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
    with st.popover(MODEL.label):
        st.caption("Answering model · Zen models are free")
        with st.container(key="model-list"):
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
            st.session_state.attachment = None
            st.session_state.error = None
            st.session_state.notice = ""
            st.session_state.failed_over = False
            st.session_state.switched_from = None
            st.session_state.uploader_key += 1
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
                        start_new_turn(question)
else:
    # Marker only: app.js keys page-scroll behaviour off its presence — without it
    # the screen is the landing screen, which always starts at the top.
    st.markdown('<div class="chat-container"></div>', unsafe_allow_html=True)

    rendered = st.session_state.messages
    if st.session_state.processing and rendered and rendered[-1]["role"] == "user":
        rendered = rendered[:-1]

    for position, message in enumerate(rendered):
        if message["role"] == "user":
            render_user(message)
        elif message.get("text"):
            render_assistant(position, message)

    if st.session_state.notice:
        st.markdown(
            f'<div class="notice">{html.escape(st.session_state.notice)}</div>',
            unsafe_allow_html=True,
        )

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
            if switch:
                st.session_state.model = alternative.key
                st.session_state.failed_over = False
                st.session_state.switched_from = None
            st.session_state.error = None
            st.session_state.error_detail = ""
            if st.session_state.messages[-1]["role"] == "user":
                st.session_state.processing = True
            st.rerun()


# --- input -----------------------------------------------------------------

upload = st.file_uploader(
    "Attach a file",
    type=list(config.UPLOAD_EXTENSIONS),
    key=f"uploader-{st.session_state.uploader_key}",
    label_visibility="collapsed",
)

if upload is not None and st.session_state.attachment is None:
    attachment, error = files.process(upload.name, upload.getvalue())
    if error:
        st.session_state.uploader_key += 1
        st.warning(f"⚠️ {error}")
        st.rerun()
    st.session_state.attachment = attachment

if st.session_state.attachment is not None:
    current = st.session_state.attachment
    with st.container(key="attachment"):
        if st.button(
            f"{current.icon} {current.filename} · {current.summary}  ✕",
            key="drop-attachment",
        ):
            st.session_state.attachment = None
            st.session_state.uploader_key += 1
            st.rerun()

# No `max_chars`. That argument is the only thing that puts Streamlit's "15/8000"
# counter inside the box, and a running character count is noise in a box you type a
# question into — it reads as a form field with a quota. The limit itself is still
# enforced, below, where it costs nothing to look at.
#
# Enforced here rather than hidden with CSS on purpose: the counter's own test id is
# Streamlit's, unversioned, and not visible from this repo, so a rule naming it would
# be a guess that fails silently the day it changes. Not asking for the counter
# cannot fail that way.
prompt = st.chat_input("Ask anything about RCC…")

# Rendered here, before the turn below: that block ends in `st.rerun()`, so
# anything after it is never reached while an answer is generating — which is
# exactly when a user whose model just ran out of credit reaches for the picker.
render_controls()

if prompt:
    asked = prompt.strip()
    if len(asked) > config.MAX_PROMPT_CHARS:
        # The cap the counter used to advertise. Said once, at the moment it matters,
        # instead of counted out on screen for every question that was never near it.
        over = len(asked) - config.MAX_PROMPT_CHARS
        st.warning(
            f"⚠️ That question is {over:,} characters over the "
            f"{config.MAX_PROMPT_CHARS:,}-character limit. Shorten it, or attach the "
            "long part as a file."
        )
    else:
        start_new_turn(asked, st.session_state.attachment)


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
                    "as [Title](path) using the exact path in each header. If they "
                    "do not cover the question, say so.\n\n" + context
                ),
            },
            *messages[1:],
        ]

    try:
        provider = get_provider(MODEL.provider)
        messages = history.build(st.session_state.messages, SYSTEM_PROMPT)
        use_tools = MODEL.supports_tools

        if use_tools:
            try:
                turn = llm.start(provider, MODEL.id, messages, TOOL_SCHEMAS)
            except llm.AssistantError as exc:
                if not llm.rejects_tools(exc.original or exc):
                    raise
                # The model does not do tool calls; retrieve up front instead.
                logger.info("%s rejected tools; using single-pass retrieval", MODEL.id)
                use_tools = False
        if not use_tools:
            messages = grounded(messages)
            turn = llm.start(provider, MODEL.id, messages, None)

        for round_number in range(config.MAX_TOOL_ROUNDS + 1):
            with answer.container(), st.chat_message("assistant"):
                streamed = st.write_stream(clearing(turn.deltas(), status))
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
                messages.append(
                    llm.tool_result_message(call, runner.run(call["name"], call["input"]))
                )
            turn = llm.start(provider, MODEL.id, messages, TOOL_SCHEMAS)

        status.empty()
        sources = [
            {
                "id": chunk.id,
                "label": chunk.label,
                "url": chunk.url,
                "source": chunk.source,
            }
            for chunk in runner.sources
        ]

        # Re-render once with links resolved, so a raw `docs/...md` target never flashes.
        answer.empty()
        st.session_state.messages.append(
            {
                "role": "assistant",
                "text": final_text,
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
        status.empty()
        answer.empty()
        logger.exception("Unexpected failure")
        fail(llm.classify(exc).user_message, _detail(exc))
    finally:
        switch_to = st.session_state.pop("failover_to", None)
        if switch_to:
            # `processing` stays True: the same question runs again, on the new
            # model, as soon as the rerun re-enters this block.
            st.session_state.model = switch_to
            st.session_state.error = None
            st.session_state.error_detail = ""
        else:
            st.session_state.processing = False
        st.rerun()
