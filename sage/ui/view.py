"""What one render of the page has to hand: the assistant, and the chosen model.

Passed to every draw function rather than read from module globals. `app.py` used to
hold `CORPUS`, `INDEX`, `MODELS` and `MODEL` at module scope and forty functions
closed over them, which is why none of those functions could be moved out of it: each
one silently depended on the whole file having run first.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..profile import Copy, Identity
from ..providers import Model
from ..runtime import Runtime


@dataclass(frozen=True)
class View:
    runtime: Runtime
    #: Every model the configured providers offer, in preference order.
    models: tuple[Model, ...]
    #: The one this session is asking.
    model: Model

    @property
    def identity(self) -> Identity:
        return self.runtime.identity

    @property
    def copy(self) -> Copy:
        return self.runtime.copy

    @property
    def corpus(self):
        return self.runtime.corpus

    @property
    def examples(self):
        return self.runtime.examples

    @property
    def fallback(self) -> Model | None:
        """First model from a *different* provider — the way round a spent quota.

        `models` is in preference order, so this is the best alternative, not an
        alphabetical accident.
        """
        return next(
            (option for option in self.models if option.provider != self.model.provider),
            None,
        )
