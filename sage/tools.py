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


def _topic_map(index: Index, limit: int = 24) -> str:
    """Top-level page titles, so a missed search has somewhere to go next.

    Cheaper and more robust than a `list_docs` tool: it costs nothing when searches
    succeed, and it gives the model a recovery route using the tools it already has
    instead of a third tool competing for its attention.
    """
    seen: dict[str, str] = {}
    for chunk in index.corpus.chunks:
        if chunk.source != "docs":
            continue
        top = chunk.path.split("/", 1)[0].removesuffix(".md")
        seen.setdefault(top, chunk.doc_title)
        if len(seen) >= limit:
            break
    if not seen:
        return ""
    titles = ", ".join(sorted(seen.values()))
    return f"\n\nThe documentation covers, at the top level: {titles}."


def format_search_results(results, caveat: str = "") -> str:
    if not results:
        return _NO_RESULTS
    lines = []
    if caveat:
        # Ahead of the results, not after them: the model reads top-down, and a
        # warning underneath six confident-looking rows arrives too late.
        lines += [f"RETRIEVAL WARNING: {caveat}", ""]
    lines += [
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


def gather_context(index: Index, query: str, limit: int | None = None):
    """One-shot retrieval for models that cannot call tools.

    Returns (context_text, chunks). The chunks become the answer's Sources strip,
    exactly as if the model had read them itself.

    The caveat matters more on this path than on the tool loop: a toolless model
    cannot search again when the context is wrong, so if retrieval was weak the only
    thing standing between it and an invented answer is being told so.
    """
    results = index.search(query, limit or config.SEARCH_RESULTS)
    blocks = [
        f"=== {result.chunk.breadcrumb} ({result.chunk.id}) ===\n{result.chunk.text}"
        for result in results
    ]
    caveat = index.assess(query, results).caveat()
    if caveat and blocks:
        blocks.insert(0, f"RETRIEVAL WARNING: {caveat}")
    return "\n\n".join(blocks), [result.chunk for result in results]


def follow_up_queries(question: str, previous: list[dict] | None) -> str:
    """Fold the previous turn's topic into a short follow-up question.

    `gather_context` retrieved on the raw last message, so on the toolless path
    "what about on Midway3?" became a BM25 query of five stopwords and a cluster
    name and returned generic cluster pages. Tool-capable models write their own
    standalone query (the system prompt now insists on it); models without tools
    have nothing, so the carry-forward is done here instead.

    Deliberately mechanical rather than a model call: this path exists *because*
    the model is limited, so spending another request on it is the wrong trade.
    """
    if not previous:
        return question
    words = [word for word in question.lower().split() if word]
    looks_like_follow_up = len(words) <= 12 and (
        any(question.lower().startswith(marker) for marker in (
            "what about", "and on", "how about", "same for", "does that",
            "what if", "is it", "and for", "on ", "for ",
        ))
        or any(word in {"it", "that", "this", "those", "there", "them"}
               for word in words)
    )
    if not looks_like_follow_up:
        return question
    # The previous answer's cited section titles are the topic, and they are already
    # stored on the message — no guessing and no extra retrieval.
    labels = []
    for message in reversed(previous):
        for source in message.get("sources") or []:
            label = (source.get("label") or "").split("—")[-1].strip()
            if label and label not in labels:
                labels.append(label)
        if labels:
            break
    if not labels:
        return question
    return f"{question} {' '.join(labels[:2])}"


class ToolRunner:
    """Executes tool calls and records which sections were actually read."""

    def __init__(self, index: Index) -> None:
        self.index = index
        self.sources: list[Chunk] = []
        self.queries: list[str] = []
        self.last_read: str = ""
        # The trace, kept rather than discarded: (query, top score, unknown terms).
        # This is the only record of a search that *missed*, which is what tells a
        # retrieval failure apart from a documentation gap.
        self.searches: list[dict] = []
        self.reads: list[str] = []
        self.weak_searches = 0
        self._served: dict[tuple[str, str], str] = {}

    def _remember(self, chunk: Chunk) -> None:
        if all(existing.id != chunk.id for existing in self.sources):
            self.sources.append(chunk)

    def run(self, name: str, arguments: dict) -> str:
        if name == SEARCH_DOCS:
            return self._search((arguments.get("query") or "").strip())
        if name == READ_DOC:
            return self._read(str(arguments.get("path") or "").strip())
        return f"Unknown tool: {name}"

    def _search(self, query: str) -> str:
        self.queries.append(query)
        logger.info("search_docs(%r)", query)
        results = self.index.search(query)
        assessment = self.index.assess(query, results)
        caveat = assessment.caveat()
        if caveat:
            self.weak_searches += 1
        self.searches.append(
            {
                "query": query,
                "results": len(results),
                "top_score": assessment.top_score,
                "margin": assessment.margin,
                "unknown_terms": list(assessment.unknown_terms),
                "confident": assessment.confident,
            }
        )
        body = format_search_results(results, caveat)
        if not results:
            body += _topic_map(self.index)
        return body

    def _read(self, path: str) -> str:
        if not path or "/" not in path:
            return (
                "Error: invalid path. Pass the exact `path` from a search_docs result, "
                "e.g. 'docs/slurm/sbatch.md#gpu-jobs'."
            )

        # A section re-read inside one turn used to be re-sent in full, and because
        # every round resends the whole conversation it was then paid for again in
        # each later round. Roughly 900 tokens per duplicate, compounding.
        key = (READ_DOC, path)
        if key in self._served:
            return (
                f"(already provided above — see the section titled "
                f"'{self._served[key]}'. Do not read it again; answer from it.)"
            )

        corpus = self.index.corpus
        chunk = corpus.chunk(path)
        if chunk is not None:
            self._remember(chunk)
            self.last_read = chunk.label
            self.reads.append(chunk.label)
            self._served[key] = chunk.breadcrumb
            document = corpus.document(f"{chunk.source}/{chunk.path}")
            # The page outline is appended only when the section is short enough for
            # it to be worth the tokens. On docs/slurm/sbatch.md it was a 222-token
            # surcharge on a 409-token section, resent every later round, for
            # navigation the model rarely uses once it has the section it asked for.
            outline = ""
            if document and len(chunk.text) < config.OUTLINE_BELOW_CHARS:
                outline = _outline(document)
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
        self.reads.append(document.title)
        self._served[key] = document.title
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
