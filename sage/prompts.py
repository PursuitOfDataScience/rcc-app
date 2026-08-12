"""Rendering a profile's prompt text.

Two prompts, and both are the deployment's to write. The system prompt comes from
the profile — `profiles/rcc.prompt.md` for this one — and the grounded instruction is
what a model that cannot call tools is given instead of the search/read loop.

Substitution is a fixed list of names rather than `str.format`, because a prompt is
prose a non-programmer edits: a stray `{` in it should read as a brace, not raise
`KeyError` on the first turn after someone mentioned `${SLURM_JOB_ID}`.
"""

from __future__ import annotations

from .profile import Identity, Profile, active

# What a `{placeholder}` in a prompt may stand for. Anything else is left alone.
_FIELDS = ("name", "subject", "topic", "documentation", "contact", "contact_label")


def render(template: str, identity: Identity) -> str:
    text = template
    for field in _FIELDS:
        token = "{" + field + "}"
        if token in text:
            text = text.replace(token, str(getattr(identity, field, "")))
    # A profile with no contact address would otherwise leave "point the user at the
    # maintainers ()" in the prompt.
    if not identity.has_contact:
        text = text.replace(" ()", "")
    return text


def system_prompt(profile: Profile | None = None) -> str:
    """The profile's system prompt, or the built-in one if it has none."""
    from .profile import DEFAULT_PROMPT  # noqa: PLC0415  (a default, not a dependency)

    chosen = profile or active()
    template = chosen.prompt or DEFAULT_PROMPT
    contact = chosen.identity.contact
    text = render(template, chosen.identity)
    if "{contact_sentence}" in text:
        text = text.replace(
            "{contact_sentence}",
            f" and point the user at {chosen.identity.contact_label} ({contact})"
            if contact
            else "",
        )
    return text


def grounded_instruction(context: str, identity: Identity | None = None) -> str:
    """What a model that cannot call tools is told, with the sections inlined.

    The rules it repeats from the system prompt are the two that matter most when
    there is no second round to correct them: cite the exact path, and do not print a
    Sources list the app is already printing three lines below.
    """
    who = identity or active().identity
    return (
        f"Answer only from these {who.qualifier}documentation sections. Cite them "
        "inline as [Title](path) using the exact path in each header, and "
        "do not restate them at the end — no Sources list and no 'Cited "
        "from' sentence, because one is printed for you. If they do not "
        "cover the question, say so.\n\n" + context
    )
