import pytest

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


def test_unresolvable_targets_fall_back_to_the_guide_root():
    out = links.fix_links("[mystery](docs/nope/missing.md)", CORPUS)
    assert out == f"[mystery]({config.DOCS_BASE_URL})"


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


class TestSourceFooter:
    """The answer said `Sources: A, B`; the app then drew a Sources strip saying the
    same two, three lines below. The first two cases here are the two that were
    photographed — one list of bare titles, one of links."""

    @pytest.mark.parametrize(
        "footer",
        [
            # Photographed: bare titles, matching the chip labels word for word.
            "Sources: Storage System Layout › Quotas, Storage System Layout",
            # Photographed: the same thing as links.
            "Sources: [How do I check my allocation?](docs/a.md), "
            "[How do I review usage?](docs/b.md)",
            "**Sources:**\n- [A](docs/a.md)\n- [B](docs/b.md)",
            "**Sources**: [A](docs/a.md)",
            "## References\n[A](docs/a.md)",
            "Citations: [A](docs/a.md)",
            "Source: [A](docs/a.md)\n",
            "## Sources",
        ],
    )
    def test_a_trailing_citation_list_is_removed(self, footer):
        answer = "Quota on /project2 is 100 GB."
        assert links.strip_source_footer(f"{answer}\n\n{footer}") == answer

    def test_the_rule_a_model_draws_above_it_goes_too(self):
        out = links.strip_source_footer("Answer.\n\n---\n\nSources: [A](docs/a.md)")
        assert out == "Answer."

    @pytest.mark.parametrize(
        ("answer", "why"),
        [
            (
                "Sources of variation include node type and network load.",
                "a sentence that opens with the word is not a footer",
            ),
            (
                "Submit with `sbatch`. See [Batch jobs](docs/slurm/sbatch.md) for flags.",
                "inline citations are the format this app asks for",
            ),
            (
                "Steps:\n\n- Load the module\n- Submit the job\n- Watch the queue",
                "a trailing list is not automatically a citation list",
            ),
            (
                "References:\n\n- Run `module load python`\n- Then `sbatch job.sh`",
                "commands under a mislabelled heading are still the answer",
            ),
            (
                "Sources: [A](docs/a.md)",
                "an answer that is only a footer would otherwise render empty",
            ),
            ("", "no text at all"),
        ],
    )
    def test_what_must_survive(self, answer, why):
        assert links.strip_source_footer(answer) == answer, why

    def test_a_heading_mid_answer_is_not_a_footer(self):
        """The cut only ever runs to the end of the answer. A `Sources` label with real
        content after it means the label is not a footer, and nothing is removed."""
        answer = (
            "Sources:\n- [A](docs/a.md)\n\n## Next steps\nSubmit the job and watch it."
        )
        assert links.strip_source_footer(answer) == answer
