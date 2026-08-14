"""Axis C, gated: the corpus properties the app depends on and cannot check at runtime.

The app's ceiling is its documents, and three of these would break answers silently. An
id `search_docs` advertises but `read_doc` cannot resolve is a dead end the model has to
recover from mid-turn. A chunk with no URL is a citation with nothing to click. A new
empty document is a topic that quietly stops being answerable.

Counts rather than absences where a count is the honest bound: the User Guide and the
scraped site overlap by construction, so duplicates cannot be forbidden — only held at
the number measured, so a new one is visible.
"""

from __future__ import annotations

import pytest

from evals import corpus_health

# Measured on the tree that introduced this file.
KNOWN_EMPTY = {
    # 0 bytes upstream, so no rclone question is answerable at all. The retrieval eval
    # has carried this as a comment since it was written.
    "docs/data_transfer/cloud/rclone.md",
    # 188 bytes of boilerplate from the scrape.
    "web/takecourse.txt",
}
MAXIMUM_EXACT_DUPLICATE_GROUPS = 4   # measured 4
MAXIMUM_NEAR_DUPLICATE_PAIRS = 0     # measured 0


@pytest.fixture(scope="module")
def measured(real_corpus, real_index):
    return corpus_health.measure(real_corpus, real_index)


class TestIntegrity:
    def test_every_advertised_id_resolves(self, measured):
        """`read_doc` resolves against the in-memory corpus and nothing else."""
        broken = measured["unresolvable_ids"]
        assert not broken, f"{len(broken)} ids do not resolve: {broken[:5]}"

    def test_every_chunk_has_a_url(self, measured):
        urlless = measured["chunks_without_url"]
        assert not urlless, f"{len(urlless)} chunks cannot be cited: {urlless[:5]}"

    def test_both_sources_are_indexed(self, measured):
        assert set(measured["sources"]) == {"docs", "web"}
        for name, row in measured["sources"].items():
            assert row["chunks"] > 0, f"{name} indexed nothing"


class TestWhatTheCorpusCannotAnswer:
    def test_no_new_empty_document(self, measured):
        found = {f"{row['source']}/{row['path']}" for row in measured["empty_documents"]}
        assert found <= KNOWN_EMPTY, (
            "documents that have gone empty: " + "; ".join(sorted(found - KNOWN_EMPTY))
        )

    def test_a_document_that_filled_up_should_be_taken_off_the_list(self, measured):
        """The other direction, so the list cannot outlive the problem it records."""
        found = {f"{row['source']}/{row['path']}" for row in measured["empty_documents"]}
        filled = KNOWN_EMPTY - found
        assert not filled, (
            "no longer empty, remove from KNOWN_EMPTY: " + "; ".join(sorted(filled))
        )


class TestDuplication:
    def test_exact_duplicates_are_held_at_the_measured_count(self, measured):
        groups = measured["duplicates"]["exact_groups"]
        assert len(groups) <= MAXIMUM_EXACT_DUPLICATE_GROUPS, (
            f"{len(groups)} identical-section groups: {groups[:3]}"
        )

    def test_near_duplicates_are_held_at_the_measured_count(self, measured):
        near = measured["duplicates"]["near"]
        assert len(near) <= MAXIMUM_NEAR_DUPLICATE_PAIRS, (
            f"{len(near)} near-duplicate pairs: {near[:3]}"
        )


class TestAdvertisedTopics:
    def test_every_topic_retrieves_something(self, measured):
        """`identity.topics` is what `search_docs` tells the model it covers."""
        empty = [row["topic"] for row in measured["topics"] if not row["top_page"]]
        assert not empty, "topics with no matching section: " + "; ".join(empty)

    @pytest.mark.xfail(reason="a one-word query scores below the floor", strict=False)
    def test_every_topic_is_answerable_without_a_caveat(self, measured):
        """Known, and worth keeping visible: a reader who types one word gets the caveat.

        `Slurm`, `storage` and `policy` score 11–19 against a floor of 20, because the
        score is an unnormalised sum and a single common term earns very little of it.
        Not a missing topic — a property of short queries. An xpass here means short
        queries have been normalised, which would be worth noticing.
        """
        caveated = [row["topic"] for row in measured["topics"] if not row["confident"]]
        assert not caveated, "caveated topics: " + "; ".join(caveated)
