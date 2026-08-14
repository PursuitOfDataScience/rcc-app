"""Run one real turn through the app's own loop, and record what happened.

The point of this module is that it measures **the app**, not a copy of it. There is a
version of an agent benchmark that reimplements `history.build` → `llm.start` → tool
rounds → final text in forty lines and measures that; it drifts from `sage/ui/turn.py`
the first time the real loop changes, and then it is measuring a fiction. So this
drives `app.py` itself, exactly as `tests/test_app_smoke.py` does — the same stubbed
Streamlit, the same session state, the same `turn.run` — with a real provider behind it
and instrumentation around the seams.

What that buys, beyond fidelity: the record includes the answer **after**
`links.strip_inline_citations` and `strip_source_footer` have rewritten it, which is
the text a reader actually gets, and the raw text before them, which is the only way
to see what those 840 lines of regular expressions removed.

    from evals import harness
    harness.prepare()                                   # once per process
    record = harness.run_turn("how do I submit a job", "opencode:big-pickle")

Everything network-bound is in the provider. Point `OPENCODE_BASE_URL` at
`tools/mock_provider.py` and the whole harness runs offline, which is how
`tests/test_bench_harness.py` proves the instrument measures what it claims to.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# The stubbed Streamlit is the app's only headless driver and it lives with the tests,
# which is the right place for it — it is a test double, not a shipped module. Rather
# than copy three hundred lines here, the tests directory goes on the path.
if os.path.join(ROOT, "tests") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "tests"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import stub_streamlit  # noqa: E402
from sage import links, llm, providers, runtime  # noqa: E402
from sage import tools as tools_module  # noqa: E402
from sage.profile import active as _active  # noqa: E402

# How many script runs one question may take. A turn that fails over asks the next
# model on the *following* run — that is what `failover_to` and `st.rerun()` mean — so a
# harness that imports the app once would record the failure and never see the answer.
# Six covers MAX_MODEL_HOPS plus the cross-provider hop with room to spare.
MAX_SCRIPT_RUNS = 6


@dataclass
class Trace:
    """Everything the seams saw during one question."""

    calls: int = 0
    tools_offered: list[bool] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    first_byte: float | None = None
    first_text: float | None = None
    raw_answers: list[str] = field(default_factory=list)
    started: float = 0.0
    # The last request's shape. Kept rather than the request itself: a multi-turn
    # conversation carrying two attachments is most of a megabyte, and what is wanted
    # from it is its size, its roles, and whether the question is still in it.
    sent_chars: int = 0
    sent_roles: list[str] = field(default_factory=list)
    sent_text: str = ""

    def stamp(self, which: str) -> None:
        if getattr(self, which) is None:
            setattr(self, which, round(time.monotonic() - self.started, 3))

    def record_request(self, messages: list[dict]) -> None:
        flat = "\n".join(str(message.get("content", "")) for message in messages)
        self.sent_chars = len(flat)
        self.sent_roles = [str(message.get("role", "")) for message in messages]
        self.sent_text = flat

    def question_was_sent(self, question: str) -> bool:
        return question.strip().lower() in self.sent_text.lower()


_TRACE = Trace()


class Recorder:
    """A real provider with a tally around it.

    Wraps rather than replaces: the stream, the errors and the model list are the
    provider's own. What is added is when the first byte arrived, when the first *text*
    arrived (which is what a reader waits for, and is not the same thing on a turn that
    opens with a tool call), and how many requests the question really cost.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.name = inner.name
        self._models: list | None = None

    def models(self):
        # Cached because every script run rebuilds `access.available_models`, and a
        # benchmark that re-discovered the lineup once per question would spend a
        # request per question on it and measure the discovery call's latency too.
        if self._models is None:
            try:
                self._models = self._inner.models()
            except Exception as exc:  # a lineup that cannot be listed is data
                _TRACE.errors.append(f"models: {type(exc).__name__}: {exc}")
                self._models = []
        return self._models

    def stream(self, model, messages, tools):
        _TRACE.calls += 1
        _TRACE.tools_offered.append(bool(tools))
        _TRACE.record_request(messages)
        try:
            for chunk in self._inner.stream(model, messages, tools):
                _TRACE.stamp("first_byte")
                if getattr(chunk, "text", ""):
                    _TRACE.stamp("first_text")
                yield chunk
        except Exception as exc:
            _TRACE.errors.append(f"{type(exc).__name__}: {exc}")
            raise


_PROVIDERS: dict[str, Recorder] = {}
_RUNTIME: runtime.Runtime | None = None
_ORIGINALS: dict[str, object] = {}


def restore() -> None:
    """Put the four patched seams back.

    Not housekeeping: these are patches on modules the whole process shares, so a test
    that prepared the harness and did not restore it would hand `sage.providers.build`
    to every test file that ran afterwards. `tests/test_bench_harness.py` restores in a
    fixture teardown for exactly that reason.
    """
    if not _ORIGINALS:
        return
    providers.build = _ORIGINALS["providers.build"]
    runtime.build = _ORIGINALS["runtime.build"]
    tools_module.ToolRunner.run = _ORIGINALS["ToolRunner.run"]
    links.strip_inline_citations = _ORIGINALS["strip_inline_citations"]
    _ORIGINALS.clear()
    _PROVIDERS.clear()


