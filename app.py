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

from sage import config, feedback, files, history, links, llm
from sage import corpus as corpus_mod
from sage.prompts import SYSTEM_PROMPT
from sage.search import Index
from sage.tools import READ_DOC, SEARCH_DOCS, TOOL_SCHEMAS, ToolRunner

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.WARNING),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sage.app")

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

EXAMPLES = [
    ("🚀", "How do I connect to Midway via SSH?"),
    ("💾", "What are the storage quotas on Midway?"),
    ("⚙️", "How do I submit a batch job with sbatch?"),
    ("🐍", "How do I set up a Python environment?"),
    ("🎮", "How do I run PyTorch on GPUs?"),
    ("📊", "How do I check my allocation balance?"),
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


def resolve_api_key() -> str:
    key = config.api_key()
    if key:
        return key
    try:
        return str(st.secrets.get("MISTRAL_API_KEY", ""))
    except Exception:  # no secrets.toml present
        return ""


@st.cache_resource(show_spinner=False)
def get_client():
    """Cached without arguments so the key never lands in a cache identity."""
    return llm.create_client(resolve_api_key())


API_KEY = resolve_api_key()
if not API_KEY:
    st.error(
        "**MISTRAL_API_KEY is not set.** Export it in the environment, or add it to "
        "`.streamlit/secrets.toml`, then reload."
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
):
    st.session_state.setdefault(key, default)


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


# --- top bar ---------------------------------------------------------------


def render_about() -> None:
    stamp = config.snapshot()
    synced = stamp.get("refreshed_at", "unknown")
    commit = stamp.get("user_guide_commit", "unknown")
    # Escaped even though these are operator-set, not user-set: an env var landing
    # unescaped inside an href is the kind of thing that stops being harmless later.
    help_url = html.escape(config.HELP_DESK_URL, quote=True)
    help_email = html.escape(config.HELP_DESK_EMAIL, quote=True)
    st.markdown(
        f"""
        <div class="about-panel">
        <h4>What Sage is</h4>
        A read-only assistant for the UChicago
        <a href="https://rcc.uchicago.edu/" target="_blank" rel="noopener">Research
        Computing Center</a>. Every answer is retrieved from the official User Guide
        and RCC website, and cites the sections it used.
        <h4>What it cannot do</h4>
        <ul>
          <li>Run commands or read files on the cluster</li>
          <li>See your account, jobs, quotas or allocations</li>
          <li>Change anything — it only reads documentation</li>
        </ul>
        <h4>Still stuck?</h4>
        Contact the <a href="{help_url}" target="_blank"
        rel="noopener">RCC Help Desk</a> or email
        <a href="mailto:{help_email}">{help_email}</a>.
        The walk-in lab is in Regenstein 216 during business hours.
        <p class="about-meta">Documentation synced {html.escape(str(synced))} ·
        user-guide <code>{html.escape(str(commit))}</code> ·
        {html.escape(corpus_mod.summarize(CORPUS))}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


has_messages = bool(st.session_state.messages)

with st.container(key="topbar"):
    slots = st.columns([1, 1], gap="small") if has_messages else [st.container()]
    with slots[0], st.popover("ℹ️", help="About Sage"):
        render_about()
    if has_messages:
        with slots[1]:
            if st.button("🗑️", key="clear", help="Clear this conversation"):
                st.session_state.messages = []
                st.session_state.processing = False
                st.session_state.attachment = None
                st.session_state.error = None
                st.session_state.uploader_key += 1
                st.rerun()


# --- body ------------------------------------------------------------------

if not has_messages:
    st.markdown(
        """
        <div class="welcome">
            <h1 class="welcome-title">What can I help you with?</h1>
            <p class="welcome-subtitle">Answered from the official UChicago RCC
            documentation, with links to the sections used.</p>
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
                icon, question = EXAMPLES[position]
                with column, st.container(key=f"example-card-{position}"):
                    if st.button(
                        f"{icon} {question}",
                        key=f"example-{position}",
                        use_container_width=True,
                    ):
                        start_new_turn(question)
else:
    # Marker only: app.js keys page-scroll behaviour off its presence.
    st.markdown('<div class="chat-container"></div>', unsafe_allow_html=True)

    rendered = st.session_state.messages
    if st.session_state.processing and rendered and rendered[-1]["role"] == "user":
        rendered = rendered[:-1]

    for position, message in enumerate(rendered):
        if message["role"] == "user":
            render_user(message)
        elif message.get("text"):
            render_assistant(position, message)

    if st.session_state.error and not st.session_state.processing:
        st.markdown(
            '<div class="error-card" role="alert">'
            '<div class="error-title">Could not complete that request</div>'
            f'<div class="error-body">{html.escape(st.session_state.error)}</div></div>',
            unsafe_allow_html=True,
        )
        columns = st.columns([1, 1, 1])
        with columns[1]:
            if st.button("↻ Try again", key="retry", use_container_width=True):
                st.session_state.error = None
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
            help="Remove this attachment",
        ):
            st.session_state.attachment = None
            st.session_state.uploader_key += 1
            st.rerun()

prompt = st.chat_input(
    "Ask anything about RCC…",
    max_chars=config.MAX_PROMPT_CHARS,
)

if prompt:
    start_new_turn(prompt.strip(), st.session_state.attachment)


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

    try:
        client = get_client()
        messages = history.build(st.session_state.messages, SYSTEM_PROMPT)
        turn = llm.start(client, messages, TOOL_SCHEMAS)

        for round_number in range(config.MAX_TOOL_ROUNDS + 1):
            with answer.container(), st.chat_message("assistant"):
                streamed = st.write_stream(clearing(turn.deltas(), status))
            # write_stream returns a list when chunks are not all strings.
            if isinstance(streamed, list):
                streamed = "".join(str(part) for part in streamed)
            if streamed:
                final_text = streamed

            if not turn.tool_calls:
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
            turn = llm.start(client, messages, TOOL_SCHEMAS)

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
            {"role": "assistant", "text": final_text, "sources": sources, "rating": None}
        )
        if runner.queries and not sources:
            feedback.record_miss(runner.queries, st.session_state.messages[-2]["text"])

    except llm.AssistantError as exc:
        status.empty()
        answer.empty()
        # An "unknown" kind means classify() had nothing to go on, so log the full
        # traceback — otherwise the only signal is a generic message on screen.
        logger.error(
            "Turn failed (%s): %r",
            exc.kind,
            exc.original,
            exc_info=exc.original if exc.kind == "unknown" else None,
        )
        st.session_state.error = exc.user_message
    except Exception as exc:  # last-resort guard so the UI never dies
        status.empty()
        answer.empty()
        logger.exception("Unexpected failure")
        st.session_state.error = llm.classify(exc).user_message
    finally:
        st.session_state.processing = False
        st.rerun()
