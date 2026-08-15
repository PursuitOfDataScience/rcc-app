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
# Split, because the two are not the same problem. A page indexed twice wastes a result
# slot and is fixable upstream; identical text under two different titles is shared
# boilerplate that must keep its own citation — deduplicating the index would answer a
# Booth question with a link to the BFI page.
MAXIMUM_SAME_PAGE_TWICE = 2          # measured 2 (web/midway2 under two URLs)
MAXIMUM_SHARED_BOILERPLATE = 2       # measured 2 (bfi.md and booth.md)
MAXIMUM_NEAR_DUPLICATE_PAIRS = 0     # measured 0
MINIMUM_PAGES_FINDABLE_BY_TITLE = 0.92   # measured 0.939 (7 of 114 are not)


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

    def test_every_url_is_a_usable_web_address(self, measured):
        """A citation is the one string in this app that becomes an `href`.

        "Has a URL" was all that was asked. A space in it, two fragment markers, no
        scheme, a control character — each is a link that lands nowhere, and nothing
        downstream notices: `anchor_check.py` validates against the live site but is
        network-bound and out of the suite.
        """
        bad = measured["malformed_urls"]
        assert not bad, f"{len(bad)} unusable citation URLs: {bad[:3]}"

    def test_every_source_the_profile_declares_contributed(self, measured, profile):
        """Derived from the profile rather than a hardcoded pair.

        `corpus.build` skips a source whose `reader` nothing registered — deliberately, so
        one misconfigured tree cannot take a multi-source deployment down. The cost is that
        the app boots looking healthy with a whole tree missing, and CI's own check only
        asserts that *some* chunks exist. A third source added to the profile is now
        required to contribute the day it is added, rather than the day somebody notices.
        """
        declared = {source.name for source in profile.sources}
        assert set(measured["sources"]) == declared
        for name, row in measured["sources"].items():
            assert row["chunks"] > 0, f"{name} indexed nothing"

    def test_no_profile_field_is_left_as_a_literal_brace(self, measured):
        """`prompts.render` substitutes six names and leaves the rest alone by design.

        The cost is silent: a profile author writing `{corpus_name}` — a documented field —
        sends the braces to the model. Both shipped prompts are clean; this is the check a
        second deployment needs, and it only fails on a placeholder that names a real field.
        """
        missed = [
            row["placeholder"] for row in measured["unrendered_placeholders"]
            if row["is_a_profile_field"]
        ]
        assert not missed, (
            "these name profile fields but reach the model as literal text: "
            + ", ".join(f"{{{name}}}" for name in missed)
        )

    def test_every_registry_name_the_profile_uses_exists(self, measured):
        """A typo caught as one line with the valid names beside it.

        A bad `links` scheme or `retrieval.engine` raises at boot with the registry's own
        list, which is right. A bad `reader` is skipped with a log line, so a single-source
        deployment boots and answers every question with "the documentation does not appear
        to cover it" — this app's worst state, and the one hardest to notice.
        """
        wrong = measured["unregistered_names"]
        assert not wrong, "names nothing registered: " + "; ".join(
            f"{row['kind']} {row['name']!r} at {row['where']} "
            f"(registered: {', '.join(row['registered'])})"
            for row in wrong
        )


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


class TestPagesThatYieldNothing:
    """Asked by outcome, not by file size, and read off the corpus rather than the disk.

    A page excluded on purpose never becomes a Document; a page that was read and produced
    nothing becomes one with no chunks. A first version of this walked the tree and
    reported all twelve deliberate exclusions — the publication dumps and the radiology
    scrape — as problems.
    """

    def test_only_the_known_empty_page_yields_nothing(self, measured):
        assert measured["indexing_nothing"] == [
            "docs/data_transfer/cloud/rclone.md"
        ], measured["indexing_nothing"]

    def test_deliberate_exclusions_are_not_reported(self, measured):
        reported = " ".join(measured["indexing_nothing"])
        for excluded in ("publications", "learn-radiology", "vislab"):
            assert excluded not in reported


class TestDuplication:
    def test_no_new_page_is_indexed_twice(self, measured):
        groups = measured["duplicates"]["same_page_twice"]
        assert len(groups) <= MAXIMUM_SAME_PAGE_TWICE, (
            f"{len(groups)} pages indexed twice: {groups[:3]}"
        )

    def test_shared_boilerplate_is_held_at_the_measured_count(self, measured):
        groups = measured["duplicates"]["shared_boilerplate"]
        assert len(groups) <= MAXIMUM_SHARED_BOILERPLATE, (
            f"{len(groups)} boilerplate groups: {groups[:3]}"
        )

    def test_the_two_kinds_are_told_apart(self, measured):
        """The classification is the point; a single count reads as four bugs."""
        duplicated = measured["duplicates"]
        assert len(duplicated["same_page_twice"]) + len(
            duplicated["shared_boilerplate"]
        ) == len(duplicated["exact_groups"])

    def test_near_duplicates_are_held_at_the_measured_count(self, measured):
        near = measured["duplicates"]["near"]
        assert len(near) <= MAXIMUM_NEAR_DUPLICATE_PAIRS, (
            f"{len(near)} near-duplicate pairs: {near[:3]}"
        )


class TestFindability:
    def test_most_pages_are_retrievable_by_their_own_title(self, measured):
        rate = measured["self_reachability"]["rate"]
        assert rate >= MINIMUM_PAGES_FINDABLE_BY_TITLE, (
            f"only {rate:.1%} of pages can be found by their own title"
        )

    def test_the_ones_that_are_not_are_the_ones_we_know_about(self, measured):
        """Two of the seven are worth a reader's attention and neither is fixable here.

        `singularity.md` is titled `# Modules` upstream, so every citation chip for the
        Singularity page reads "Modules — …"; the fix is in the User Guide. And
        `MidwayGeoSpatial` retrieves *nothing* for its own title, because a CamelCase
        compound is one token the page's own prose never uses — splitting CamelCase in the
        tokenizer would touch every score in the index to rescue one page, which is a
        worse trade than the page.
        """
        pages = {row["page"] for row in measured["self_reachability"]["unreachable"]}
        assert "docs/software/apps-and-envs/singularity.md" in pages
        assert "docs/tutorials/gis/MidwayGeoSpatial.md" in pages
        titles = {
            row["page"]: row["title"]
            for row in measured["self_reachability"]["unreachable"]
        }
        assert titles["docs/software/apps-and-envs/singularity.md"] == "Modules"


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
