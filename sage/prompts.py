"""The system prompt.

The text moved to `sage/profiles/rcc.py`, because it is one of the things that
differs between deployments rather than a property of the package. This module
stays as the name callers already knew, re-exporting the active profile's prompt
— keeping a second copy of the RCC text here would be two prompts that drift.
"""

from .profiles import active
from .profiles.rcc import SYSTEM_PROMPT as RCC_SYSTEM_PROMPT

__all__ = ["RCC_SYSTEM_PROMPT", "SYSTEM_PROMPT", "for_profile"]

# The prompt for whichever profile `SAGE_PROFILE` selects, resolved at import.
# `app.py` reads `PROFILE.system_prompt` directly and does not go through this.
SYSTEM_PROMPT = active().system_prompt


def for_profile(profile) -> str:
    return profile.system_prompt
