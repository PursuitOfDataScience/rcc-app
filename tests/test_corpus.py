from sage import config
from sage import corpus as corpus_mod

DOC = """# Batch jobs

Intro paragraph that is long enough to survive the minimum-chunk filter easily.

## `.sbatch` scripts

Write a script.

### Submitting a script

Run `sbatch script.sbatch` to submit it.

## Managing jobs

Use squeue.
"""


def test_sections_become_separate_chunks_with_anchors():
    _document, chunks = corpus_mod.chunk_markdown("docs", "slurm/sbatch.md", DOC)
    ids = [chunk.id for chunk in chunks]
    assert "docs/slurm/sbatch.md#sbatch-scripts" in ids
    assert "docs/slurm/sbatch.md#submitting-a-script" in ids
    assert "docs/slurm/sbatch.md#managing-jobs" in ids


def test_breadcrumb_carries_the_ancestor_trail_without_repeating_the_title():
    _document, chunks = corpus_mod.chunk_markdown("docs", "slurm/sbatch.md", DOC)
    deep = next(c for c in chunks if c.id.endswith("#submitting-a-script"))
    assert deep.breadcrumb == "Batch jobs › .sbatch scripts › Submitting a script"
    top = next(c for c in chunks if c.id.endswith("#batch-jobs"))
    assert top.breadcrumb == "Batch jobs"


def test_citation_url_deep_links_to_the_section():
    _document, chunks = corpus_mod.chunk_markdown("docs", "slurm/sbatch.md", DOC)
    deep = next(c for c in chunks if c.id.endswith("#managing-jobs"))
    assert deep.url == (
        "https://rcc-uchicago.github.io/user-guide/slurm/sbatch/#managing-jobs"
    )


def test_index_page_maps_to_the_site_root():
    assert corpus_mod.docs_url("index.md") == config.DOCS_BASE_URL


def test_oversized_sections_split_without_breaking_fences():
    body = "\n\n".join(f"Paragraph number {n} with some filler text." for n in range(400))
    source = f"# Big\n\n## Section\n\n```bash\necho keep-together\n```\n\n{body}\n"
    _document, chunks = corpus_mod.chunk_markdown("docs", "big.md", source)
    section_chunks = [c for c in chunks if c.id.startswith("docs/big.md#section")]
    assert len(section_chunks) > 1
    assert all(len(c.text) <= config.MAX_CHUNK_CHARS * 1.2 for c in section_chunks)
    fence_owner = [c for c in section_chunks if "echo keep-together" in c.text]
    assert len(fence_owner) == 1
    assert fence_owner[0].text.count("```") == 2


def test_duplicate_headings_get_distinct_ids():
    source = "# T\n\n## Notes\n\nFirst body here, long enough.\n\n## Notes\n\nSecond body.\n"
    _document, chunks = corpus_mod.chunk_markdown("docs", "d.md", source)
    ids = [c.id for c in chunks if "notes" in c.id]
    assert len(ids) == len(set(ids)) == 2


def test_scraped_pages_window_and_keep_their_real_url():
    raw = (
        "URL: https://beag3.rcc.uchicago.edu/software\n"
        "Title: Software | Beagle3 - RCC\n"
        "=================================\n"
        + "\n".join(f"Sentence {n} about the Beagle3 software stack." for n in range(200))
    )
    document, chunks = corpus_mod.chunk_scraped("web", "software.txt", raw)
    assert document.url == "https://beag3.rcc.uchicago.edu/software"
    assert document.title == "Software"
    assert len(chunks) > 1
    assert all(c.url == document.url for c in chunks)


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

    def test_chunk_ids_are_unique(self, real_corpus):
        ids = [c.id for c in real_corpus.chunks]
        assert len(ids) == len(set(ids))

    def test_no_mkdocs_syntax_survives_into_chunk_text(self, real_corpus):
        joined = "\n".join(c.text for c in real_corpus.chunks)
        assert "{:target" not in joined
        assert "!!! note" not in joined
        assert "{: class" not in joined
