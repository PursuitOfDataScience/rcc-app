"""Rewrite the internal paths a model emits into real, clickable URLs.

The previous version sent *every* `web/` citation to the user-guide root on the
stated grounds that "website pages have no stable per-page docs URL". They do —
each scraped file records it on line 1 — and they span five different hosts, so a
Skyway or Beagle3 answer was being cited to the Midway user guide.
"""

from __future__ import annotations

import re

from . import config
from .corpus import Corpus, docs_url

_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_ATTR_LIST = re.compile(r"\{:[^}]*\}")
_EXTERNAL = ("http://", "https://", "mailto:", "tel:", "#")


def resolve(target: str, corpus: Corpus) -> str | None:
    """Best URL for an internal doc reference, or None if it cannot be resolved."""
    target = target.strip()
    if not target:
        return None

    chunk = corpus.chunk(target)
    if chunk is not None:
        return chunk.url

    base, _, anchor = target.partition("#")
    base = base.strip().lstrip("./")

    document = corpus.document(base)
    if document is None:
        for source in ("docs", "web"):
            document = corpus.document(f"{source}/{base}")
            if document is not None:
                break

    if document is None:
        # A bare or relative filename: match on path suffix.
        candidates = [
            item
            for item in corpus.documents.values()
            if item.path == base or item.path.endswith(f"/{base}")
        ]
        document = candidates[0] if len(candidates) == 1 else None

    if document is None:
        return None
    if document.source == "web":
        return document.url
    return docs_url(document.path, anchor)


def fix_links(text: str, corpus: Corpus) -> str:
    """Point internal links at published URLs; unlink what cannot be resolved."""
    text = _ATTR_LIST.sub("", text)

    def replace(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        if target.startswith(_EXTERNAL):
            # A bare in-page anchor has nowhere to go in a chat transcript.
            return label if target.startswith("#") else match.group(0)
        url = resolve(target, corpus)
        return f"[{label}]({url})" if url else f"[{label}]({config.DOCS_BASE_URL})"

    return _MARKDOWN_LINK.sub(replace, text)
