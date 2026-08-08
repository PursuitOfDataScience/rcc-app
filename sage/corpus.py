"""Discover, clean and chunk the documentation corpus.

Chunks are heading-sized rather than file-sized. That is what removes the old
15k-character truncation (which cut 62% of `docs/slurm/sbatch.md`) and what lets
a citation deep-link to the exact section an answer came from.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from . import config, profiles
from .normalize import (
    collapse_blank_lines,
    normalize_markdown,
    parse_post_header,
    parse_scraped,
    plain_heading,
    pretty_title,
    slugify,
)
from .profile import POST, SCRAPED, Profile

logger = logging.getLogger(__name__)

# An explicit anchor on a heading — pandoc's `## Title {#the-id}`. Synced blog
# posts carry the id the rendered page actually uses, rather than letting
# `slugify` guess at another tool's slug rule and produce a dead link.
_HEADING = re.compile(
    r"^(?P<hashes>#{1,6})[ \t]+(?P<text>\S.*?)"
    r"(?:[ \t]*\{#(?P<anchor>[^}\s]+)\})?[ \t]*#*$"
)
_FENCE = re.compile(r"^[ \t]*(?P<ticks>`{3,}|~{3,})")


@dataclass
class Chunk:
    id: str
    source: str
    path: str
    doc_title: str
    heading: str
    breadcrumb: str
    text: str
    url: str

    @property
    def label(self) -> str:
        """Short human label for a citation chip."""
        if self.heading and self.heading != self.doc_title:
            return f"{self.doc_title} — {self.heading}"
        return self.doc_title


@dataclass
class Document:
    source: str
    path: str
    title: str
    url: str
    text: str
    outline: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.source}/{self.path}"


@dataclass
class Corpus:
    chunks: list[Chunk] = field(default_factory=list)
    documents: dict[str, Document] = field(default_factory=dict)
    # Which deployment this corpus belongs to. It rides here because the corpus is
    # what already reaches the index, the tool runner and the link resolver, so
    # they get the profile without an argument threaded through every call.
    profile: Profile | None = None

    def chunk(self, chunk_id: str) -> Chunk | None:
        return self._by_id.get(chunk_id)

    def document(self, doc_id: str) -> Document | None:
        return self.documents.get(doc_id)

    def __post_init__(self) -> None:
        self._by_id = {chunk.id: chunk for chunk in self.chunks}
        if self.profile is None:
            self.profile = profiles.active()


# --- helpers ---------------------------------------------------------------


def docs_url(rel_path: str, anchor: str = "") -> str:
    """Map `slurm/sbatch.md` to its published user-guide URL.

    Kept as a module-level name because it is the RCC profile's URL rule and
    several callers already knew it by this name; the rule itself lives in
    `sage/profiles/rcc.py` now.
    """
    return profiles.rcc.docs_url(rel_path, anchor)


def _host(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower()
    except ValueError:
        return ""


def _is_excluded(profile: Profile, source: str, rel_path: str, url: str) -> bool:
    if any(rel_path.endswith(name) for name in profile.excluded_files):
        return True
    if profile.kind(source) != SCRAPED or not url:
        return False
    return _host(url) in profile.excluded_hosts


def _first_heading(text: str) -> str:
    for line in text.splitlines()[:40]:
        match = _HEADING.match(line)
        if match:
            return plain_heading(match.group("text"))
    return ""


# --- markdown chunking -----------------------------------------------------


@dataclass
class _Section:
    level: int
    heading: str
    trail: list[str]
    lines: list[str] = field(default_factory=list)
    # Set when the heading carried `{#id}`; otherwise the anchor is slugified.
    anchor: str = ""

    @property
    def body(self) -> str:
        return collapse_blank_lines("\n".join(self.lines))


def _split_sections(text: str) -> list[_Section]:
    """Break normalized markdown at headings, tracking the ancestor trail."""
    sections = [_Section(level=0, heading="", trail=[])]
    stack: list[tuple[int, str]] = []
    fence: str | None = None

    for line in text.splitlines():
        match = _FENCE.match(line)
        if fence:
            if match and match.group("ticks")[0] == fence:
                fence = None
            sections[-1].lines.append(line)
            continue
        if match:
            fence = match.group("ticks")[0]
            sections[-1].lines.append(line)
            continue

        heading = _HEADING.match(line)
        if not heading:
            sections[-1].lines.append(line)
            continue

        level = len(heading.group("hashes"))
        title = plain_heading(heading.group("text"))
        while stack and stack[-1][0] >= level:
            stack.pop()
        sections.append(
            _Section(
                level=level,
                heading=title,
                trail=[name for _, name in stack],
                anchor=heading.group("anchor") or "",
            )
        )
        stack.append((level, title))

    return sections


def _split_oversized(body: str, limit: int) -> list[str]:
    """Break a long section on paragraph boundaries, never inside a fence."""
    if len(body) <= limit:
        return [body]

    blocks: list[str] = []
    current: list[str] = []
    fence: str | None = None

    for line in body.splitlines():
        match = _FENCE.match(line)
        if fence:
            current.append(line)
            if match and match.group("ticks")[0] == fence:
                fence = None
            continue
        if match:
            fence = match.group("ticks")[0]
            current.append(line)
            continue
        if not line.strip() and not fence:
            blocks.append("\n".join(current))
            current = []
            continue
        current.append(line)
    blocks.append("\n".join(current))

    parts: list[str] = []
    buffer = ""
    for block in blocks:
        candidate = f"{buffer}\n\n{block}" if buffer else block
        if len(candidate) > limit and buffer:
            parts.append(buffer)
            buffer = block
        else:
            buffer = candidate
    if buffer.strip():
        parts.append(buffer)
    return [part for part in parts if part.strip()]


def chunk_markdown(
    source: str,
    rel_path: str,
    raw: str,
    profile: Profile | None = None,
    page_url: str = "",
    title: str = "",
) -> tuple[Document, list[Chunk]]:
    """Chunk a markdown document at its headings.

    `page_url` is the page's own published URL when it carries one (a synced blog
    post does); otherwise the profile computes it from the path. `title` is the
    document's real title when something authoritative knows it — a post's front
    matter — rather than the first heading, which on this blog is frequently the
    first *section* and once is the author's name.
    """
    profile = profile or profiles.active()
    text = normalize_markdown(raw)
    doc_title = title or _first_heading(text) or pretty_title(rel_path)

    def url(anchor: str = "") -> str:
        if not page_url:
            return profile.url_for(source, rel_path, anchor)
        return f"{page_url}#{anchor}" if anchor else page_url

    document = Document(
        source=source,
        path=rel_path,
        title=doc_title,
        url=url(),
        text=text,
    )

    chunks: list[Chunk] = []
    seen_anchors: dict[str, int] = {}

    for section in _split_sections(text):
        body = section.body
        if section.heading:
            indent = "  " * max(section.level - 1, 0)
            document.outline.append(f"{indent}- {section.heading}")
        if not body.strip():
            continue
        if not section.heading and len(body) < config.MIN_CHUNK_CHARS:
            continue

        # An explicit `{#id}` wins: it is the anchor the rendered page really has.
        anchor = section.anchor or (
            slugify(section.heading) if section.heading else ""
        )
        # What the *citation* may point at. For a page that brought its own URL,
        # only an explicit anchor is known to exist: slugifying a heading there is
        # guessing at another renderer's id, and a guess that misses is a link that
        # silently lands at the top of the page instead of the section cited.
        # Chunk ids keep using `anchor` either way — they are internal.
        link_anchor = (section.anchor if page_url else anchor)
        trail: list[str] = []
        for part in (doc_title, *section.trail, section.heading):
            # The page H1 usually repeats as the first section heading.
            if part and (not trail or trail[-1] != part):
                trail.append(part)
        breadcrumb = " › ".join(trail)

        for index, part in enumerate(_split_oversized(body, config.MAX_CHUNK_CHARS)):
            base = anchor or "intro"
            seen = seen_anchors.get(base, 0)
            seen_anchors[base] = seen + 1
            suffix = base if seen == 0 and index == 0 else f"{base}-{seen}"
            heading_text = section.heading or doc_title
            chunks.append(
                Chunk(
                    id=f"{source}/{rel_path}#{suffix}",
                    source=source,
                    path=rel_path,
                    doc_title=doc_title,
                    heading=heading_text,
                    breadcrumb=breadcrumb or doc_title,
                    text=part,
                    url=url(link_anchor),
                )
            )

    return document, chunks


def chunk_post(
    source: str, rel_path: str, raw: str, profile: Profile | None = None
) -> tuple[Document, list[Chunk]]:
    """A synced blog post: a URL/title header, then markdown with real anchors.

    The header is what lets a citation deep-link to the live page. Hugo's own
    permalink is recorded at sync time rather than recomputed here, because
    reimplementing another tool's slug rule produces dead links that no test in
    this repo could notice.
    """
    profile = profile or profiles.active()
    url, title, body = parse_post_header(raw)
    return chunk_markdown(
        source, rel_path, body, profile=profile, page_url=url, title=title
    )


# --- scraped-page chunking -------------------------------------------------


def chunk_scraped(
    source: str, rel_path: str, raw: str, profile: Profile | None = None
) -> tuple[Document, list[Chunk]]:
    """Scraped pages have no heading structure, so window them by paragraph."""
    profile = profile or profiles.active()
    url, title, body = parse_scraped(raw)
    doc_title = title or pretty_title(rel_path)
    document = Document(
        source=source,
        path=rel_path,
        title=doc_title,
        url=url or profile.url_for(source, rel_path, ""),
        text=body,
    )

    paragraphs = [line.strip() for line in body.splitlines() if line.strip()]
    windows: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        candidate = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        if len(candidate) > config.WEB_CHUNK_CHARS and buffer:
            windows.append(buffer)
            tail = buffer[-config.WEB_CHUNK_OVERLAP :]
            buffer = f"{tail}\n\n{paragraph}" if config.WEB_CHUNK_OVERLAP else paragraph
        else:
            buffer = candidate
    if buffer.strip():
        windows.append(buffer)

    chunks = [
        Chunk(
            id=f"{source}/{rel_path}#{index + 1}",
            source=source,
            path=rel_path,
            doc_title=doc_title,
            heading=doc_title if index == 0 else f"{doc_title} (part {index + 1})",
            breadcrumb=doc_title,
            text=window,
            url=document.url,
        )
        for index, window in enumerate(windows)
        if len(window) >= config.MIN_CHUNK_CHARS or index == 0
    ]
    return document, chunks


# --- build -----------------------------------------------------------------

_BUILDERS = {
    SCRAPED: chunk_scraped,
    POST: chunk_post,
}


def build(
    sources: dict[str, str] | None = None, profile: Profile | None = None
) -> Corpus:
    """Scan the profile's source trees and return a fully chunked corpus.

    `sources` overrides only the *paths*; the kinds, extensions and weights come
    from the profile either way. It is kept because callers and tests already pass
    it, and because pointing a profile at a different checkout is a legitimate
    thing to want.
    """
    profile = profile or profiles.active()
    paths = sources or profile.paths
    chunks: list[Chunk] = []
    documents: dict[str, Document] = {}
    skipped = 0

    for source, base in paths.items():
        if not os.path.isdir(base):
            logger.warning("Source tree missing, skipping: %s", base)
            continue
        declared = profile.source(source)
        extensions = declared.extensions if declared else (".md", ".txt")

        for root, _dirs, names in os.walk(base):
            for name in sorted(names):
                if not name.lower().endswith(extensions):
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, base).replace(os.sep, "/")
                try:
                    with open(full, encoding="utf-8", errors="replace") as handle:
                        raw = handle.read()
                except OSError as exc:
                    logger.warning("Unreadable document %s: %s", full, exc)
                    continue

                kind = profile.kind(source)
                if kind == SCRAPED:
                    probe_url, _title, _body = parse_scraped(raw)
                else:
                    probe_url = ""
                if _is_excluded(profile, source, rel, probe_url):
                    skipped += 1
                    continue

                builder = _BUILDERS.get(kind, chunk_markdown)
                document, page_chunks = builder(source, rel, raw, profile)
                if not page_chunks:
                    # Surfaces upstream gaps: docs/data_transfer/cloud/rclone.md is
                    # a 0-byte file in the User Guide, so nothing can cite it.
                    logger.warning("No indexable content in %s", document.id)
                documents[document.id] = document
                chunks.extend(page_chunks)

    logger.info(
        "Corpus built: %d chunks across %d documents (%d excluded)",
        len(chunks),
        len(documents),
        skipped,
    )
    return Corpus(chunks=chunks, documents=documents, profile=profile)


def summarize(corpus: Corpus) -> str:
    """One-line description used in logs and the About panel."""
    return f"{len(corpus.documents)} pages · {len(corpus.chunks)} sections"