def prepare(build_provider=None, *, fresh: bool = False) -> runtime.Runtime:
    """Patch the four seams and build the index once. Idempotent unless `fresh`.

    Every patch is on a module `stub_streamlit.forget_importers()` leaves alone
    (`sage.providers`, `sage.runtime`, `sage.tools`, `sage.links`), which is why they
    survive the re-import that each script run performs. Patching anything under
    `sage.ui` would silently come undone on the second question.
    """
    global _RUNTIME

    if fresh:
        restore()
        _RUNTIME = None

    if _RUNTIME is None:
        _RUNTIME = runtime.build()

    if _ORIGINALS:
        return _RUNTIME

    _ORIGINALS.update(
        {
            "providers.build": providers.build,
            "runtime.build": runtime.build,
            "ToolRunner.run": tools_module.ToolRunner.run,
            "strip_inline_citations": links.strip_inline_citations,
        }
    )
    make = build_provider or _ORIGINALS["providers.build"]

    def build(name: str, api_key: str):
        if name not in _PROVIDERS:
            _PROVIDERS[name] = Recorder(make(name, api_key))
        return _PROVIDERS[name]

    providers.build = build
    # The app asks for a Runtime once per script run, and indexing 572 chunks per
    # question would dominate the wall clock of a benchmark that is measuring models.
    runtime.build = lambda profile=None: _RUNTIME

    inner_run = tools_module.ToolRunner.run

    def run(self, name, arguments):
        started = time.monotonic()
        result = inner_run(self, name, arguments)
        _TRACE.tool_calls.append(
            {
                "name": name,
                "arguments": arguments,
                "seconds": round(time.monotonic() - started, 3),
                "chars": len(result),
                # The one thing a tool result says about the model rather than the
                # index: a path it made up comes back as an error it has to recover
                # from, and that recovery is what the loop is being measured on.
                "error": result.startswith("Error:") or result.startswith("Unknown tool"),
                "no_results": "No matching" in result[:200],
            }
        )
        return result

    tools_module.ToolRunner.run = run

    inner_strip = links.strip_inline_citations

    def strip(text, sources=None):
        # The last moment the model's own words exist. `turn.run` stores the rewritten
        # text, so without this there is nothing to compare the rewrite against.
        _TRACE.raw_answers.append(text)
        return inner_strip(text, sources)

    links.strip_inline_citations = strip

    return _RUNTIME


def _reinstall(stub) -> None:
    """Put the *same* stub back after forgetting the app, which is one script run.

    `stub_streamlit.install()` would make a new one, and a new one has empty session
    state — so a failover, which is carried from one run to the next in
    `st.session_state.failover_to`, could never happen.
    """
    stub_streamlit.forget_importers()
    sys.modules["streamlit"] = stub
    sys.modules["streamlit.components"] = stub.components
    sys.modules["streamlit.components.v1"] = stub.components.v1


def _kinds_by_message() -> dict[str, str]:
    """User-facing error text back to the kind that produced it.

    `turn.run` puts `exc.user_message` in session state and keeps the kind to itself.
    Reading it back out of the message is how the bench reports *why* a model failed
    without reaching into the turn, and the table is built the same way the exception
    builds the message so a reworded message cannot silently stop matching.
    """
    operator = _active().identity.operator
    return {
        text.replace("{operator}", operator): kind
        for kind, text in llm._MESSAGES.items()
    }


def run_turn(
    question: str,
    model_key: str,
    *,
    expect: str = "answer",
    must_mention: tuple[str, ...] = (),
    pages: tuple[str, ...] = (),
    attachments: list | None = None,
    stub_kwargs: dict | None = None,
) -> dict:
    """Ask one question on one model, and return everything observable about it.

    `expect` is `"answer"` for a question the corpus covers and `"caveat"` for one it
    does not; it is carried into the record because the answer checks are asymmetric — a
    fenced command block is right on one side and a defect on the other.
    """
    stub = stub_streamlit.install(**(stub_kwargs or {}))
    return _drive(
        stub, question, model_key,
        expect=expect, must_mention=must_mention, pages=pages,
        attachments=attachments,
    )


def run_conversation(turns: list[dict], model_key: str, **shared) -> list[dict]:
    """Several questions in one session, which is where a retrieval agent rots.

    One stub for the whole conversation, so `st.session_state.messages` accumulates
    exactly as it does for a reader: the follow-up is answered with the earlier turns in
    the request, and `history.build` trims them under the same budget. A harness that
    re-installed between questions would measure a series of first questions.

    Each turn is `{"text": ..., "pages": (...), "must_mention": (...), "expect": ...}`.
    """
    stub = stub_streamlit.install()
    records = []
    for position, turn in enumerate(turns):
        record = _drive(
            stub,
            str(turn["text"]),
            model_key,
            expect=str(turn.get("expect", "answer")),
            must_mention=tuple(turn.get("must_mention", ())),
            pages=tuple(turn.get("pages", ())),
            attachments=turn.get("attachments"),
            **shared,
        )
        record["turn_index"] = position
        record["conversation_length"] = len(turns)
        records.append(record)
    return records


