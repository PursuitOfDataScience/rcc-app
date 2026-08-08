"""Sage — a grounded, citation-first documentation assistant.

The package is deliberately split so that everything except the Streamlit view is
importable without Streamlit, which is what makes the retrieval layer and the agent
loop unit-testable.

Which corpus it answers from is a `Profile` (`SAGE_PROFILE`), not a property of the
package: `profiles.rcc` is the UChicago RCC User Guide assistant, `profiles.site`
the personal-website one. Nothing outside `sage/profiles/` should name either.
"""

__all__ = [
    "config",
    "corpus",
    "engine",
    "files",
    "history",
    "links",
    "llm",
    "normalize",
    "profile",
    "profiles",
    "prompts",
    "search",
    "sitehtml",
]
