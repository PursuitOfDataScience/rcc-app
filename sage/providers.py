"""Chat providers behind one interface, so the model is a runtime choice.

Two are supported:

* **Mistral**, via the official SDK.
* **OpenCode Zen**, an OpenAI-compatible endpoint at `https://opencode.ai/zen/v1`
  that fronts a set of free models. Useful when a paid key runs out of credit.

Both normalise onto `Chunk`, so nothing downstream knows which one is in use.
Model lists are discovered from the provider at runtime rather than hardcoded,
because a free tier's lineup changes without notice; a configured list is the
fallback when discovery fails.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import config

logger = logging.getLogger(__name__)

MISTRAL = "mistral"
OPENCODE = "opencode"


@dataclass(frozen=True)
class Model:
    provider: str
    id: str

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.id}"

    @property
    def label(self) -> str:
        """The model's own name, and nothing else.

        There was a provider prefix — "Zen · deepseek-v4-flash-free" — which spent a
        third of the picker's width restating what the rest of the row already said,
        on every line. The id alone identifies the model, and `mistral-` on the front
        of the Mistral ones does the same job the prefix was doing.
        """
        return self.id

    @property
    def supports_tools(self) -> bool:
        """Some free models cannot call tools; those fall back to plain retrieval."""
        lowered = self.id.lower()
        return not any(mark and mark in lowered for mark in config.TOOLLESS_MODELS)


@dataclass
class Usage:
    """Tokens billed for one request, when the provider says.

    Nothing captured this before, so the app could not report its own cost, could
    not tell whether a cache was being hit, and could not tell a slow model from a
    slow prompt. Every figure about spend was therefore an estimate about an
    estimate.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    def __bool__(self) -> bool:
        return bool(self.input_tokens or self.output_tokens)

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cached_input_tokens += other.cached_input_tokens


def parse_usage(raw) -> Usage:
    """Read a usage block from an SDK object or a JSON dict, tolerating absence."""
    if raw is None:
        return Usage()

    def pick(*names):
        for name in names:
            value = (
                raw.get(name)
                if isinstance(raw, dict)
                else getattr(raw, name, None)
            )
            if isinstance(value, (int, float)):
                return int(value)
        return 0

    cached = 0
    details = (
        raw.get("prompt_tokens_details")
        if isinstance(raw, dict)
        else getattr(raw, "prompt_tokens_details", None)
    )
    if details is not None:
        cached = (
            details.get("cached_tokens", 0)
            if isinstance(details, dict)
            else getattr(details, "cached_tokens", 0) or 0
        )
    return Usage(
        input_tokens=pick("prompt_tokens", "input_tokens"),
        output_tokens=pick("completion_tokens", "output_tokens"),
        cached_input_tokens=int(cached or 0) or pick("cached_tokens"),
    )


@dataclass
class Chunk:
    """One normalised streaming event."""

    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    # Set on the final event of a stream, when the provider reports it.
    usage: Usage | None = None


class Provider(Protocol):
    name: str

    def models(self) -> list[Model]: ...

    def stream(
        self, model: str, messages: list[dict], tools: list[dict] | None
    ) -> Iterator[Chunk]: ...


def _tool_fragments(raw) -> list[dict]:
    """Normalise a delta's tool_calls, whether objects (SDK) or dicts (JSON)."""
    fragments = []
    for index, call in enumerate(raw or []):
        if isinstance(call, dict):
            function = call.get("function") or {}
            fragments.append(
                {
                    "index": call.get("index", index) or 0,
                    "id": call.get("id") or "",
                    "name": function.get("name") or "",
                    "arguments": function.get("arguments") or "",
                }
            )
            continue
        function = getattr(call, "function", None)
        fragments.append(
            {
                "index": getattr(call, "index", index) or 0,
                "id": getattr(call, "id", "") or "",
                "name": getattr(function, "name", "") or "",
                "arguments": getattr(function, "arguments", "") or "",
            }
        )
    return fragments


def _flatten(content) -> str:
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part if isinstance(part, str) else (
                part.get("text", "") if isinstance(part, dict)
                else getattr(part, "text", "") or ""
            )
            for part in content
        )
    return str(content)


# --- Mistral ---------------------------------------------------------------


class MistralProvider:
    name = MISTRAL

    def __init__(self, api_key: str) -> None:
        from mistralai import Mistral  # noqa: PLC0415

        self._client = Mistral(api_key=api_key)

    def models(self) -> list[Model]:
        return [Model(MISTRAL, name) for name in config.MISTRAL_MODELS]

    def stream(self, model, messages, tools) -> Iterator[Chunk]:
        stream = self._client.chat.stream(
            model=model,
            messages=messages,
            tools=tools or None,
            tool_choice="auto" if tools else None,
            max_tokens=config.MAX_TOKENS,
            temperature=config.TEMPERATURE,
        )
        # SDK 1.x returns a context manager; some builds a bare iterator.
        manager = stream if hasattr(type(stream), "__enter__") else None
        source = manager.__enter__() if manager else stream
        if source is None:
            source = stream
        try:
            for event in source:
                data = getattr(event, "data", None)
                if not data:
                    continue
                usage = parse_usage(getattr(data, "usage", None))
                if not getattr(data, "choices", None):
                    # Mistral reports usage on a final event that carries no choices;
                    # skipping every choice-less event threw the only cost figure away.
                    if usage:
                        yield Chunk(usage=usage)
                    continue
                delta = data.choices[0].delta
                yield Chunk(
                    text=_flatten(getattr(delta, "content", None)),
                    tool_calls=_tool_fragments(getattr(delta, "tool_calls", None)),
                    usage=usage or None,
                )
        finally:
            if manager is not None:
                try:
                    manager.__exit__(None, None, None)
                except Exception:
                    logger.debug("Ignoring error closing the stream", exc_info=True)


