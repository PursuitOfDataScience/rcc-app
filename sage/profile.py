"""What makes one deployment of Sage different from another.

Everything RCC-specific in this repo was data pretending to be code: a base URL in
`config`, a slug rule in `corpus`, a synonym table in `search`, tool copy in
`tools`, a system prompt in `prompts`, starter cards and a page title in `app.py`,
and a brand colour in the stylesheet. Nine files had to be edited in concert to
point the assistant at a different corpus, and nothing checked that they agreed.

A `Profile` is that set of values in one frozen object. `sage.profiles` holds the
instances and picks between them on `SAGE_PROFILE`; nothing else in the package
should mention RCC or any other particular deployment.

The profile travels on the `Corpus`, which already flows into `Index`, `ToolRunner`
and the link resolver — so adding one did not mean threading an argument through
every call in the package.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

# How a source tree is turned into chunks.
#
#   markdown — headings become chunk boundaries and anchors (the User Guide)
#   scraped  — no heading structure; windowed by paragraph (the scraped site)
#   post     — markdown with an explicit URL header and `{#anchor}` headings, which
#              is what a rendered blog post becomes when it is synced in
MARKDOWN = "markdown"
SCRAPED = "scraped"
POST = "post"


@dataclass(frozen=True)
class Source:
    """One tree of documents, and how to read it."""

    name: str
    path: str
    extensions: tuple[str, ...]
    kind: str = MARKDOWN
    # A mild prior applied to every chunk from this tree, for corpora where one
    # source is more authoritative than another.
    weight: float = 1.0


@dataclass(frozen=True)
class Profile:
    key: str

    # --- corpus ---
    sources: tuple[Source, ...]
    # Bare filename suffixes to keep out of the index, whatever tree they are in.
    excluded_files: tuple[str, ...] = ()
    # Scraped hosts to keep out; only meaningful for `SCRAPED` sources.
    excluded_hosts: tuple[str, ...] = ()
    # (source, rel_path, anchor) -> published URL. Used for citation links, and as
    # the fallback when a scraped page does not carry its own URL.
    url_for: Callable[[str, str, str], str] = lambda source, path, anchor: ""
    # Where an unresolvable internal link goes rather than nowhere.
    home_url: str = ""

    # --- retrieval ---
    # Bidirectional groups, expanded at query time at a reduced weight so an exact
    # match always outranks a synonym match.
    synonyms: tuple[tuple[str, ...], ...] = ()
    # Terms the stemmer must leave alone.
    protected_terms: frozenset[str] = frozenset()

    # --- what the model is told ---
    system_prompt: str = ""
    # The corpus in a few words, as it appears in tool descriptions: "the official
    # RCC User Guide and website", "Y. Yu's blog posts".
    corpus_description: str = "the documentation"
    search_description: str = ""
    read_description: str = ""
    no_results: str = ""
    # Prepended to the retrieved context for models that cannot call tools.
    grounding_instruction: str = ""
    # The noun used in status lines: "Searching {searching_noun} for …".
    searching_noun: str = "the docs"

    # --- the view ---
    page_title: str = "Sage"
    page_icon: str = "🌱"
    welcome_title: str = "What can I help you with?"
    welcome_subtitle: str = ""
    index_spinner: str = "Indexing documentation…"
    # (icon, card label, question actually sent)
    examples: tuple[tuple[str, str, str], ...] = ()
    # CSS custom properties layered over static/app.css, so a deployment can be
    # rebranded without a second stylesheet. `brand_dark` is not optional in
    # practice: a single unconditional `:root` block overrides the stylesheet's
    # own dark-mode values too, and the first version of the site palette put
    # #1d4ed8 inline code on a near-black page at 2.62:1. `tools/render_check.py`
    # renders both schemes and caught it.
    brand: dict[str, str] = field(default_factory=dict)
    brand_dark: dict[str, str] = field(default_factory=dict)

    def source(self, name: str) -> Source | None:
        return next((item for item in self.sources if item.name == name), None)

    def weight(self, name: str) -> float:
        found = self.source(name)
        return found.weight if found else 1.0

    def kind(self, name: str) -> str:
        found = self.source(name)
        return found.kind if found else MARKDOWN

    @property
    def paths(self) -> dict[str, str]:
        return {item.name: item.path for item in self.sources}

    @property
    def brand_css(self) -> str:
        """Overrides for `static/app.css`, both schemes, or "" for none.

        The dark block is emitted with the same `prefers-color-scheme` query the
        stylesheet uses, and after it, so it wins for the properties it names and
        leaves the rest of the dark palette alone.
        """
        if not self.brand and not self.brand_dark:
            return ""

        def block(values: dict[str, str]) -> str:
            return " ".join(f"{name}: {value};" for name, value in values.items())

        parts = []
        if self.brand:
            parts.append(f":root {{ {block(self.brand)} }}")
        if self.brand_dark:
            parts.append(
                "@media (prefers-color-scheme: dark) { :root { "
                f"{block(self.brand_dark)} }} }}"
            )
        return "\n".join(parts)
