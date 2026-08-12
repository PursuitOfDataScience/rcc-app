"""One turn: the status line, the tool loop, the answer, and every way it can end."""

from __future__ import annotations

import html
import logging
import time

import streamlit as st

from .. import config, feedback, history, links, llm, prompts
from ..tools import READ_DOC, SEARCH_DOCS, gather_context
from .access import get_provider
from .state import get_limiter
from .transcript import citations, render_user
from .view import View

logger = logging.getLogger(__name__)

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

# The most of a name or a query the status line will say. Neither is written by this
# app — a doc title comes from the corpus and a query from the model — so both need a
# ceiling, and the ceiling has to hold on a phone: at 500px this line has room for
# about 60 characters before it takes a second row, and a progress cue that grows the
# page it sits on is worse than one that says less.
STATUS_MAX = 48


def is_control_flow(exc: BaseException) -> bool:
    return type(exc).__name__ in CONTROL_FLOW_NAMES


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


def _short(text: str) -> str:
    """`text`, cut at a word boundary if it is longer than the line has room for."""
    if len(text) <= STATUS_MAX:
        return text
    cut = text[:STATUS_MAX].rsplit(" ", 1)[0] or text[:STATUS_MAX]
    return f"{cut.rstrip(' ,;:—-')}…"


def describe(corpus, calls: list[dict]) -> str:
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
            chunk = corpus.chunk(path)
            title = chunk.doc_title if chunk else path.split("/")[-1]
            return f"Reading {_short(title)}" if title else "Reading documentation"
    return "Working"


def detail(view: View, exc: BaseException | None) -> str:
    """A one-line, non-secret description of a failure for the details panel."""
    if exc is None:
        return ""
    text = f"{type(exc).__name__}: {exc}"
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    if status:
        text = f"{text}  (HTTP {status})"
    return f"{text}\nmodel={view.model.key}"[:800]


