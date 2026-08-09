"""Sage — the RCC User Guide assistant.

Every module here is importable without Streamlit, which is what makes the retrieval
layer unit-testable; `app.py` at the repository root is the only Streamlit-dependent
file. (This used to name a `sage.ui` module as the exception. There has never been
one.)
"""

__all__ = [
    "config",
    "corpus",
    "feedback",
    "files",
    "history",
    "links",
    "llm",
    "normalize",
    "prompts",
    "providers",
    "search",
    "tools",
]
