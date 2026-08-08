"""Transcripts out: markdown, and a pre-drafted help desk message.

Reloading the page destroys the conversation — Streamlit binds session state to the
websocket and there is no server-side flag that changes it. Until something persists
threads, an export button is what turns data loss into an inconvenience.

The one rule that matters here: answer text must go through `links.fix_links` before
it leaves. Raw answers contain corpus paths like `docs/slurm/sbatch.md#gpu-jobs`,
which only become real URLs at render time, so an export that skips that step ships
a document full of dead links — and it will look fine to whoever wrote it.
"""

from __future__ import annotations

from urllib.parse import quote

from . import config, links, scrub


def _provenance(model_labels: list[str], stamped_at: str) -> list[str]:
    """Front matter, in the shape Perplexity ships, so it drops into a notebook.

    The highest-value field is the docs snapshot: it turns "some AI said the quota is
    100 GB" into "the User Guide at commit f5676ad, synced 2026-07-06, said the quota
    is 100 GB", which a staff member can check in thirty seconds. `config.snapshot()`
    has always parsed it and nothing has ever shown it.
    """
    snapshot = config.snapshot()
    lines = [
        "---",
        'tool: "Sage — UChicago RCC documentation assistant"',
        f'exported_at: "{stamped_at}"',
    ]
    if model_labels:
        rendered = ", ".join(f'"{label}"' for label in dict.fromkeys(model_labels))
        lines.append(f"models_used: [{rendered}]")
    if snapshot.get("user_guide_commit"):
        lines.append(f'docs_commit: "{snapshot["user_guide_commit"]}"')
    if snapshot.get("refreshed_at"):
        lines.append(f'docs_refreshed_at: "{snapshot["refreshed_at"]}"')
    lines += [
        f'docs_base_url: "{config.DOCS_BASE_URL}"',
        f'help_desk: "{config.HELP_DESK_EMAIL}"',
        'note: "Generated from RCC documentation. Verify commands before running'
        ' them."',
        "---",
        "",
    ]
    return lines


def as_markdown(messages: list[dict], corpus, stamped_at: str) -> str:
    """The whole conversation, with citations resolved and sources listed."""
    models = [
        message.get("model", "")
        for message in messages
        if message.get("role") == "assistant" and message.get("model")
    ]
    lines = _provenance(models, stamped_at)

    question_number = 0
    for message in messages:
        text = (message.get("text") or "").strip()
        if message.get("role") == "user":
            question_number += 1
            lines.append(f"## Q{question_number}")
            lines.append("")
            lines.append(scrub.scrub(text) if text else "*(no text)*")
            attachments = message.get("attachments") or []
            if attachments:
                named = ", ".join(f"`{item.filename}`" for item in attachments)
                lines += ["", f"Attachments: {named}"]
            lines.append("")
        elif text:
            label = message.get("model") or "assistant"
            lines.append(f"## A{question_number} — {label}")
            lines.append("")
            lines.append(links.fix_links(text, corpus))
            lines.append("")
            sources = message.get("sources") or []
            if sources:
                lines.append("**Sources**")
                lines.append("")
                for source in sources:
                    lines.append(
                        f"- [{source.get('label', '')}]({source.get('url', '')})"
                        f" · {source.get('source', '')}"
                    )
                lines.append("")
            if message.get("trimmed"):
                lines += [
                    "> Note: earlier turns of this conversation were not sent to the"
                    " model when this answer was produced.",
                    "",
                ]
    return "\n".join(lines).rstrip() + "\n"


def filename(stamped_at: str) -> str:
    stamp = stamped_at.replace(":", "").replace("-", "").replace(" ", "-")
    return f"sage-transcript-{stamp}.md"


def help_desk_mailto(question: str, searches: list[dict], sources: list[dict]) -> str:
    """A `mailto:` with the question, what was searched, and what was found.

    47% of users handed from a bot to a human report being annoyed at having to
    repeat themselves. Sage knows the question verbatim, the queries it ran and the
    pages it read, so it can draft a better first message than the user would — and
    saying it was drafted by the assistant tells the human on the other end what has
    already been checked.

    Kept deliberately short: `mailto` bodies are unreliable much past ~2 KB, so this
    is a summary plus an instruction to attach the exported transcript rather than an
    attempt to inline it.
    """
    subject = scrub.scrub(question).strip()[:80] or "RCC question"
    tried = ", ".join(
        f'"{scrub.scrub(str(item.get("query", "")))[:60]}"' for item in searches[:4]
    )
    found = "\n".join(
        f"  - {source.get('label', '')} ({source.get('url', '')})"
        for source in sources[:5]
    )
    body = f"""My question: {scrub.scrub(question)[:600]}

I checked the RCC User Guide with the Sage documentation assistant first.
"""
    if tried:
        body += f"Searches tried: {tried}\n"
    if found:
        body += f"Sections it found:\n{found}\n"
    else:
        body += "It found no matching documentation section.\n"
    body += """
What I have tried so far:
  [ ]

CNetID:
Cluster:
"""
    return (
        f"mailto:{config.HELP_DESK_EMAIL}"
        f"?subject={quote(subject, safe='')}&body={quote(body, safe='')}"
    )


def docs_issue_url(question: str, searches: list[dict]) -> str:
    """A pre-filled issue against the upstream user-guide repo.

    The cheapest closed loop available: no backend, no auth, no storage — a URL with
    a title and a body. It converts a user's frustration into a triaged
    documentation ticket carrying the retrieval trace, and it makes the feedback
    visibly consequential, which is what stops rating rates collapsing.
    """
    if not config.DOCS_ISSUE_URL:
        return ""
    title = f"Docs gap: {scrub.scrub(question).strip()[:70]}"
    tried = ", ".join(
        f'`{scrub.scrub(str(item.get("query", "")))[:60]}`' for item in searches[:5]
    )
    body = (
        "Asked via the Sage documentation assistant and not answerable from the "
        "current User Guide.\n\n"
        f"**Question:** {scrub.scrub(question)[:600]}\n\n"
    )
    if tried:
        body += f"**Searches tried:** {tried}\n\n"
    snapshot = config.snapshot()
    if snapshot.get("user_guide_commit"):
        body += f"**Docs commit checked:** {snapshot['user_guide_commit']}\n"
    return (
        f"{config.DOCS_ISSUE_URL}?title={quote(title, safe='')}"
        f"&body={quote(body, safe='')}"
    )
