from sage import config
from sage import corpus as corpus_mod
from sage.corpus import urls
from sage.profile import Source

DOC = """# Batch jobs

Intro paragraph that is long enough to survive the minimum-chunk filter easily.

## `.sbatch` scripts

Write a script.

### Submitting a script

Run `sbatch script.sbatch` to submit it.

## Managing jobs

Use squeue.
"""


def test_sections_become_separate_chunks_with_anchors(docs_source):
    _document, chunks = corpus_mod.read(docs_source, "slurm/sbatch.md", DOC)
    ids = [chunk.id for chunk in chunks]
    assert "docs/slurm/sbatch.md#sbatch-scripts" in ids
    assert "docs/slurm/sbatch.md#submitting-a-script" in ids
    assert "docs/slurm/sbatch.md#managing-jobs" in ids


def test_breadcrumb_carries_the_ancestor_trail_without_repeating_the_title(docs_source):
    _document, chunks = corpus_mod.read(docs_source, "slurm/sbatch.md", DOC)
    deep = next(c for c in chunks if c.id.endswith("#submitting-a-script"))
    assert deep.breadcrumb == "Batch jobs › .sbatch scripts › Submitting a script"
    top = next(c for c in chunks if c.id.endswith("#batch-jobs"))
    assert top.breadcrumb == "Batch jobs"


def test_citation_url_deep_links_to_the_section(docs_source):
    _document, chunks = corpus_mod.read(docs_source, "slurm/sbatch.md", DOC)
    deep = next(c for c in chunks if c.id.endswith("#managing-jobs"))
    assert deep.url == (
        "https://docs.rcc.uchicago.edu/slurm/sbatch/#managing-jobs"
    )


def test_index_page_maps_to_the_site_root(docs_source):
    assert corpus_mod.url_for(docs_source, "index.md") == docs_source.base_url


class TestUrlSchemes:
    """Where a document is published is a property of the tree it came from.

    It used to be `if source == "docs"` inside the chunker, which is why a second
    corpus could not be added without editing the chunker. Each scheme is a function
    now, registered under the name a source declares.
    """

    def test_mkdocs_publishes_a_page_as_a_directory(self, docs_source):
        assert corpus_mod.url_for(docs_source, "slurm/sbatch.md", "gpu-jobs") == (
            "https://docs.rcc.uchicago.edu/slurm/sbatch/#gpu-jobs"
        )

    def test_mkdocs_publishes_a_nested_index_as_its_directory(self, docs_source):
        """`software/index.md` at `software/index/` is a 404, and it was: 16 sections
        across two index pages pointed at a dead page."""
        assert corpus_mod.url_for(docs_source, "software/index.md") == (
            "https://docs.rcc.uchicago.edu/software/"
        )

    def test_a_directly_served_tree_keeps_the_path(self):
        source = Source(
            name="notes", path="./notes", links="direct", base_url="https://x.test/"
        )
        assert corpus_mod.url_for(source, "a/b.md", "top") == "https://x.test/a/b.md#top"

    def test_a_private_corpus_has_no_url_rather_than_a_wrong_one(self):
        source = Source(name="private", path="./private", links="none")
        assert corpus_mod.url_for(source, "a/b.md", "top") == ""

    def test_an_unregistered_scheme_says_so(self, docs_source):
        import pytest

        with pytest.raises(LookupError, match="Unknown url scheme"):
            urls.build(Source(name="x", path=".", links="carrier-pigeon"), "a.md")


def test_oversized_sections_split_without_breaking_fences(docs_source):
    body = "\n\n".join(f"Paragraph number {n} with some filler text." for n in range(400))
    source = f"# Big\n\n## Section\n\n```bash\necho keep-together\n```\n\n{body}\n"
    _document, chunks = corpus_mod.read(docs_source, "big.md", source)
    section_chunks = [c for c in chunks if c.id.startswith("docs/big.md#section")]
    assert len(section_chunks) > 1
    assert all(len(c.text) <= config.MAX_CHUNK_CHARS * 1.2 for c in section_chunks)
    fence_owner = [c for c in section_chunks if "echo keep-together" in c.text]
    assert len(fence_owner) == 1
    assert fence_owner[0].text.count("```") == 2


def test_the_page_title_is_its_h1_and_not_its_first_subsection(docs_source):
    """Five pages in the bundled guide have no H1, and the title scan took whatever
    heading came first — so `software/apps-and-envs/r.md` was cited as "Table of
    Contents" and `software/index.md` as "Private Software".

    On this page the borrowed title is also a real section, so the citation strip named
    the page "Step 1. From Data Provider to SDE Virtual Desktop" and Related then
    offered a section of the same name: one name, two links, no way to tell them apart.
    """
    source = (
        "Transferring data from a Data Provider Server to the SDE3 HPC system involves "
        "a two-step process, using the Secure Data Enclave Virtual Desktop as an "
        "intermediate staging area — long enough to be indexed as the page's intro.\n\n"
        "## Step 1. From Data Provider to SDE Virtual Desktop\n\nLog in and copy.\n"
    )
    document, chunks = corpus_mod.read(
        docs_source, "tutorials/sde3/data-transfer.md", source
    )
    assert document.title == "Data transfer"
    assert {chunk.heading for chunk in chunks} == {
        "Data transfer",
        "Step 1. From Data Provider to SDE Virtual Desktop",
    }


