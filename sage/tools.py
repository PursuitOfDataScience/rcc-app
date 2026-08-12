"""The tools the model can call, and the thing that runs them.

A tool is an object with a `name`, a `schema` the provider is sent, and a `run` that
returns text. Two ship — search the index, read one section — and they are built by
factories in a registry, so a deployment that wants a third (look up a term, check a
status page, query an API the documentation describes) registers one and names it:

    from sage.tools import factories, Toolset
    factories.register("glossary", lambda retriever, identity: Glossary(...))

Reads resolve against the in-memory corpus rather than the filesystem, so the old
`realpath` traversal guard is no longer the thing standing between a crafted `path`
argument and an arbitrary file — only ids that were indexed can resolve at all.
Unknown ids get an error string the model can recover from.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from . import config
from .corpus import Chunk
from .profile import Identity
from .profile import active as _active
from .registry import Registry
from .retrieval import Retriever

logger = logging.getLogger(__name__)

SEARCH_DOCS = "search_docs"
READ_DOC = "read_doc"

# What a tool calls to say "the answer may now cite this section". Passing it in
# rather than letting a tool reach for the runner keeps a custom tool from having to
# know how sources are deduplicated.
Record = Callable[[Chunk], None]


class Tool(Protocol):
    name: str

    @property
    def schema(self) -> dict: ...

    def run(self, arguments: dict, record: Record) -> str: ...


# name -> (retriever, identity) -> Tool
factories: Registry = Registry("tool")

# The two a documentation assistant is built out of. A profile that wants a different
# set says so; this is the default because search-then-read is what the prompt
# describes and what the retrieval eval measures.
DEFAULT_TOOLS = (SEARCH_DOCS, READ_DOC)


def _text(value) -> str:
    """A tool argument as a string, whatever the model made it.

    `None` becomes empty rather than "None", which would go on to be searched for.
    """
    return "" if value is None else str(value)


def _outline(document) -> str:
    if not document.outline:
        return ""
    shown = document.outline[:60]
    more = "" if len(document.outline) == len(shown) else "\n  … (outline truncated)"
    return "Sections on this page:\n" + "\n".join(shown) + more


# --- search ----------------------------------------------------------------


class SearchDocs:
    """Rank the corpus for a query and describe the best sections."""

    name = SEARCH_DOCS

    def __init__(self, retriever: Retriever, identity: Identity) -> None:
        self.retriever = retriever
        self.identity = identity

    @property
    def _about(self) -> str:
        topics = self.identity.topics.strip()
        return f" about {topics}" if topics else ""

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    f"Search {self.identity.corpus_name} for sections relevant to "
                    "the user's question. Returns ranked results, each with a "
                    "`path`, a section title and a snippet. Call this FIRST for any "
                    f"{self.identity.qualifier}question{self._about}, then read the "
                    "most promising result with read_doc."
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
        }

    def no_results(self) -> str:
        pointer = (
            f" and point the user at the {self.identity.contact_label} "
            f"({self.identity.contact})"
            if self.identity.has_contact
            else ""
        )
        return (
            f"No matching {self.identity.qualifier}documentation was found. Try "
            "different or broader keywords. If the topic genuinely is not covered, "
            f"say so plainly{pointer} rather than guessing specifics."
        )

    def format(self, results, caveat: str = "") -> str:
        if not results:
            return self.no_results()
        lines = []
        if caveat:
            # Ahead of the results, not after them: a model reads top-down, and a
            # warning underneath six confident-looking rows arrives too late to
            # change the answer.
            lines += [f"RETRIEVAL WARNING: {caveat}", ""]
        lines += [
            f"Top matching {self.identity.qualifier}documentation sections. "
            "Call read_doc with the exact `path` to read one in full.",
            "",
        ]
        for result in results:
            lines.append(f"- path: {result.id}")
            lines.append(
                f"  section: {result.chunk.breadcrumb}  (source: {result.source})"
            )
            lines.append(f"  snippet: {result.snippet}")
        return "\n".join(lines)

    def run(self, arguments: dict, record: Record) -> str:
        query = _text(arguments.get("query")).strip()
        logger.info("search_docs(%r)", query)
        results = self.retriever.search(query)
        assessment = self.retriever.assess(query, results)
        if not assessment.confident:
            logger.info("weak retrieval for %r (top %.1f, unseen %s)",
                        query, assessment.top_score, assessment.unknown_terms)
        return self.format(results, assessment.caveat())


# --- read ------------------------------------------------------------------


class ReadDoc:
    """Return one indexed section, or a long page's outline, in full."""

    name = READ_DOC

    def __init__(self, retriever: Retriever, identity: Identity) -> None:
        self.retriever = retriever
        self.identity = identity

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "Read one documentation section in full. Pass the exact `path` "
                    "from a search_docs result (for example "
                    f"'{self.identity.path_example}'). Dropping the '#section' part "
                    "returns the whole page, or its outline if the page is very long."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": (
                                "The exact `path` value from a search_docs result."
                            ),
                        }
                    },
                    "required": ["path"],
                },
            },
        }

    def run(self, arguments: dict, record: Record) -> str:
        path = _text(arguments.get("path")).strip()
        if not path or "/" not in path:
            return (
                "Error: invalid path. Pass the exact `path` from a search_docs "
                f"result, e.g. '{self.identity.path_example}'."
            )

        corpus = self.retriever.corpus
        chunk = corpus.chunk(path)
        if chunk is not None:
            record(chunk)
            document = corpus.document(f"{chunk.source}/{chunk.path}")
            outline = _outline(document) if document else ""
            header = f"=== {chunk.breadcrumb} ({chunk.id}) ==="
            return "\n\n".join(part for part in (header, chunk.text, outline) if part)

        document = corpus.document(path.split("#", 1)[0])
        if document is None:
            return (
                f"Error: '{path}' is not in the documentation index. "
                "Run search_docs again and use a `path` exactly as returned."
            )

        first = next(
            (item for item in corpus.chunks if item.path == document.path), None
        )
        if first is not None:
            record(first)

        header = f"=== {document.title} ({document.id}) ==="
        if len(document.text) <= config.MAX_DOC_CHARS:
            return f"{header}\n\n{document.text}"

        intro = document.text[: config.MAX_DOC_CHARS // 3]
        return (
            f"{header}\n\nThis page is long; here is the beginning plus its outline. "
            "Call read_doc again with 'path#section-anchor' for a specific section.\n\n"
            f"{intro}\n\n{_outline(document)}"
        )


factories.register(SEARCH_DOCS, SearchDocs)
factories.register(READ_DOC, ReadDoc)


# --- the set, and running it ------------------------------------------------


class Toolset:
    """The tools this deployment offers, and their schemas.

    Built once per runtime and shared; a `ToolRunner` is per turn, because it is what
    remembers which sections the turn actually read.
    """

    def __init__(self, tools: list[Tool]) -> None:
        self.tools = tools
        self.by_name = {tool.name: tool for tool in tools}

    @property
    def schemas(self) -> list[dict]:
        return [tool.schema for tool in self.tools]

    def runner(self) -> ToolRunner:
        return ToolRunner(self)


def build(
    retriever: Retriever,
    identity: Identity | None = None,
    names: tuple[str, ...] = DEFAULT_TOOLS,
) -> Toolset:
    who = identity or _active().identity
    return Toolset([factories.get(name)(retriever, who) for name in names])


class ToolRunner:
    """Executes tool calls for one turn and records which sections were read."""

    def __init__(self, toolset: Toolset) -> None:
        self.toolset = toolset
        self.sources: list[Chunk] = []
        self.queries: list[str] = []
        self.last_read: str = ""

    def _remember(self, chunk: Chunk) -> None:
        if all(existing.id != chunk.id for existing in self.sources):
            self.sources.append(chunk)
        # The label of the section most recently exposed, for the status line.
        self.last_read = chunk.label

    def run(self, name: str, arguments: dict) -> str:
        tool = self.toolset.by_name.get(name)
        if tool is None:
            return f"Unknown tool: {name}"
        # `_text(...)` inside each tool because a tool argument is whatever the model
        # typed. `llm._parse` guarantees a dict and nothing about what is in it, and a
        # model that types its query as a number — `{"query": 123}` — used to end the
        # turn with an AttributeError dressed up as "something went wrong reaching the
        # assistant".
        if name == SEARCH_DOCS:
            self.queries.append(_text(arguments.get("query")).strip())
        return tool.run(arguments, self._remember)


def gather_context(retriever: Retriever, query: str, limit: int | None = None):
    """One-shot retrieval for models that cannot call tools.

    Returns (context_text, chunks). The chunks become the answer's Sources strip,
    exactly as if the model had read them itself.

    The caveat matters more here than in the tool loop: a model that cannot call tools
    cannot search again when the context is wrong, so if retrieval was weak, being told
    so is the only thing between it and an invented answer.
    """
    results = retriever.search(query, limit or config.SEARCH_RESULTS)
    blocks = [
        f"=== {result.chunk.breadcrumb} ({result.chunk.id}) ===\n{result.chunk.text}"
        for result in results
    ]
    caveat = retriever.assess(query, results).caveat()
    if caveat and blocks:
        blocks.insert(0, f"RETRIEVAL WARNING: {caveat}")
    return "\n\n".join(blocks), [result.chunk for result in results]
