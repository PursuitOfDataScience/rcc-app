"""Mistral client, streaming, and error classification.

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

logger = logging.getLogger(__name__)

_RETRYABLE = {"rate_limit", "network", "unavailable"}

_MESSAGES = {
    "auth": "The assistant is not configured correctly (API key rejected). "
            "Please tell RCC staff.",
    "rate_limit": "The assistant is busy right now. Please wait a moment and retry.",
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
    text = f"{type(exc).__name__} {exc}".lower()

    if status in (401, 403) or "unauthorized" in text or "invalid api key" in text:
        kind = "auth"
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


def create_client(api_key: str):
    """Build a Mistral SDK v1 client. Raises AssistantError with a usable message."""
    if not api_key:
        raise AssistantError("auth")
    try:
        from mistralai import Mistral  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - environment problem
        logger.error("mistralai SDK missing or too old: %s", exc)
        raise AssistantError("unknown", exc) from exc
    try:
        return Mistral(api_key=api_key)
    except Exception as exc:  # pragma: no cover
        raise classify(exc) from exc


def _open(stream):
    """Return (iterable, context_manager_to_close).

    `mistralai` 1.x returns a context manager from `chat.stream()` — the documented
    usage is `with client.chat.stream(...) as events:` — while some builds return a
    plain iterator. Entering it when possible makes both shapes work.
    """
    if hasattr(type(stream), "__enter__"):
        opened = stream.__enter__()
        return (stream if opened is None else opened), stream
    return stream, None


@dataclass
class Turn:
    """One model turn. Iterate `deltas()` to stream, or `consume()` to block."""

    stream: Any
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finished: bool = False

    def deltas(self) -> Iterator[str]:
        pending: dict[int, dict] = {}
        source, manager = _open(self.stream)
        try:
            for event in source:
                data = getattr(event, "data", None)
                if not data or not getattr(data, "choices", None):
                    continue
                delta = data.choices[0].delta

                content = getattr(delta, "content", None)
                if content:
                    # Some SDK versions deliver content as a list of parts.
                    if isinstance(content, list):
                        content = "".join(
                            part if isinstance(part, str) else getattr(part, "text", "")
                            for part in content
                        )
                    if content:
                        self.text += content
                        yield content

                for call in getattr(delta, "tool_calls", None) or []:
                    index = getattr(call, "index", 0) or 0
                    slot = pending.setdefault(index, {"id": "", "name": "", "args": ""})
                    if getattr(call, "id", None):
                        slot["id"] = call.id
                    function = getattr(call, "function", None)
                    if function is not None:
                        if getattr(function, "name", None):
                            slot["name"] = function.name
                        if getattr(function, "arguments", None):
                            arguments = function.arguments
                            slot["args"] += (
                                arguments
                                if isinstance(arguments, str)
                                else json.dumps(arguments)
                            )
        except Exception as exc:
            raise classify(exc) from exc
        finally:
            if manager is not None:
                try:
                    manager.__exit__(None, None, None)
                except Exception:  # closing must never mask the real error
                    logger.debug("Ignoring error while closing the stream", exc_info=True)

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


def start(client, messages: list[dict], tools: list[dict] | None = None) -> Turn:
    """Open a streaming turn, retrying transient failures before any output."""
    attempts = max(config.REQUEST_RETRIES, 0) + 1
    last: AssistantError | None = None

    for attempt in range(attempts):
        try:
            stream = client.chat.stream(
                model=config.MODEL,
                messages=messages,
                tools=tools or None,
                tool_choice="auto" if tools else None,
                max_tokens=config.MAX_TOKENS,
                temperature=config.TEMPERATURE,
            )
            return Turn(stream=stream)
        except Exception as exc:
            error = classify(exc)
            last = error
            if not error.retryable or attempt == attempts - 1:
                raise error from exc
            delay = 2**attempt
            logger.warning(
                "Transient %s from Mistral, retrying in %ss", error.kind, delay
            )
            time.sleep(delay)

    raise last or AssistantError("unknown")


def tool_result_message(call: dict, content: str) -> dict:
    return {
        "role": "tool",
        "tool_call_id": call["id"],
        "name": call["name"],
        "content": content,
    }
