"""Sage — the RCC User Guide assistant.

The package is deliberately split so that everything except `sage.ui` is importable
without Streamlit, which is what makes the retrieval layer unit-testable.
"""

__all__ = [
    "config",
    "corpus",
    "files",
    "history",
    "links",
    "llm",
    "normalize",
    "prompts",
    "search",
]
