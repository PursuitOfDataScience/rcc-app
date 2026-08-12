"""Any endpoint that speaks OpenAI's `/chat/completions`, which is most of them.

Registered under the kind `openai`, and it is the reason adding a provider is usually
a TOML entry rather than code: OpenCode Zen, Together, Groq, Fireworks, a vLLM server
on a login node and Ollama on a laptop all answer this shape. What varies between
them is a base URL, an environment variable holding a key, and a fallback list of
model ids — which is exactly what a profile entry carries.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from .. import config
from ..profile import ProviderEntry
from .base import Chunk, Model, family_of, flatten, tool_fragments

logger = logging.getLogger(__name__)


class OpenAICompatProvider:
    def __init__(self, entry: ProviderEntry, api_key: str) -> None:
        self.name = entry.name
        self.entry = entry
        self._key = api_key
        self._base = entry.base_url.rstrip("/")
        # Discovery returns the catalogue in arbitrary order. The profile's list is
        # the order we would choose, and it decides both the picker's default and what
        # an automatic failover lands on — so it must not be alphabetical.
        self._preferred = tuple(entry.models)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

    def _is_free(self, model: str) -> bool:
        lowered = (model or "").lower()
        return any(
            mark and mark.lower() in lowered for mark in self.entry.free_marks
        )

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
            # An endpoint may serve this deployment's paid lineup alongside the free
            # one, and offering a model there is no balance for is offering a button
            # that returns a 402. Filtered here rather than in the picker so nothing
            # downstream — failover included — can select one.
            if found and self.entry.free_only and self.entry.free_marks:
                free = [name for name in found if self._is_free(name)]
                if free:
                    found = free
                else:
                    logger.warning(
                        "%s served %d models and none looked free; offering all of "
                        "them. Check free_marks against the current lineup.",
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
        """Preferred first, then the rest alphabetically — and families kept together.

        The ranking on its own scattered a family down the list. `nemotron-3-ultra`
        sat fifth because the preference list puts it there and
        `nemotron-3.5-lightning` sat last because nothing named it, so the picker
        offered two Nemotrons eight rows apart, with three unrelated models between
        them. A reader choosing a model is comparing versions of the same thing —
        which Nemotron, which Ling — and a list that splits them up makes the one
        comparison the picker exists for the hardest thing to do in it.

        Grouping is applied AFTER the ranking rather than instead of it, so the two
        jobs stay separate: the ranking still decides which model a fresh session
        starts on and which one an automatic failover lands on, and this only decides
        where a family's other members are drawn. A family takes the position of its
        best-ranked member, and members keep their ranked order inside it — so the
        first row of the picker is the same model it was before.
        """
        known = [model_id for model_id in self._preferred if model_id in found]
        ranked = known + sorted(set(found) - set(known))
        families: dict[str, list[str]] = {}
        for model_id in ranked:
            families.setdefault(family_of(model_id), []).append(model_id)
        return [model_id for members in families.values() for model_id in members]

    def stream(self, model, messages, tools) -> Iterator[Chunk]:
        import httpx  # noqa: PLC0415

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": config.MAX_TOKENS,
            "temperature": config.TEMPERATURE,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        with (
            httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client,
            client.stream(
                "POST",
                f"{self._base}/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as response,
        ):
            if response.status_code >= 400:
                # Body must be read before the status can be raised on a stream.
                response.read()
                response.raise_for_status()
            yield from parse_sse(response.iter_lines())


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
        # Parsed is not the same as shaped. `data: "[DONE]"` — quoted, which some
        # OpenAI-compatible gateways send — is valid JSON and a string, and every
        # `.get` below assumed a dict: the AttributeError left `Turn.deltas` to
        # classify it as an unknown failure, so a half-streamed answer was thrown
        # away and replaced with "something went wrong" at the very end of it. An
        # event this code does not understand is one to skip, which is what the
        # JSONDecodeError branch above already decided.
        if not isinstance(event, dict):
            continue
        choices = event.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            continue
        delta = choices[0].get("delta")
        if not isinstance(delta, dict):
            delta = {}
        yield Chunk(
            text=flatten(delta.get("content")),
            tool_calls=tool_fragments(delta.get("tool_calls")),
        )
