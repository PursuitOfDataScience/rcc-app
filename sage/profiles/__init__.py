"""The profile registry.

`SAGE_PROFILE` picks one. It defaults to `rcc`, so a deployment that sets nothing
behaves exactly as this app always has.
"""

from __future__ import annotations

import logging
import os

from ..profile import Profile
from . import rcc, site

logger = logging.getLogger(__name__)

PROFILES: dict[str, Profile] = {
    rcc.PROFILE.key: rcc.PROFILE,
    site.PROFILE.key: site.PROFILE,
}

DEFAULT = rcc.PROFILE.key


def get(key: str) -> Profile:
    """Look up a profile, falling back to the default with a warning.

    Loudly rather than silently: a typo in `SAGE_PROFILE` would otherwise deploy
    the wrong assistant against the right corpus and look like a prompt bug.
    """
    if key in PROFILES:
        return PROFILES[key]
    logger.warning(
        "Unknown SAGE_PROFILE %r; using %r. Known profiles: %s",
        key, DEFAULT, ", ".join(sorted(PROFILES)),
    )
    return PROFILES[DEFAULT]


def active() -> Profile:
    return get(os.getenv("SAGE_PROFILE", DEFAULT).strip().lower() or DEFAULT)
