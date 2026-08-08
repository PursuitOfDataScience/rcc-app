from sage import config, links
from sage.corpus import Chunk, Corpus, Document


def build() -> Corpus:
    chunks = [
        Chunk(
            id="docs/slurm/sbatch.md#gpu-jobs",
            source="docs",
            path="slurm/sbatch.md",
            doc_title="Batch jobs",
            heading="GPU jobs",
            breadcrumb="Batch jobs › GPU jobs",
            text="body",
            url="https://rcc-uchicago.github.io/user-guide/slurm/sbatch/#gpu-jobs",
        ),
        Chunk(
            id="web/faqs.txt#1",
            source="web",
            path="faqs.txt",
            doc_title="FAQs",
            heading="FAQs",
            breadcrumb="FAQs",
            text="body",
            url="https://cloud-skyway.rcc.uchicago.edu/faqs",
        ),
    ]
    documents = {
        "docs/slurm/sbatch.md": Document(
            "docs",
            "slurm/sbatch.md",
            "Batch jobs",
            "https://rcc-uchicago.github.io/user-guide/slurm/sbatch/",
            "body",
        ),
        "web/faqs.txt": Document(
            "web", "faqs.txt", "FAQs", "https://cloud-skyway.rcc.uchicago.edu/faqs", "body"
        ),
    }
    return Corpus(chunks=chunks, documents=documents)


CORPUS = build()


def test_scraped_pages_cite_their_own_host():
    """These used to be redirected to the Midway user guide root."""
    out = links.fix_links("See the [Skyway FAQ](web/faqs.txt).", CORPUS)
    assert "https://cloud-skyway.rcc.uchicago.edu/faqs" in out


def test_chunk_ids_resolve_to_a_deep_link():
    out = links.fix_links("[GPU jobs](docs/slurm/sbatch.md#gpu-jobs)", CORPUS)
    assert out == (
        "[GPU jobs](https://rcc-uchicago.github.io/user-guide/slurm/sbatch/#gpu-jobs)"
    )


def test_page_paths_resolve_without_an_anchor():
    out = links.fix_links("[Batch jobs](docs/slurm/sbatch.md)", CORPUS)
    assert out == "[Batch jobs](https://rcc-uchicago.github.io/user-guide/slurm/sbatch/)"


def test_unknown_anchor_still_produces_a_page_link():
    out = links.fix_links("[x](docs/slurm/sbatch.md#not-a-real-anchor)", CORPUS)
    assert "slurm/sbatch/#not-a-real-anchor" in out


def test_bare_and_relative_filenames_resolve_by_suffix():
    assert "slurm/sbatch/" in links.fix_links("[a](sbatch.md)", CORPUS)
    assert "slurm/sbatch/" in links.fix_links("[a](./slurm/sbatch.md)", CORPUS)


def test_external_links_are_left_alone():
    text = "[RCC](https://rcc.uchicago.edu/) and [mail](mailto:help@rcc.uchicago.edu)"
    assert links.fix_links(text, CORPUS) == text


def test_in_page_anchors_are_unlinked():
    assert links.fix_links("jump to [that part](#later)", CORPUS) == "jump to that part"


def test_unresolvable_targets_are_unlinked_not_pointed_at_the_root():
    """This asserted the opposite, and the opposite was a bug.

    `fix_links`' own docstring said "unlink what cannot be resolved" while the code
    sent every unresolvable target to `DOCS_BASE_URL`. The test locked in the code
    rather than the promise, so a reader clicking a citation landed on the front
    page of the User Guide believing they had reached the cited section — a
    confident, wrong citation, indistinguishable from a working one by looking.
    """
    out = links.fix_links("[mystery](docs/nope/missing.md)", CORPUS)
    assert out == "mystery"
    assert config.DOCS_BASE_URL not in out


def test_unresolved_targets_can_be_counted():
    """A model inventing a path is a generation defect worth seeing in the logs,
    not just something the renderer quietly tidies away."""
    missing = links.unresolved(
        "[a](docs/slurm/sbatch.md) and [b](docs/nope/missing.md)", CORPUS
    )
    assert missing == ["docs/nope/missing.md"]

    assert links.unresolved("[RCC](https://rcc.uchicago.edu/)", CORPUS) == []


def test_leaked_kramdown_attributes_are_stripped_from_answers():
    out = links.fix_links("[RCC](https://rcc.uchicago.edu/){:target='_blank'}", CORPUS)
    assert "{:target" not in out


def test_titled_links_are_handled():
    out = links.fix_links('[a](docs/slurm/sbatch.md "Batch jobs")', CORPUS)
    assert "slurm/sbatch/" in out


def test_plain_prose_is_untouched():
    text = "Run `sbatch job.sbatch` and check with `squeue -u $USER`."
    assert links.fix_links(text, CORPUS) == text


def test_every_link_in_a_real_answer_resolves(real_corpus):
    answer = (
        "Submit with sbatch — see [Batch jobs](docs/slurm/sbatch.md) and "
        "[Quotas](docs/storage/main.md#quotas)."
    )
    out = links.fix_links(answer, real_corpus)
    assert "docs/" not in out
    assert out.count("https://") == 2
