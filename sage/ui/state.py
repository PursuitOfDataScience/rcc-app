"""Session state, the limiter, and the three moments a turn begins or ends.

Everything Streamlit remembers between runs is declared in one place here, with the
reason each key exists next to it, and every path that starts a turn goes through
`start_new_turn` — which is what makes `may_start_turn` a gate rather than a
suggestion.
"""

from __future__ import annotations

import copy
import logging
import time

import streamlit as st

from .. import config, limits
from .access import whoami

logger = logging.getLogger(__name__)

SESSION_DEFAULTS: tuple[tuple[str, object], ...] = (
    ("messages", []),
    ("processing", False),
    # A list, not one file. Holding one meant the guard in `uploads` dropped anything
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
    # Set by the stop button's callback, which runs before the script does. Read
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
    # Bumped every time the editor opens, and spliced into its widget keys so no key
    # is ever reused. See `transcript.render_user_editor`.
    ("edit_session", 0),
    ("error", None),
    ("error_detail", ""),
    ("model", ""),
    ("notice", ""),
    ("failed_over", False),
    # Models this turn has already asked and been refused by. A refusal about a
    # model — a spent free allowance — may be walked past to the next one, and
    # this is what stops the walk landing back where it started.
    ("tried", []),
    # (label, kind) of a model an automatic failover moved off. Held until the
    # replacement has actually answered, so the notice can never claim a switch
    # worked while an error card below it says it did not.
    ("switched_from", None),
)


def initialise() -> None:
    """Give this session its own copy of every default.

    A copy, and the word is load-bearing. `SESSION_DEFAULTS` is built once, when this
    module is imported — once per *process*, not once per session — so the `[]` beside
    `messages` is a single list object. Handing it to `setdefault` gave every session
    in the process the same list: one reader's question appended to it appeared in
    another reader's transcript, and the app opened on somebody else's conversation
    instead of the landing screen. On a public deployment that is other people's
    questions, their attachments, and whatever they pasted into them.

    This is a regression the refactor introduced and nothing caught. The list used to
    be written inside `app.py`'s module body, which Streamlit re-executes on every
    script run, so a fresh `[]` was built for each session by accident rather than on
    purpose. Moving the declaration into a module that is imported once removed the
    accident and left nothing in its place.

    `deepcopy` rather than a table of factories: it cannot be got wrong later. A new
    mutable default added to that tuple is safe the day it is written, with no one
    having to notice that it needs to be.
    """
    for key, default in SESSION_DEFAULTS:
        if key not in st.session_state:
            st.session_state[key] = copy.deepcopy(default)


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


def start_new_turn(
    question: str, attachments=None, replacing: int | None = None
) -> None:
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
    st.session_state.tried = []
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


def clear_conversation() -> None:
    st.session_state.messages = []
    st.session_state.processing = False
    st.session_state.partial = []
    st.session_state.stop_requested = False
    st.session_state.editing = None
    st.session_state.edit_session += 1
    st.session_state.attachments = []
    st.session_state.dropped_uploads = {}
    st.session_state.upload_refusals = {}
    st.session_state.error = None
    st.session_state.notice = ""
    st.session_state.failed_over = False
    st.session_state.tried = []
    st.session_state.switched_from = None
    st.session_state.uploader_key += 1
    # Nothing here can empty the composer — the text in it is client-side state
    # Streamlit only reads on submit — so clearing the conversation left the last
    # question sitting in the box on the landing screen, over a set of starter cards,
    # as if it were still about to be sent. app.js empties it when this counter moves.
    st.session_state.clear_token += 1
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
# write — and until now the abort was something the app only defended against
# (`interrupted`, and the `disabled=` on the rating buttons). A stop is that same
# abort, asked for on purpose, with one flag set to say so.
#
# The order the pieces run in is what makes it work:
#
#   1. `request_stop` is an `on_click` callback, so it runs BEFORE the script does
#      on the run that follows the click. A button whose value were merely read where
#      it is rendered would be read at the bottom of the page, long after the
#      transcript above it had been drawn for a turn that is no longer running.
#   2. `finish_stopped_turn` runs at the top, before anything is drawn.
#   3. The turn block at the end sees `processing` cleared and does not start again.


def request_stop() -> None:
    st.session_state.stop_requested = True


def finish_stopped_turn(model_key: str) -> None:
    """Keep what arrived before the reader pressed stop, and end the turn there.

    The half-written answer is kept rather than thrown away. It is what was on the
    screen at the moment of the click — often it is the answer, and the reader
    stopped it because they had already read enough — and deleting it would make the
    button destructive in a way nothing about a square suggests.

    A stop with nothing to keep still appends a message, empty. The transcript skips
    an assistant message with no text, so without one the reader is left looking at
    their own question with no reply, no error and nothing to click: the exact dead
    end this app has fixed twice before. `stopped` is what `render_assistant` reads
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
    # next run, `processing` is set again by the turn's `finally`, and the turn the
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
            "model": model_key,
            "stopped": True,
        }
    )
    logger.info("Turn stopped by the reader after %d characters", len(text))
