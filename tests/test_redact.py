"""Taking the machinery's names out of an answer, in both directions.

The reason this module exists is a real reply: asked whether his answers could be
trusted, the app told a reader they were "pulled from the official … documentation (via
the search_docs and read_doc tools)". `prompts.SELF_DISCLOSURE` asks the model not to;
this is what happens when it does anyway.

The risk of a substitution pass is that it eats something. So the sweep at the bottom
runs it over every sentence of the real corpus and asserts it changes nothing — which is
also the measured claim in the module's own docstring.
"""

from __future__ import annotations

import pytest

from sage import corpus as corpus_mod
from sage import redact, retrieval, tools

NAMES = {"search_docs": "search", "read_doc": "read"}


class TestTheSwap:
    def test_the_real_answer(self):
        text, removed = redact.apply(
            "Every answer is pulled from the official RCC documentation (via the "
            "search_docs and read_doc tools) and then quoted verbatim.",
            NAMES,
        )
        assert "search_docs" not in text and "read_doc" not in text
        assert "(via the search and read tools)" in text
        assert sorted(removed) == ["read_doc", "search_docs"]

    def test_it_leaves_the_punctuation_around_the_name_alone(self):
        """Backticks, bold and a bullet all survive, because only the word is replaced."""
        text, _removed = redact.apply(
            "* **search_docs** – finds sections\n* `read_doc` – reads one in full",
            NAMES,
        )
        assert text == "* **search** – finds sections\n* `read` – reads one in full"

    def test_a_bulleted_list_of_tools_still_reads_as_english(self):
        """The reason it is a swap and not a deletion.

        Deleting the names leaves "* **** – finds sections", and a visibly broken answer
        is worse than the name was.
        """
        text, _removed = redact.apply("* **search_docs** – finds sections", NAMES)
        assert "****" not in text

    def test_case_and_repetition(self):
        text, removed = redact.apply("Search_docs first, then search_docs again.", NAMES)
        assert "search" in text and "_docs" not in text
        assert len(removed) == 2

    def test_a_longer_name_wins_over_the_one_it_starts_with(self):
        """`re` takes the first alternative that matches, so order is not incidental."""
        text, _removed = redact.apply(
            "read_doc_outline is not read_doc",
            {"read_doc": "read", "read_doc_outline": "outline"},
        )
        assert text == "outline is not read"

    def test_the_case_of_the_original_survives(self):
        """A case-insensitive match with a lowercase replacement rewrote the reader's
        prose: "Search_docs finds sections" came back opening on a lowercase word."""
        assert redact.apply("Search_docs finds sections.", NAMES)[0] == (
            "Search finds sections."
        )
        assert redact.apply("SEARCH_DOCS", NAMES)[0] == "SEARCH"
        assert redact.apply("search_docs", NAMES)[0] == "search"

    def test_a_link_target_is_left_alone(self):
        """A substitution there changes where a citation points.

        No page in this corpus has a tool's name in its path — but this module is generic,
        and a deployment whose documentation documents a function called `read_doc` is
        precisely the one that would meet it. A broken link is worse than the name was.
        """
        text = "See [the guide](docs/search_docs.md) and https://x.org/read_doc for more."
        assert redact.apply(text, NAMES) == (text, [])

    def test_but_the_same_name_in_prose_beside_a_link_still_goes(self):
        """The exemption is the address, not the sentence containing it."""
        out, removed = redact.apply(
            "I used search_docs; see [the guide](docs/search_docs.md).", NAMES
        )
        assert out == "I used search; see [the guide](docs/search_docs.md)."
        assert removed == ["search_docs"]

    def test_inline_code_is_not_an_address_and_is_swapped(self):
        assert redact.apply("I called `read_doc` next.", NAMES)[0] == (
            "I called `read` next."
        )

    def test_a_public_name_that_is_another_internal_name_does_not_cascade(self):
        """Single-pass, so a pathological label map cannot chain."""
        out, removed = redact.apply(
            "use search_docs", {"search_docs": "search", "search": "look"}
        )
        assert out == "use search"
        assert removed == ["search_docs"]

    def test_a_word_that_merely_contains_a_name_is_untouched(self):
        for text in ("my-search_docs wrapper", "presearch_docs", "read_docs"):
            assert redact.apply(text, NAMES) == (text, [])

    def test_a_name_with_no_public_form_is_left_alone(self):
        """Saying "keep this out" without saying what to put in its place is not an
        instruction this can follow, and guessing is how a sentence gets broken."""
        assert redact.apply("via glossary", {"glossary": ""}) == ("via glossary", [])

    @pytest.mark.parametrize("text", ["", "Use `sbatch` to submit a job."])
    def test_an_ordinary_answer_is_returned_unchanged(self, text):
        assert redact.apply(text, NAMES) == (text, [])

    def test_no_names_at_all_is_a_no_op(self):
        assert redact.apply("anything", {}) == ("anything", [])


class TestTheToolsetSuppliesTheNames:
    """Derived from the tools, so a third tool is covered by giving it a `label`."""

    def toolset(self, names=tools.DEFAULT_TOOLS):
        index = retrieval.Index(corpus_mod.Corpus())
        return tools.build(index, names=names)

    def test_the_two_shipped_tools(self):
        assert self.toolset().public_names == {"search_docs": "search", "read_doc": "read"}

    def test_a_tool_with_no_label_is_not_substituted(self):
        class Glossary:
            name = "glossary"
            label = ""
            schema: dict = {}

            def run(self, arguments, record):
                return ""

        tools.factories.register("glossary_test", lambda *_args: Glossary())
        try:
            built = self.toolset(names=(*tools.DEFAULT_TOOLS, "glossary_test"))
            assert "glossary" not in built.public_names
        finally:
            tools.factories.remove("glossary_test")


class TestItChangesNothingAboutAnOrdinaryAnswer:
    """The measured claim in `sage/redact.py`'s docstring, held as a test.

    A substitution pass over every answer the app produces has to be a no-op on the ones
    that are about the documentation, and "no occurrences in 173 recorded answers" is
    evidence that goes stale. This is the version that cannot.
    """

    def test_no_sentence_of_the_corpus_is_touched(self, real_corpus):
        touched = []
        for chunk in real_corpus.chunks:
            text, removed = redact.apply(chunk.text, NAMES)
            if removed or text != chunk.text:
                touched.append(chunk.id)
        assert not touched, f"{len(touched)} chunks were rewritten: {touched[:3]}"
