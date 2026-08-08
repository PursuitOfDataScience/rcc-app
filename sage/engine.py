"""The agent loop — search, read, answer — with no view attached.

This used to live inside `app.py`, welded to `st.write_stream`, `st.session_state`
and `st.rerun`, which meant the most interesting 200 lines in the repo could only
run inside a Streamlit script and could only be tested through a stub of one. The
loop is the same loop; what changed is that it now yields `Event`s and lets the
caller decide what a status line or a streamed delta looks like.

The contract is deliberately small:

    for event in run_turn(...):
        match event.kind:
            case "status": ...        # a short line naming what is happening
            case "stream": ...        # event.deltas is an iterator of text pieces
            case "reset":  ...        # discard what was streamed; a tool round follows
            case "answer": ...        # event.data has the final text and its sources

`stream` hands over an *iterator* rather than a string because that is what a
typewriter effect needs, and because Streamlit's `st.write_stream` consumes one.
Callers that do not want to stream can pass the iterator to `"".join`. Either way
the iterator must be drained before asking for the next event; `run_turn` drains
whatever is left behind rather than losing text if a caller forgets.

Failures are raised, not yielded: `run_turn` lets `llm.AssistantError` out so the
caller can decide between retrying, failing over and giving up. `run_conversation`
is the batteries-included wrapper that makes that decision the way the Streamlit
app always has.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import config, feedback, links, llm
from .corpus import Corpus
from .search import Index
from .tools import READ_DOC, SEARCH_DOCS, TOOL_SCHEMAS, ToolRunner, gather_context

logger = logging.getLogger(__name__)

STATUS = "status"
STREAM = "stream"
RESET = "reset"
NOTICE = "notice"
ANSWER = "answer"

# Shown while the first token is still in flight, before the model has said whether
# it wants to search or answer.
THINKING = "Thinking"

# The model asked for tool round after tool round and never settled. Better than an
# empty bubble, and it names the one action that helps.
UNFINISHED = (
    "I wasn't able to finish looking that up. Please try rephrasing your question."
)


@dataclass(frozen=True)
class Event:
    kind: str
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def deltas(self) -> Iterator[str]:
        """The text iterator carried by a `stream` event."""
        return self.data["deltas"]


def describe(calls: list[dict], corpus: Corpus) -> str:
    """Say what is actually happening instead of a generic shimmer."""
    for call in calls:
        if call["name"] == SEARCH_DOCS:
            query = (call["input"].get("query") or "").strip()
            return f"Searching the docs for “{query}”" if query else "Searching the docs"
    for call in calls:
        if call["name"] == READ_DOC:
            path = (call["input"].get("path") or "").strip()
            chunk = corpus.chunk(path)
            label = chunk.label if chunk else path.split("/")[-1]
            return f"Reading {label}" if label else "Reading documentation"
    return "Working"


def _grounded(
    messages: list[dict], index: Index, question: str, runner: ToolRunner
) -> list[dict]:
    """Retrieve up front, for models that cannot call tools."""
    context, chunks = gather_context(index, question)
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
                "do not end with a Sources list — one is printed for you. If they "
                "do not cover the question, say so.\n\n" + context
            ),
        },
        *messages[1:],
    ]


def _sources(runner: ToolRunner) -> list[dict]:
    return [
        {
            "id": chunk.id,
            "label": chunk.label,
            "url": chunk.url,
            "source": chunk.source,
        }
        for chunk in runner.sources
    ]


class _Drainable:
    """A one-shot text iterator that remembers what it produced.

    `run_turn` needs the round's full text whether or not the caller bothered to
    consume the iterator, and needs to know it is exhausted before moving on. A
    caller that ignores a `stream` event entirely would otherwise skip a tool
    round's worth of the model's reasoning and leave the loop reading a half-read
    HTTP response.
    """

    def __init__(self, source: Iterator[str]) -> None:
        self._source = source
        self.text = ""
        self.done = False

    def __iter__(self) -> Iterator[str]:
        for piece in self._source:
            self.text += piece
            yield piece
        self.done = True

    def drain(self) -> None:
        if not self.done:
            for _ in self:
                pass


def run_turn(
    *,
    index: Index,
    messages: list[dict],
    model,
    provider,
    question: str = "",
    tools: bool = True,
    max_rounds: int | None = None,
) -> Iterator[Event]:
    """One answer, on one model. Raises `llm.AssistantError` rather than yielding it.

    `messages` is the fully built upstream history (see `history.build`) and is not
    mutated — the tool rounds append to a local copy.
    """
    rounds = config.MAX_TOOL_ROUNDS if max_rounds is None else max_rounds
    corpus = index.corpus
    runner = ToolRunner(index)
    messages = list(messages)
    final_text = ""

    yield Event(STATUS, THINKING)

    use_tools = tools
    if use_tools:
        try:
            turn = llm.start(provider, model.id, messages, TOOL_SCHEMAS)
        except llm.AssistantError as exc:
            if not llm.rejects_tools(exc.original or exc):
                raise
            # The model does not do tool calls; retrieve up front instead.
            logger.info("%s rejected tools; using single-pass retrieval", model.id)
            use_tools = False
    if not use_tools:
        messages = _grounded(messages, index, question, runner)
        turn = llm.start(provider, model.id, messages, None)

    for round_number in range(rounds + 1):
        streamed = _Drainable(turn.deltas())
        yield Event(STREAM, data={"deltas": iter(streamed)})
        streamed.drain()
        if streamed.text:
            final_text = streamed.text

        if not turn.tool_calls or not use_tools:
            break
        if round_number == rounds:
            logger.warning("Tool-round limit reached without a final answer")
            final_text = final_text or UNFINISHED
            break

        yield Event(RESET)
        yield Event(STATUS, describe(turn.tool_calls, corpus))
        messages.append(turn.as_message())
        for call in turn.tool_calls:
            messages.append(
                llm.tool_result_message(call, runner.run(call["name"], call["input"]))
            )
        turn = llm.start(provider, model.id, messages, TOOL_SCHEMAS)

    sources = _sources(runner)
    if runner.queries and not sources:
        feedback.record_miss(runner.queries, question)

    yield Event(
        ANSWER,
        data={
            # Stored stripped, not merely rendered stripped: this text is also what
            # goes back upstream next turn, and a footer in the history is a worked
            # example teaching the model to write another one.
            "text": links.strip_source_footer(final_text),
            "sources": sources,
            "model": model.key,
        },
    )


# Why a model refused, in words a user can act on.
REASONS = {"quota": "out of credit", "auth": "its key was rejected"}


def run_conversation(
    *,
    index: Index,
    messages: list[dict],
    models: Sequence,
    provider_for,
    question: str = "",
    max_rounds: int | None = None,
) -> Iterator[Event]:
    """`run_turn` with the failover the Streamlit app has always done by rerunning.

    Tries `models` in order. Only "quota" and "auth" move to the next one — those
    are the two failures that a different provider actually fixes, and waiting does
    not. Anything else is raised, because retrying it on another model would hide a
    real fault behind a second bill.

    A `notice` event is emitted before the retry, and the successful `answer` event
    carries `switched_from` so a caller can say so in the past tense once there is
    an answer to say it about.
    """
    queue = list(models)
    if not queue:
        raise llm.AssistantError("unknown")

    switched_from: tuple[str, str] | None = None

    while queue:
        model = queue.pop(0)
        try:
            for event in run_turn(
                index=index,
                messages=messages,
                model=model,
                provider=provider_for(model.provider),
                question=question,
                tools=model.supports_tools,
                max_rounds=max_rounds,
            ):
                if event.kind == ANSWER and switched_from:
                    yield Event(
                        ANSWER, data={**event.data, "switched_from": switched_from}
                    )
                else:
                    yield event
            return
        except llm.AssistantError as exc:
            alternative = next(
                (item for item in queue if item.provider != model.provider), None
            )
            if exc.kind not in ("quota", "auth") or alternative is None:
                raise
            logger.info(
                "%s unusable (%s); failing over to %s",
                model.key, exc.kind, alternative.key,
            )
            switched_from = (model.label, exc.kind)
            # Present tense: the retry has not happened yet. The past-tense version
            # is written only once an answer actually arrives, off `switched_from`.
            yield Event(
                NOTICE,
                f"{model.label} is unavailable ({REASONS.get(exc.kind, exc.kind)}). "
                f"Retrying with {alternative.label}…",
            )
            # A spent key is spent for every model behind it, not just this one.
            queue = [item for item in queue if item.provider != model.provider]

    raise llm.AssistantError("unknown")