def _drive(
    stub,
    question: str,
    model_key: str,
    *,
    expect: str = "answer",
    must_mention: tuple[str, ...] = (),
    pages: tuple[str, ...] = (),
    attachments: list | None = None,
) -> dict:
    """One turn against an existing stub. The whole measurement lives here.

    Kept separate from `run_turn` so a conversation can reuse the same session, and so
    the state reset below happens in exactly one place. That reset mirrors
    `state.start_new_turn`, minus the limiter: `tried` and `failed_over` belong to the
    turn that just ended, and a second question that inherits them would believe every
    model had already refused it.
    """
    global _TRACE

    sage = prepare()
    _TRACE = Trace(started=time.monotonic())

    state = stub.session_state
    state.setdefault("messages", [])
    state["messages"].append(
        {"role": "user", "text": question, "attachments": list(attachments or [])}
    )
    state["processing"] = True
    state["model"] = model_key
    state["error"] = None
    state["error_detail"] = ""
    state["notice"] = ""
    state["failed_over"] = False
    state["tried"] = []
    state["switched_from"] = None
    before = len(state["messages"])

    runs = 0
    fatal = ""
    while runs < MAX_SCRIPT_RUNS:
        runs += 1
        if runs > 1 or "app" in sys.modules:
            _reinstall(stub)
        try:
            import app  # noqa: F401, PLC0415
        except (stub_streamlit.Rerun, stub_streamlit.Stop):
            pass
        except BaseException as exc:  # noqa: BLE001 — a crash is a result, not a stop
            fatal = f"{type(exc).__name__}: {exc}"
            break
        if not state.get("processing"):
            break

    elapsed = round(time.monotonic() - _TRACE.started, 3)
    messages = state.get("messages") or []
    reply = (
        messages[-1]
        if len(messages) >= before and messages[-1].get("role") == "assistant"
        else {}
    )
    text = str(reply.get("text") or "")
    sources = list(reply.get("sources") or [])
    error = state.get("error")

    if fatal:
        outcome = "crashed"
    elif text.strip():
        outcome = "answered"
    elif error:
        outcome = "refused"
    else:
        outcome = "nothing"

    evidence = {}
    # Pages resolved through the corpus rather than sliced off the id. A chunk id is
    # `{source}/{path}#{anchor}` and a gold label is `{path}`; cutting the prefix by hand
    # made every gold comparison miss, silently, and read as a model that never cited the
    # right page.
    cited_pages = set()
    for source in sources:
        chunk = sage.corpus.chunk(str(source.get("id", "")))
        if chunk is not None:
            evidence[chunk.id] = chunk.text
            cited_pages.add(chunk.path)

    searches = [
        call for call in _TRACE.tool_calls if call["name"] == tools_module.SEARCH_DOCS
    ]
    reads = [call for call in _TRACE.tool_calls if call["name"] == tools_module.READ_DOC]

    return {
        "question": question,
        "model": model_key,
        "expect": expect,
        "pages": list(pages),
        "must_mention": list(must_mention),
        "attachments": [item.filename for item in (attachments or [])],
        "outcome": outcome,
        "error": error or "",
        "error_kind": _kinds_by_message().get(error or "", "" if not error else "unknown"),
        "fatal": fatal,
        "text": text,
        "raw": _TRACE.raw_answers[-1] if _TRACE.raw_answers else "",
        "sources": sources,
        "source_pages": sorted(cited_pages),
        "evidence": evidence,
        "answered_by": str(reply.get("model") or ""),
        "notice": str(state.get("notice") or ""),
        "script_runs": runs,
        "provider_calls": _TRACE.calls,
        "tools_offered": any(_TRACE.tools_offered),
        "rounds": len(_TRACE.tools_offered),
        "tool_calls": list(_TRACE.tool_calls),
        "searches": len(searches),
        "reads": len(reads),
        "queries": [str(call["arguments"].get("query", "")) for call in searches],
        "read_errors": sum(1 for call in reads if call["error"]),
        "empty_searches": sum(1 for call in searches if call["no_results"]),
        "tool_chars": sum(call["chars"] for call in _TRACE.tool_calls),
        "stream_chunks": list(stub.stream_chunks),
        "seconds": elapsed,
        "first_byte": _TRACE.first_byte,
        "first_text": _TRACE.first_text,
        "provider_errors": list(_TRACE.errors),
        # What actually went upstream on the last request. The history budget trims
        # oldest-first and once clipped a turn at exactly the point the question began,
        # leaving the model two files and no question — so whether the question survived
        # is measured rather than assumed.
        "sent_chars": _TRACE.sent_chars,
        "sent_roles": list(_TRACE.sent_roles),
        "question_sent": _TRACE.question_was_sent(question),
    }
