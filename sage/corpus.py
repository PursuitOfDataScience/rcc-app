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

from . import config
from .normalize import (
    collapse_blank_lines,
    normalize_markdown,
    parse_scraped,
    plain_heading,
    pretty_title,
    slugify,
)

logger = logging.getLogger(__name__)

_HEADING = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<text>\S.*?)[ \t]*#*$")
_FENCE = re.compile(r"^[ \t]*(?P<ticks>`{3,}|~{3,})")
_RCC_SITE = "https://rcc.uchicago.edu/"


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

    def chunk(self, chunk_id: str) -> Chunk | None:
        return self._by_id.get(chunk_id)

    def document(self, doc_id: str) -> Document | None:
        return self.documents.get(doc_id)

    def __post_init__(self) -> None:
        self._by_id = {chunk.id: chunk for chunk in self.chunks}


# --- helpers ---------------------------------------------------------------


def docs_url(rel_path: str, anchor: str = "") -> str:
    """Map `slurm/sbatch.md` to its published user-guide URL.

    An `index.md` is the directory it sits in, at every depth, not just the top one.
    mkdocs runs with `use_directory_urls` (the default), which publishes
    `software/index.md` at `software/` — so citing it to `software/index/` is a 404,
    and it was: 16 indexed sections across `software/index.md` and
    `tutorials/gis/index.md` pointed at a dead page.
    """
    slug = re.sub(r"\.md$", "", rel_path, flags=re.IGNORECASE).strip("/")
    slug = re.sub(r"(?:^|/)index$", "", slug).strip("/")
    if not slug:
        url = config.DOCS_BASE_URL
    else:
        url = f"{config.DOCS_BASE_URL.rstrip('/')}/{slug}/"
    return f"{url}#{anchor}" if anchor else url


def _host(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower()
    except ValueError:
        return ""


def _is_excluded(source: str, rel_path: str, url: str) -> bool:
    if any(rel_path.endswith(name) for name in config.EXCLUDED_FILES):
        return True
    return source == "web" and bool(url) and _host(url) in config.EXCLUDED_HOSTS


# --- markdown chunking -----------------------------------------------------


@dataclass
class _Section:
    level: int
    heading: str
    trail: list[str]
    lines: list[str] = field(default_factory=list)

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
            _Section(level=level, heading=title, trail=[name for _, name in stack])
        )
        stack.append((level, title))

    return sections


def _document_title(sections: list[_Section]) -> str:
    """The page's H1, which is the title mkdocs publishes it under.

    Any heading used to do, taken from a 40-line window. Five pages in the guide have no
    H1, so each was named after whichever subsection came first: the R page was cited as
    "Table of Contents", `software/index.md` as "Private Software", and
    `tutorials/sde3/data-transfer.md` as "Step 1. From Data Provider to SDE Virtual
    Desktop" — a name that page also carries as a real section, so its citation and its
    own Related entry read identically while linking to two different places.

    The window was what kept a code comment out of the title, not a rule: the R page has
    five `# Install renv …` lines inside an R fence, 274 lines down. Reading the split
    sections rather than raw lines is fence-aware for free, so the H1 looked for here is
    always a real one wherever it sits, and a page without one falls back to its path.
    """
    return next(
        (item.heading for item in sections if item.level == 1 and item.heading), ""
    )


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


def chunk_markdown(source: str, rel_path: str, raw: str) -> tuple[Document, list[Chunk]]:
    text = normalize_markdown(raw)
    sections = _split_sections(text)
    doc_title = _document_title(sections) or pretty_title(rel_path)
    document = Document(
        source=source,
        path=rel_path,
        title=doc_title,
        url=docs_url(rel_path) if source == "docs" else _RCC_SITE,
        text=text,
    )

    chunks: list[Chunk] = []
    seen_anchors: dict[str, int] = {}

    for section in sections:
        body = section.body
        if section.heading:
            indent = "  " * max(section.level - 1, 0)
            document.outline.append(f"{indent}- {section.heading}")
        if not body.strip():
            continue
        if not section.heading and len(body) < config.MIN_CHUNK_CHARS:
            continue

        anchor = slugify(section.heading) if section.heading else ""
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
                    url=docs_url(rel_path, anchor) if source == "docs" else _RCC_SITE,
                )
            )

    return document, chunks


# --- scraped-page chunking -------------------------------------------------


def chunk_scraped(source: str, rel_path: str, raw: str) -> tuple[Document, list[Chunk]]:
    """Scraped pages have no heading structure, so window them by paragraph."""
    url, title, body = parse_scraped(raw)
    doc_title = title or pretty_title(rel_path)
    document = Document(
        source=source,
        path=rel_path,
        title=doc_title,
        url=url or _RCC_SITE,
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
            # The page title, for every window. `(part 3)` used to go here, and it was
            # the index's private arithmetic wearing a section heading's clothes: a
            # scraped page has no headings to cut on, so window 3 is not a section
            # called "part 3", it is the same page cut at 2400 characters — and it
            # carries the same URL, because there is no anchor to deep-link to either.
            # The reader saw the cut and could not act on it, since `Our Team — Our
            # Team (part 3)` in the Sources strip and `Our Team (part 3)` under Related
            # both land exactly where plain `Our Team` lands. The window number is kept
            # where it is needed and nowhere else: in the id, which is what `read_doc`
            # takes to fetch one window in full.
            heading=doc_title,
            breadcrumb=doc_title,
            text=window,
            url=document.url,
        )
        for index, window in enumerate(windows)
        if len(window) >= config.MIN_CHUNK_CHARS or index == 0
    ]
    return document, chunks


# --- build -----------------------------------------------------------------


def build(sources: dict[str, str] | None = None) -> Corpus:
    """Scan the configured source trees and return a fully chunked corpus."""
    sources = sources or config.SOURCES
    chunks: list[Chunk] = []
    documents: dict[str, Document] = {}
    skipped = 0

    for source, base in sources.items():
        if not os.path.isdir(base):
            logger.warning("Source tree missing, skipping: %s", base)
            continue
        extensions = config.SOURCE_EXTENSIONS.get(source, (".md", ".txt"))

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

                if source == "web":
                    probe_url, _title, _body = parse_scraped(raw)
                else:
                    probe_url = ""
                if _is_excluded(source, rel, probe_url):
                    skipped += 1
                    continue

                builder = chunk_scraped if source == "web" else chunk_markdown
                document, page_chunks = builder(source, rel, raw)
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
    return Corpus(chunks=chunks, documents=documents)


def summarize(corpus: Corpus) -> str:
    """One-line description used in logs and the About panel."""
    return f"{len(corpus.documents)} pages · {len(corpus.chunks)} sections"
