"""The two retrieval tools exposed to the model, and their execution.

Reads resolve against the in-memory corpus rather than the filesystem, so the
old `realpath` traversal guard is no longer the thing standing between a crafted
`path` argument and an arbitrary file — only ids that were indexed can resolve at
all. Unknown ids get an error string the model can recover from.
"""

from __future__ import annotations

import logging

from . import config
from .corpus import Chunk
from .search import Index

logger = logging.getLogger(__name__)

SEARCH_DOCS = "search_docs"
READ_DOC = "read_doc"

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": SEARCH_DOCS,
            "description": (
                "Search the official RCC User Guide and website for sections relevant "
                "to the user's question. Returns ranked results, each with a `path`, a "
                "section title and a snippet. Call this FIRST for any RCC question "
                "about accounts, connecting, Slurm, storage, software, GPUs or policy, "
                "then read the most promising result with read_doc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Keywords or a natural-language question, e.g. "
                            "'sbatch GPU job' or 'scratch quota purge policy'."
                        ),
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": READ_DOC,
            "description": (
                "Read one documentation section in full. Pass the exact `path` from a "
                "search_docs result (for example 'docs/slurm/sbatch.md#gpu-jobs'). "
                "Dropping the '#section' part returns the whole page, or its outline "
                "if the page is very long."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The exact `path` value from a search_docs result.",
                    }
                },
                "required": ["path"],
            },
        },
    },
]

_NO_RESULTS = (
    "No matching RCC documentation was found. Try different or broader keywords. "
    "If the topic genuinely is not covered, say so plainly and point the user at "
    f"the RCC Help Desk ({config.HELP_DESK_EMAIL}) rather than guessing specifics."
)


def format_search_results(results) -> str:
    if not results:
        return _NO_RESULTS
    lines = [
        "Top matching RCC documentation sections. "
        "Call read_doc with the exact `path` to read one in full.",
        "",
    ]
    for result in results:
        lines.append(f"- path: {result.id}")
        lines.append(f"  section: {result.chunk.breadcrumb}  (source: {result.source})")
        lines.append(f"  snippet: {result.snippet}")
    return "\n".join(lines)


def _outline(document) -> str:
    if not document.outline:
        return ""
    shown = document.outline[:60]
    more = "" if len(document.outline) == len(shown) else "\n  … (outline truncated)"
    return "Sections on this page:\n" + "\n".join(shown) + more


class ToolRunner:
    """Executes tool calls and records which sections were actually read."""

    def __init__(self, index: Index) -> None:
        self.index = index
        self.sources: list[Chunk] = []
        self.queries: list[str] = []
        self.last_read: str = ""

    def _remember(self, chunk: Chunk) -> None:
        if all(existing.id != chunk.id for existing in self.sources):
            self.sources.append(chunk)

    def run(self, name: str, arguments: dict) -> str:
        if name == SEARCH_DOCS:
            query = (arguments.get("query") or "").strip()
            self.queries.append(query)
            logger.info("search_docs(%r)", query)
            return format_search_results(self.index.search(query))
        if name == READ_DOC:
            return self._read(str(arguments.get("path") or "").strip())
        return f"Unknown tool: {name}"

    def _read(self, path: str) -> str:
        if not path or "/" not in path:
            return (
                "Error: invalid path. Pass the exact `path` from a search_docs result, "
                "e.g. 'docs/slurm/sbatch.md#gpu-jobs'."
            )

        corpus = self.index.corpus
        chunk = corpus.chunk(path)
        if chunk is not None:
            self._remember(chunk)
            self.last_read = chunk.label
            document = corpus.document(f"{chunk.source}/{chunk.path}")
            outline = _outline(document) if document else ""
            header = f"=== {chunk.breadcrumb} ({chunk.id}) ==="
            body = "\n\n".join(part for part in (header, chunk.text, outline) if part)
            return body

        document = corpus.document(path.split("#", 1)[0])
        if document is None:
            return (
                f"Error: '{path}' is not in the documentation index. "
                "Run search_docs again and use a `path` exactly as returned."
            )

        self.last_read = document.title
        first = next(
            (item for item in corpus.chunks if item.path == document.path), None
        )
        if first is not None:
            self._remember(first)

        header = f"=== {document.title} ({document.id}) ==="
        if len(document.text) <= config.MAX_DOC_CHARS:
            return f"{header}\n\n{document.text}"

        intro = document.text[: config.MAX_DOC_CHARS // 3]
        return (
            f"{header}\n\nThis page is long; here is the beginning plus its outline. "
            "Call read_doc again with 'path#section-anchor' for a specific section.\n\n"
            f"{intro}\n\n{_outline(document)}"
        )
