"""What a provider is, and the shapes every one of them normalises onto.

`Model` and `Chunk` are the whole contract with the rest of the app: a turn is a
stream of `Chunk`s and a picker row is a `Model`, and nothing downstream — the tool
loop, the failover, the history builder — knows which endpoint produced either.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol

from .. import config

# One bound for every adapter, so a hung stream cannot hold a script run open on
# whichever provider the reader happened to pick. The HTTP adapter spells the same
# 120s as an `httpx.Timeout`.
STREAM_TIMEOUT_MS = 120_000

# The id segment marking a no-cost tier. Matched on `Model.label` only; the id itself
# is never rewritten, so what is sent upstream stays exactly what the provider serves.
_TIER_MARK = "free"


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

        There was a provider prefix — "Zen · deepseek-v4-flash" — which spent a third
        of the picker's width restating what the rest of the row already said, on
        every line. The id alone identifies the model, and `mistral-` on the front of
        the Mistral ones does the same job the prefix was doing.

        The tier marker in an id is dropped for the same reason: it is billing
        plumbing, not part of the model's name. It still belongs in `key`, which is
        what goes upstream, and in the discovery filter that reads it — but a picker
        row is where a reader is choosing between models, and the marker says nothing
        about the choice. Removed by segment, so only a whole `-free-` word goes.
        """
        kept = [part for part in self.id.split("-") if part.lower() != _TIER_MARK]
        return "-".join(kept) or self.id

    @property
    def supports_tools(self) -> bool:
        """Some free models cannot call tools; those fall back to plain retrieval."""
        lowered = self.id.lower()
        return not any(mark and mark in lowered for mark in config.TOOLLESS_MODELS)


@dataclass
class Chunk:
    """One normalised streaming event."""

    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)


class Provider(Protocol):
    name: str

    def models(self) -> list[Model]: ...

    def stream(
        self, model: str, messages: list[dict], tools: list[dict] | None
    ) -> Iterator[Chunk]: ...


def family_of(model_id: str) -> str:
    """The maker's name at the front of a model id — `nemotron-3.5-lightning-free`
    and `nemotron-3-ultra-free` are both `nemotron`.

    The first segment, and nothing cleverer. Every id either provider serves puts the
    family first and the version straight after it (`ling-3.0-tiny`, `deepseek-v4`,
    `mistral-small-latest`, `gpt-5.2-codex`), so the split is where the version
    begins. A rule that tried to parse the version out as well would have to know
    that `laguna-s-2.1` has a letter in the middle and `big-pickle` has no version at
    all, and it would be wrong about the next naming scheme a free tier invents. This
    one degrades into "a family of one", which is what an unrecognised name should be.
    """
    return (model_id or "").split("-", 1)[0].lower()


def tool_fragments(raw) -> list[dict]:
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


def flatten(content) -> str:
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