def test_a_heading_inside_a_code_fence_is_not_the_page_title(docs_source):
    """`# Install renv if not already installed` is an R comment, and the R page has
    five of them. The old scan was not fence-aware and was saved from them only by a
    40-line window — which is also what hid the page's real problem, so widening the
    window to look for an H1 would have found a comment instead.
    """
    source = (
        "## Table of Contents\n\nA list of what is on this page, long enough to keep.\n\n"
        "```r\n# Install renv if not already installed\ninstall.packages('renv')\n```\n"
    )
    document, _chunks = corpus_mod.read(
        docs_source, "software/apps-and-envs/r.md", source
    )
    assert document.title == "R"


def test_an_index_page_is_titled_after_the_directory_it_indexes(docs_source):
    """the mkdocs URL scheme already publishes `software/index.md` at `software/`. "Index" names
    no page a reader could recognise in a citation."""
    source = "## Private Software\n\nBody text long enough to be kept as a chunk.\n"
    document, _chunks = corpus_mod.read(docs_source, "software/index.md", source)
    assert document.title == "Software"


def test_duplicate_headings_get_distinct_ids(docs_source):
    source = "# T\n\n## Notes\n\nFirst body here, long enough.\n\n## Notes\n\nSecond body.\n"
    _document, chunks = corpus_mod.read(docs_source, "d.md", source)
    ids = [c.id for c in chunks if "notes" in c.id]
    assert len(ids) == len(set(ids)) == 2


def test_scraped_pages_window_and_keep_their_real_url(web_source):
    raw = (
        "URL: https://beag3.rcc.uchicago.edu/software\n"
        "Title: Software | Beagle3 - RCC\n"
        "=================================\n"
        + "\n".join(f"Sentence {n} about the Beagle3 software stack." for n in range(200))
    )
    document, chunks = corpus_mod.read(web_source, "software.txt", raw)
    assert document.url == "https://beag3.rcc.uchicago.edu/software"
    assert document.title == "Software"
    assert len(chunks) > 1
    assert all(c.url == document.url for c in chunks)


def test_a_window_is_not_a_section_named_part_2(web_source):
    """`(part 3)` was bookkeeping in a section heading's clothes.

    A scraped page has no headings, so a window of one is not a section — it is the
    same page, cut for indexing, and every cut carries the page's own URL. Naming the
    cuts put the index's private arithmetic in front of the reader: the Sources strip
    said `Our Team — Our Team (part 3)`, and Related offered parts 2, 3 and 4 as three
    leads that were one link, the very link listed above them under Sources.
    """
    raw = (
        "URL: https://rcc.uchicago.edu/about-rcc/our-team\n"
        "Title: Our Team | RCC\n"
        "=====================\n"
        + "\n".join(f"Staff member {n} supports research computing." for n in range(200))
    )
    _document, chunks = corpus_mod.read(web_source, "about-rcc_our-team.txt", raw)

    assert len(chunks) > 3
    assert {chunk.heading for chunk in chunks} == {"Our Team"}
    assert {chunk.label for chunk in chunks} == {"Our Team"}
    # The window number is kept where it is needed and nowhere else: in the id, which
    # is what `read_doc` is handed to fetch one window in full.
    assert len({chunk.id for chunk in chunks}) == len(chunks)


class TestRealCorpus:
    def test_the_whole_sbatch_page_is_reachable(self, real_corpus):
        """The old 15k truncation dropped 62% of this page."""
        chunks = [c for c in real_corpus.chunks if c.path == "slurm/sbatch.md"]
        assert len(chunks) > 10
        # Normalization removes mkdocs syntax, so expect slightly less than the raw
        # 39,741 bytes — but far more than the old 15,000-character ceiling.
        assert sum(len(c.text) for c in chunks) > 30000

    def test_off_topic_hosts_are_excluded(self, real_corpus):
        paths = {document.path for document in real_corpus.documents.values()}
        assert "pirads.txt" not in paths
        assert "mpMRI.txt" not in paths
        assert "grants-publications_list-of-publications.txt" not in paths

    def test_rcc_documentation_is_still_indexed(self, real_corpus):
        paths = {document.path for document in real_corpus.documents.values()}
        for expected in ("slurm/sbatch.md", "storage/main.md", "faqs.txt"):
            assert expected in paths

    def test_every_chunk_has_an_absolute_citation_url(self, real_corpus):
        assert all(c.url.startswith("https://") for c in real_corpus.chunks)

    def test_no_citation_label_advertises_a_window_number(self, real_corpus):
        """40 of the 83 scraped chunks were named after the cut that made them."""
        named = [c.id for c in real_corpus.chunks if "(part " in c.label]
        assert not named, f"{len(named)} chunks named after their window: {named[:3]}"

    def test_chunk_ids_are_unique(self, real_corpus):
        ids = [c.id for c in real_corpus.chunks]
        assert len(ids) == len(set(ids))

    def test_no_mkdocs_syntax_survives_into_chunk_text(self, real_corpus):
        joined = "\n".join(c.text for c in real_corpus.chunks)
        assert "{:target" not in joined
        assert "!!! note" not in joined
        assert "{: class" not in joined
