"""Turn assembly, streaming, and error classification.

There used to be two near-identical stream readers — one that yielded deltas for
the UI and one that collected silently — and the tool loop used the silent one for
its final round. The result was that the *most common* interaction (search → read →
answer) never streamed: users watched a shimmer, then the whole answer appeared at
once. One reader now serves both, so every answer streams.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from . import config
from .providers import Chunk, Usage

logger = logging.getLogger(__name__)

_RETRYABLE = {"rate_limit", "network", "unavailable"}

_MESSAGES = {
    "auth": "The assistant is not configured correctly (API key rejected). "
            "Please tell RCC staff.",
    "rate_limit": "The assistant is busy right now. Please wait a moment and retry.",
    "quota": "This model is out of credit or its quota is used up. "
             "Switch to another model and try again.",
    "context": "This conversation got too long for the model. "
               "Clear the chat and ask again.",
    "network": "Could not reach the assistant. Check the connection and retry.",
    "unavailable": "The assistant is temporarily unavailable. Please retry shortly.",
    "unknown": "Something went wrong reaching the assistant. Please try again.",
}


class AssistantError(Exception):
    def __init__(self, kind: str, original: BaseException | None = None) -> None:
        self.kind = kind if kind in _MESSAGES else "unknown"
        self.original = original
        super().__init__(_MESSAGES[self.kind])

    @property
    def user_message(self) -> str:
        return _MESSAGES[self.kind]

    @property
    def retryable(self) -> bool:
        return self.kind in _RETRYABLE


def classify(exc: BaseException) -> AssistantError:
    if isinstance(exc, AssistantError):
        return exc

    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status is None:
        # httpx.HTTPStatusError keeps the code on .response
        status = getattr(getattr(exc, "response", None), "status_code", None)
    text = f"{type(exc).__name__} {exc}".lower()

    if status in (401, 403) or "unauthorized" in text or "invalid api key" in text:
        kind = "auth"
    elif status == 402 or any(
        needle in text
        for needle in ("quota", "insufficient", "credit", "billing",
                       "check your subscription", "payment")
    ):
        # Out of credit does not recover by waiting, so it is deliberately not
        # retryable — switching provider is the only useful action.
        kind = "quota"
    elif status == 429 or "rate limit" in text or "too many requests" in text:
        kind = "rate_limit"
    elif (
        ("context" in text and ("length" in text or "token" in text))
        or "too large" in text
        or status == 413
    ):
        kind = "context"
    elif isinstance(status, int) and 500 <= status < 600:
        kind = "unavailable"
    elif any(
        needle in text
        for needle in ("timeout", "timed out", "connection", "network", "dns", "ssl")
    ):
        kind = "network"
    else:
        kind = "unknown"
    return AssistantError(kind, exc)


@dataclass
class Turn:
    """One model turn. Iterate `deltas()` to stream, or `consume()` to block.

    Consumes normalised `Chunk`s, so Mistral and any OpenAI-compatible endpoint
    go through exactly the same assembly and error handling.
    """

    stream: Any
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finished: bool = False
    usage: Usage = field(default_factory=Usage)

    def deltas(self) -> Iterator[str]:
        pending: dict[int, dict] = {}
        try:
            for chunk in self.stream:
                if not isinstance(chunk, Chunk):
                    continue
                if chunk.usage:
                    self.usage.add(chunk.usage)
                if chunk.text:
                    self.text += chunk.text
                    yield chunk.text
                for fragment in chunk.tool_calls:
                    slot = pending.setdefault(
                        fragment["index"], {"id": "", "name": "", "args": ""}
                    )
                    if fragment.get("id"):
                        slot["id"] = fragment["id"]
                    if fragment.get("name"):
                        slot["name"] = fragment["name"]
                    if fragment.get("arguments"):
                        slot["args"] += fragment["arguments"]
        except Exception as exc:
            raise classify(exc) from exc

        self.tool_calls = [
            {"id": slot["id"], "name": slot["name"], "input": _parse(slot["args"])}
            for slot in pending.values()
            if slot["name"]
        ]
        self.finished = True

    def consume(self) -> Turn:
        for _ in self.deltas():
            pass
        return self

    def as_message(self) -> dict:
        """The assistant message to append before tool results."""
        return {
            "role": "assistant",
            "content": self.text,
            "tool_calls": [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["input"]),
                    },
                }
                for call in self.tool_calls
            ],
        }


def _parse(arguments: str) -> dict:
    if not arguments:
        return {}
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        logger.warning("Unparseable tool arguments: %r", arguments[:200])
        return {}
    return parsed if isinstance(parsed, dict) else {}


def start(provider, model: str, messages: list[dict],
          tools: list[dict] | None = None) -> Turn:
    """Open a streaming turn, retrying transient failures before any output."""
    attempts = max(config.REQUEST_RETRIES, 0) + 1
    last: AssistantError | None = None

    for attempt in range(attempts):
        try:
            stream = provider.stream(model, messages, tools)
            # `stream` is a generator, so the request has not been made yet. Pull
            # the first chunk here so connection and auth failures surface where
            # they can still be retried, rather than mid-render.
            first = next(stream, None)
            return Turn(stream=_replay(first, stream))
        except Exception as exc:
            error = classify(exc)
            last = error
            if not error.retryable or attempt == attempts - 1:
                raise error from exc
            delay = 2**attempt
            logger.warning(
                "Transient %s from %s, retrying in %ss", error.kind, provider.name, delay
            )
            time.sleep(delay)

    raise last or AssistantError("unknown")


def _replay(first, rest) -> Iterator[Chunk]:
    if first is not None:
        yield first
    yield from rest


def rejects_tools(exc: BaseException) -> bool:
    """Whether a failure looks like the model simply not supporting tool calls."""
    text = f"{type(exc).__name__} {exc}".lower()
    return ("tool" in text or "function" in text) and any(
        mark in text for mark in
        ("not support", "unsupported", "invalid", "unknown parameter", "unrecognized")
    )


def tool_result_message(call: dict, content: str) -> dict:
    return {
        "role": "tool",
        "tool_call_id": call["id"],
        "name": call["name"],
        "content": content,
    }