def run(view: View) -> None:
    """Answer the question at the end of the transcript.

    Ends in a rerun on every path that is not already one, because the answer is
    committed to session state and the page has to be redrawn from it — with links
    resolved, the Sources strip under the bubble, and the rating buttons live.
    """
    model = view.model
    runtime = view.runtime

    # Marker element app.js polls to know a generation is in flight.
    st.markdown('<div id="processing-signal" hidden></div>', unsafe_allow_html=True)

    render_user(st.session_state.messages[-1])
    status = st.empty()
    show_status(status, "Thinking")

    answer = st.empty()
    runner = runtime.toolset.runner()
    final_text = ""
    question = st.session_state.messages[-1].get("text", "")
    # Set only when Streamlit aborts this run from underneath us. The `finally` below
    # must then leave `processing` alone and not issue a rerun of its own: the abort
    # already is one, and clearing the flag on a turn that never finished left the
    # question on screen with no answer, no error and nothing to click.
    interrupted = False

    def fail(message: str, why: str) -> None:
        """Surface a failure — and drop any notice, which can only contradict it.

        A leftover "retrying with X…" sitting above "could not complete that
        request" is how the UI ended up arguing with itself.
        """
        st.session_state.error = message
        st.session_state.error_detail = why
        st.session_state.notice = ""
        st.session_state.switched_from = None

    def grounded(messages: list[dict]) -> list[dict]:
        """Retrieve up front, for models that cannot call tools."""
        context, chunks = gather_context(runtime.retriever, question)
        for chunk in chunks:
            runner.sources.append(chunk)
        if not context:
            return messages
        return [
            messages[0],
            {
                "role": "system",
                "content": prompts.grounded_instruction(context, runtime.identity),
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
        return llm.start(provider, model.id, msgs, schemas)

    try:
        provider = get_provider(model.provider)
        messages = history.build(
            st.session_state.messages,
            runtime.system_prompt,
            vision=config.sees_images(model.id),
        )
        use_tools = model.supports_tools

        if use_tools:
            try:
                turn = start(messages, runtime.tool_schemas)
            except llm.AssistantError as exc:
                if not llm.rejects_tools(exc.original or exc):
                    raise
                # The model does not do tool calls; retrieve up front instead.
                logger.info("%s rejected tools; using single-pass retrieval", model.id)
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
            # THIS round's text, not the best text seen so far.
            #
            # It used to keep the last non-empty round, and that turned a model's
            # throat-clearing into an answer. Several of them narrate the tool call
            # they are about to make — "Let me search for more specific Midway3
            # hardware details." — and then, if the round after the search comes back
            # with nothing, that sentence was the only text the turn had. It shipped
            # as the reply, with a Sources strip of four documents under it, looking
            # for all the world like a finished answer that had been cut off. Reported
            # from the running app, with the screenshot.
            #
            # A round that ends in a tool call is the model saying what it is about to
            # do; the answer is whatever the round that stops calling tools produces.
            # If that is nothing, the turn produced no answer, and the empty check
            # below turns it into the error card that offers Try again and another
            # model — which is the truth, and is recoverable, in a way that a
            # confident non-answer is not.
            final_text = streamed or ""

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
            show_status(status, describe(view.corpus, turn.tool_calls))
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
            turn = start(messages, runtime.tool_schemas)

        status.empty()

        # An answer that is not there. The turn succeeded — no exception, maybe even a
        # search and a read — and the stream carried nothing but whitespace, which the
        # renderer then had nothing to draw: the transcript skips an assistant message
        # with no text, so what the reader was left with was their own question, no
        # reply, no error card and no button. Raised rather than papered over with a
        # sentence, because the useful thing here is the retry and the model switch the
        # error card already offers.
        if not final_text.strip():
            logger.warning("%s returned an empty answer", model.key)
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
                    links.strip_inline_citations(final_text, sources),
                    view.corpus,
                    sources,
                ),
                "sources": sources,
                "rating": None,
                "model": model.key,
            }
        )
        st.session_state.failed_over = False
        # Only now is a failover a fact worth reporting: the replacement model
        # has produced this answer. Any older notice belongs to an older turn.
        switched = st.session_state.switched_from
        st.session_state.switched_from = None
        st.session_state.notice = (
            f"{switched[0]} was unavailable ({REASONS.get(switched[1], switched[1])}), "
            f"so {model.label} answered instead. Pick a different one from the "
            f"model button under the input box."
            if switched
            else ""
        )
        if runner.queries and not sources:
            feedback.record_miss(runner.queries, st.session_state.messages[-2]["text"])
        # A path the corpus does not have is a model inventing a citation. The renderer
        # no longer dresses it up as a working link, which means the only trace it
        # leaves is this line — and a deployment tuning its prompt wants to see it.
        invented = links.unresolved(final_text, view.corpus)
        if invented:
            logger.warning("%s cited %d path(s) that do not exist: %s",
                           model.key, len(invented), ", ".join(invented[:5]))

    except llm.AssistantError as exc:
        status.empty()
        answer.empty()
        alternative = view.fallback
        if (
            exc.kind in ("quota", "auth")
            and alternative is not None
            and not st.session_state.failed_over
        ):
            # Out of credit on one provider is exactly what the second one is for.
            # Once per turn, so a bad key cannot ping-pong between providers.
            logger.info("%s unusable (%s); failing over to %s",
                        model.key, exc.kind, alternative.key)
            st.session_state.failed_over = True
            st.session_state.failover_to = alternative.key
            st.session_state.switched_from = (model.label, exc.kind)
            # Present tense: the retry has not happened yet. The past-tense
            # version is written only once an answer actually arrives.
            st.session_state.notice = (
                f"{model.label} is unavailable ({REASONS.get(exc.kind, exc.kind)}). "
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
            fail(exc.user_message, detail(view, exc.original or exc))
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
        fail(llm.classify(exc).user_message, detail(view, exc))
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
