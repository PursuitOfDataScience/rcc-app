"""Reading settings out of the environment, and nothing else.

Split out of `config.py` so that `profile.py` can use the same rules without the two
importing each other. There is one place a `SAGE_…=` with an empty value means "clear
this list", one place a negative `MAX_TOKENS` is treated as a typo rather than handed
to a provider, and one place a boolean's spelling is decided — which is what keeps a
deployment's settings behaving the same way whichever module happens to read them.
"""

from __future__ import annotations

import os

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "")


def text(name: str, default: str = "") -> str:
    raw = os.getenv(name)
    return default if raw is None else raw


def integer(name: str, default: int, minimum: int | None = None) -> int:
    """An integer setting, falling back to `default` on anything unusable.

    `minimum` is for the settings where a non-positive value is not a choice but a
    typo: `SAGE_MAX_TOKENS=-1` used to be handed straight to the provider, which
    fails the request with a message about the model rather than about the setting.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return default if minimum is not None and value < minimum else value


def number(name: str, default: float, minimum: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return default if minimum is not None and value < minimum else value


def items(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Comma-separated env override. `NAME=` (empty) explicitly clears the list."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def flag(name: str, default: bool) -> bool:
    """A boolean setting. Anything unrecognised keeps the default.

    Both spellings are listed rather than one being "not the other", so that a
    variable set to a word this does not know keeps the shipped behaviour instead of
    silently reading as off. `NAME=` (empty) is off, which is what the two hand-rolled
    flags this replaces both did.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    lowered = raw.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    return default