# --- OpenAI-compatible (OpenCode Zen) --------------------------------------


class OpenAICompatProvider:
    """Any OpenAI-compatible `/chat/completions` endpoint."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        name: str = OPENCODE,
        preferred: tuple[str, ...] | None = None,
    ) -> None:
        self.name = name
        self._key = api_key
        self._base = base_url.rstrip("/")
        # Discovery returns the catalogue in arbitrary order. This is the order
        # we would choose, and it decides both the picker's default and what an
        # automatic failover lands on — so it must not be alphabetical.
        self._preferred = (
            config.OPENCODE_MODELS if preferred is None else tuple(preferred)
        )
        self._client = None

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

    def _http(self):
        """One client for the life of the provider, not one per request.

        `stream` opened a fresh `httpx.Client` on every call, so a four-request turn
        paid four TCP and TLS handshakes and a six-round turn paid seven — all of it
        on the pre-answer path, which is the latency the reader actually feels. The
        Mistral adapter next door already holds its client; this one did not.

        Built lazily so importing the module still works without httpx installed,
        which is how the test suite runs.
        """
        if self._client is None:
            import httpx  # noqa: PLC0415

            self._client = httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0))
        return self._client

    def models(self) -> list[Model]:
        """Ask the endpoint what it serves; fall back to the configured list."""
        try:
            import httpx  # noqa: PLC0415

            response = httpx.get(
                f"{self._base}/models", headers=self._headers(), timeout=10
            )
            response.raise_for_status()
            payload = response.json()
            found = [
                str(entry["id"])
                for entry in payload.get("data", [])
                if isinstance(entry, dict) and entry.get("id")
            ]
            # The endpoint serves this deployment's paid lineup alongside the free
            # one, and offering a model there is no balance for is offering a button
            # that returns a 402. Filtered here rather than in the picker so nothing
            # downstream — failover included — can select one.
            if found and config.ZEN_FREE_ONLY:
                free = [name for name in found if config.is_free_zen_model(name)]
                if free:
                    found = free
                else:
                    logger.warning(
                        "%s served %d models and none looked free; offering all of "
                        "them. Check SAGE_ZEN_FREE_MARKS against the current lineup.",
                        self.name, len(found),
                    )
            if found:
                return [Model(self.name, model_id) for model_id in self._order(found)]
            logger.warning("%s returned no models; using the configured list", self.name)
        except Exception as exc:
            logger.warning("Could not list %s models (%s); using configured list",
                           self.name, exc)
        return [Model(self.name, model_id) for model_id in self._preferred]

    def _order(self, found: list[str]) -> list[str]:
        """Preferred models first, in preferred order; then the rest, alphabetically."""
        known = [model_id for model_id in self._preferred if model_id in found]
        return known + sorted(set(found) - set(known))

    def stream(self, model, messages, tools) -> Iterator[Chunk]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": config.MAX_TOKENS,
            "temperature": config.TEMPERATURE,
            # Ask for the token counts. An unknown field is a 400 on some endpoints,
            # so `stream` retries once without it — see `_stream_once`.
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            yield from self._stream_once(payload)
        except _UnsupportedStreamOption:
            logger.info(
                "%s rejected stream_options; retrying without token accounting",
                self.name,
            )
            payload.pop("stream_options", None)
            yield from self._stream_once(payload)

    def _stream_once(self, payload: dict) -> Iterator[Chunk]:
        wants_usage = "stream_options" in payload
        with (
            self._http().stream(
                "POST",
                f"{self._base}/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as response,
        ):
            if response.status_code >= 400:
                # Body must be read before the status can be raised on a stream.
                response.read()
                if wants_usage and response.status_code == 400:
                    raise _UnsupportedStreamOption(response.text[:200])
                response.raise_for_status()
            yield from parse_sse(response.iter_lines())


class _UnsupportedStreamOption(Exception):
    """The endpoint rejected `stream_options`. Retry without it, once."""


def parse_sse(lines: Iterator[str]) -> Iterator[Chunk]:
    """Turn an OpenAI-style `data:` event stream into Chunks."""
    for raw in lines:
        line = raw.strip() if isinstance(raw, str) else raw.decode().strip()
        if not line or not line.startswith("data:"):
            continue
        body = line[len("data:") :].strip()
        if body == "[DONE]":
            return
        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            logger.warning("Skipping unparseable stream event: %r", body[:200])
            continue
        usage = parse_usage(event.get("usage"))
        choices = event.get("choices") or []
        if not choices:
            # With `stream_options.include_usage` the token counts arrive on a final
            # event with an empty `choices` list. Returning early here discarded it.
            if usage:
                yield Chunk(usage=usage)
            continue
        delta = choices[0].get("delta") or {}
        yield Chunk(
            text=_flatten(delta.get("content")),
            tool_calls=_tool_fragments(delta.get("tool_calls")),
            usage=usage or None,
        )


# --- registry --------------------------------------------------------------


def build(name: str, api_key: str) -> Provider:
    if name == MISTRAL:
        return MistralProvider(api_key)
    if name == OPENCODE:
        return OpenAICompatProvider(api_key, config.OPENCODE_BASE_URL)
    raise ValueError(f"Unknown provider: {name}")


def parse_key(value: str) -> Model | None:
    """`'opencode:deepseek-v4-flash'` -> Model, or None if malformed."""
    if not value or ":" not in value:
        return None
    provider, model_id = value.split(":", 1)
    if provider not in (MISTRAL, OPENCODE) or not model_id:
        return None
    return Model(provider, model_id)
