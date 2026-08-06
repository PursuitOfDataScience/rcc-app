"""Build the upstream message list from session history.

Fixes two cost bugs. Attachment text used to be re-sent on *every* subsequent
turn — ask three follow-ups about a PDF and it shipped four times — and there was
no bound at all on total history size.
"""

from __future__ import annotations

from . import config
from .files import Attachment, as_context


def user_content(text: str, attachment: Attachment | None, *, full: bool) -> str:
    """Render one user turn, with the attachment either inlined or stubbed."""
    if attachment is None:
        return text
    if full:
        return f"{as_context(attachment)}\n\nThe user asks: {text}"
    return (
        f"[earlier in this conversation the user attached {attachment.filename}; "
        f"its text is omitted here to save space]\n\n{text}"
    )


def build(messages: list[dict], system: str) -> list[dict]:
    """Turn session messages into Mistral chat messages within the char budget."""
    attachment_positions = [
        index
        for index, message in enumerate(messages)
        if message.get("role") == "user" and message.get("attachment") is not None
    ]
    inline = set(attachment_positions[-config.ATTACHMENT_FULL_TEXT_TURNS :])

    built: list[dict] = []
    for index, message in enumerate(messages):
        role = message.get("role")
        text = (message.get("text") or "").strip()
        if role == "user":
            content = user_content(
                text, message.get("attachment"), full=index in inline
            )
            if content:
                built.append({"role": "user", "content": content})
        elif role == "assistant" and text:
            built.append({"role": "assistant", "content": text})

    return [{"role": "system", "content": system}, *_trim(built)]


def _trim(built: list[dict]) -> list[dict]:
    """Drop the oldest turns until the budget is met. The last turn always stays."""
    def size(items: list[dict]) -> int:
        return sum(len(item["content"]) for item in items)

    while len(built) > 1 and size(built) > config.HISTORY_CHAR_BUDGET:
        built.pop(0)

    if built and size(built) > config.HISTORY_CHAR_BUDGET:
        keep = config.HISTORY_CHAR_BUDGET
        built[0] = {**built[0], "content": built[0]["content"][:keep]}
    return built
