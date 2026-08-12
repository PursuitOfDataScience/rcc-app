"""What one render of the page has to hand: the assistant, and the chosen model.

Passed to every draw function rather than read from module globals. `app.py` used to
hold `CORPUS`, `INDEX`, `MODELS` and `MODEL` at module scope and forty functions
closed over them, which is why none of those functions could be moved out of it: each
one silently depended on the whole file having run first.
"""

from __future__ import annotations

from collections.abc import Sequence
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

    #: Failures whose remedy is a different model on the SAME provider, because the
    #: key is fine and only this model is unavailable.
    PER_MODEL = frozenset({"allowance"})

    def alternative(self, kind: str = "", skip: Sequence[str] = ()) -> Model | None:
        """The best other model to try, given what went wrong.

        Which way to jump depends on the failure, and getting this wrong walks the
        reader from one dead end into another:

        * A spent **key** — 402, or a rejected key — kills every model behind it, so
          the way out is a different provider.
        * A spent **free allowance** is metered per model. `deepseek-v4-flash-free`
          answered `FreeUsageLimitError` while `nemotron-3-ultra-free` on the same key
          answered in under a second, and the other provider's key was itself out of
          credit — so preferring a different provider offered a second dead end while
          a working model sat one row down the picker.

        Either preference falls back to the other rather than to nothing: with one
        provider configured there was no switch button at all, on a screen whose own
        error text says to switch. `models` is in preference order, so each branch
        takes the best candidate rather than an alphabetical accident.

        `skip` is what the turn has already tried, so a second hop does not land back
        on a model that has just refused.
        """
        spent = set(skip) | {self.model.key}
        same = [
            option for option in self.models
            if option.provider == self.model.provider and option.key not in spent
        ]
        elsewhere = [
            option for option in self.models
            if option.provider != self.model.provider and option.key not in spent
        ]
        order = (same, elsewhere) if kind in self.PER_MODEL else (elsewhere, same)
        return next((group[0] for group in order if group), None)

    @property
    def fallback(self) -> Model | None:
        """The alternative to offer when the reason is not known — the error card."""
        return self.alternative()
