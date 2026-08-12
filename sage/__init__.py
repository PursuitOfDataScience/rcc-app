"""Sage — a documentation assistant, assembled from parts you can replace.

Nothing in this package names a particular set of documents, a particular model or a
particular organisation. What it is *about* comes from a profile (`sage/profile.py`,
`profiles/*.toml`); what it is *made of* comes from four registries, each one a place
a deployment substitutes its own implementation:

    corpus.readers    a file -> a document and its chunks     (markdown, scraped)
    corpus.urls       a document -> the URL a citation opens   (mkdocs, embedded, …)
    retrieval.engines a corpus -> something that searches it   (bm25)
    providers.adapters a profile entry -> a chat endpoint      (openai, mistral)
    tools.factories   a retriever -> a tool the model can call (search_docs, read_doc)

`runtime.build()` is the composition root that turns a profile into a working
assistant; `sage/ui/` draws one. Everything here is importable without Streamlit,
which is what keeps the retrieval layer unit-testable — `sage.ui` and `app.py` are
the only Streamlit-dependent code.
"""

__all__ = [
    "config",
    "corpus",
    "env",
    "feedback",
    "files",
    "history",
    "limits",
    "links",
    "llm",
    "normalize",
    "profile",
    "prompts",
    "providers",
    "registry",
    "retrieval",
    "runtime",
    "tools",
]
