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


def test_an_unresolvable_target_is_not_linked_at_all():
    """It used to become a live link to the guide root, indistinguishable by eye from
    a citation that worked, and landing the reader on the front page of the user guide
    while they believed they had reached the cited section."""
    out = links.fix_links("[mystery](docs/nope/missing.md)", CORPUS)
    assert out == "mystery"
    assert config.DOCS_BASE_URL not in out


def test_invented_paths_are_reported_not_only_hidden():
    text = "See [a](docs/slurm/sbatch.md) and [b](docs/nope/missing.md)."
    assert links.unresolved(text, CORPUS) == ["docs/nope/missing.md"]


def test_external_and_anchor_targets_are_not_counted_as_invented():
    text = "[RCC](https://rcc.uchicago.edu/) and [up there](#top)"
    assert links.unresolved(text, CORPUS) == []


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


class TestUnlabelledSourceFooter:
    """The second screenshot. Told not to write a "Sources" list, the model dropped
    the word and left the links: two of them, on their own line, directly above the
    strip listing the same two pages. Shape alone is too thin to cut on here, so
    these come off only when every link is provably already a chip."""

    @staticmethod
    def two_chunks(corpus):
        chunks = [chunk for chunk in corpus.chunks if "storage" in chunk.path][:2]
        sources = [
            {"id": c.id, "label": c.label, "url": c.url, "source": c.source}
            for c in chunks
        ]
        return chunks, sources

    def test_a_bare_paragraph_of_links_is_removed(self, real_corpus):
        chunks, sources = self.two_chunks(real_corpus)
        answer = (
            "Run `rcchelp usage` to see what is left.\n\n"
            f"[{chunks[0].heading}]({chunks[0].id}) [{chunks[1].heading}]({chunks[1].id})"
        )
        out = links.strip_source_footer(answer, real_corpus, sources)
        assert out == "Run `rcchelp usage` to see what is left."

    def test_the_whole_list_goes_not_its_last_line(self, real_corpus):
        """Cutting one line off a bulleted list leaves a half-eaten list, which
        reads worse than the duplicate it was meant to remove."""
        chunks, sources = self.two_chunks(real_corpus)
        answer = f"Answer.\n\n- [a]({chunks[0].id})\n- [b]({chunks[1].id})"
        assert links.strip_source_footer(answer, real_corpus, sources) == "Answer."

    def test_a_link_the_strip_is_not_showing_survives(self, real_corpus):
        """The gate is "the reader loses nothing", not "this looks like a footer"."""
        chunks, sources = self.two_chunks(real_corpus)
        elsewhere = next(c for c in real_corpus.chunks if "slurm" in c.path)
        answer = f"Answer.\n\n- [a]({chunks[0].id})\n- [b]({elsewhere.id})"
        assert links.strip_source_footer(answer, real_corpus, sources) == answer

    def test_links_a_sentence_introduces_are_the_answer(self, real_corpus):
        """A colon above them means they are the object of a sentence. Cutting them
        leaves the sentence pointing at nothing."""
        chunks, sources = self.two_chunks(real_corpus)
        answer = (
            "Here is what the documentation covers:\n\n"
            f"- [a]({chunks[0].id})\n- [b]({chunks[1].id})"
        )
        assert links.strip_source_footer(answer, real_corpus, sources) == answer

    def test_prose_that_ends_on_links_is_untouched(self, real_corpus):
        chunks, sources = self.two_chunks(real_corpus)
        answer = (
            f"That's it. For full details, see [GPU jobs]({chunks[0].id}) and "
            f"[PyTorch]({chunks[1].id})."
        )
        assert links.strip_source_footer(answer, real_corpus, sources) == answer

    def test_nothing_is_cut_without_a_strip_to_cut_against(self, real_corpus):
        """No `sources` means the app is drawing no chips, so the footer is the only
        citation the reader has."""
        chunks, _ = self.two_chunks(real_corpus)
        answer = f"Answer.\n\nSources: [a]({chunks[0].id})"
        assert links.strip_source_footer(answer, real_corpus, []) == answer

    def test_shape_alone_does_not_cut_it(self, real_corpus):
        """Called without the strip's contents — as the module's own tests above do
        — an unlabelled list cannot be proven duplicate and stays."""
        chunks, _ = self.two_chunks(real_corpus)
        answer = f"Answer.\n\n[a]({chunks[0].id}) [b]({chunks[1].id})"
        assert links.strip_source_footer(answer) == answer


class TestCitationSentenceFooter:
    """The third shape, and the one that arrived after the prompt was told not to write
    the word "Sources": a footer with grammar. "Cited from A and B." is a sentence, so
    neither the label rule nor the bare-links rule could see it."""

    @staticmethod
    def two_chunks(corpus):
        chunks = [chunk for chunk in corpus.chunks if "storage" in chunk.path][:2]
        sources = [
            {"id": c.id, "label": c.label, "url": c.url, "source": c.source}
            for c in chunks
        ]
        return chunks, sources

    @pytest.mark.parametrize(
        "closing",
        [
            "Cited from [a]({a}) and [b]({b}).",
            "Cited from [a]({a}).",
            "Based on [a]({a}) and [b]({b}).",
            "Sourced from [a]({a}), [b]({b}).",
            "According to [a]({a}) and [b]({b}).",
        ],
    )
    def test_a_closing_citation_sentence_is_removed(self, real_corpus, closing):
        chunks, sources = self.two_chunks(real_corpus)
        answer = "Run `rcchelp balance` to see what is left."
        text = f"{answer}\n\n" + closing.format(a=chunks[0].id, b=chunks[1].id)
        assert links.strip_source_footer(text, real_corpus, sources) == answer

    @pytest.mark.parametrize(
        ("closing", "why"),
        [
            (
                "For full details, see [GPU jobs]({a}) and [PyTorch]({b}).",
                "prose: 'details' is not citation scaffolding",
            ),
            (
                "See [a]({a}) for the quota table.",
                "a pointer into a page is not a restatement of the citations",
            ),
            (
                "Check the limits in [a]({a}) before submitting.",
                "an instruction that happens to contain a link",
            ),
        ],
    )
    def test_a_sentence_that_is_doing_work_survives(self, real_corpus, closing, why):
        chunks, sources = self.two_chunks(real_corpus)
        text = "Answer.\n\n" + closing.format(a=chunks[0].id, b=chunks[1].id)
        assert links.strip_source_footer(text, real_corpus, sources) == text, why

    def test_a_citation_sentence_naming_a_page_not_shown_survives(self, real_corpus):
        """Same gate as the other shapes: removal has to be provably lossless."""
        chunks, sources = self.two_chunks(real_corpus)
        elsewhere = next(c for c in real_corpus.chunks if "slurm" in c.path)
        text = f"Answer.\n\nCited from [x]({elsewhere.id})."
        assert links.strip_source_footer(text, real_corpus, sources) == text

    def test_signal_words_without_links_are_just_words(self, real_corpus):
        _chunks, sources = self.two_chunks(real_corpus)
        text = "Answer.\n\nThe quota is set per source, and cited limits vary."
        assert links.strip_source_footer(text, real_corpus, sources) == text

