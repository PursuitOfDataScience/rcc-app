import pytest

from sage import links, profile
from sage.corpus import Chunk, Corpus, Document

PROFILE = profile.active()
DOCS_BASE_URL = PROFILE.source("docs").base_url


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
            url="https://docs.rcc.uchicago.edu/slurm/sbatch/#gpu-jobs",
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
            "https://docs.rcc.uchicago.edu/slurm/sbatch/",
            "body",
        ),
        "web/faqs.txt": Document(
            "web", "faqs.txt", "FAQs", "https://cloud-skyway.rcc.uchicago.edu/faqs", "body"
        ),
    }
    # With its sources, because a corpus built by `corpus.build` always has them and
    # they are what `url_for` needs to place an anchor on a page the model cited by
    # path rather than by indexed section.
    return Corpus(chunks=chunks, documents=documents, sources=PROFILE.sources)


CORPUS = build()


def test_scraped_pages_cite_their_own_host():
    """These used to be redirected to the Midway user guide root."""
    out = links.fix_links("See the [Skyway FAQ](web/faqs.txt).", CORPUS)
    assert "https://cloud-skyway.rcc.uchicago.edu/faqs" in out


def test_chunk_ids_resolve_to_a_deep_link():
    out = links.fix_links("[GPU jobs](docs/slurm/sbatch.md#gpu-jobs)", CORPUS)
    assert out == (
        "[GPU jobs](https://docs.rcc.uchicago.edu/slurm/sbatch/#gpu-jobs)"
    )


def test_page_paths_resolve_without_an_anchor():
    out = links.fix_links("[Batch jobs](docs/slurm/sbatch.md)", CORPUS)
    assert out == "[Batch jobs](https://docs.rcc.uchicago.edu/slurm/sbatch/)"


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
    assert DOCS_BASE_URL not in out


def test_invented_paths_are_reported_not_only_hidden():
    text = "See [a](docs/slurm/sbatch.md) and [b](docs/nope/missing.md)."
    assert links.unresolved(text, CORPUS) == ["docs/nope/missing.md"]


def test_external_and_anchor_targets_are_not_counted_as_invented():
    text = "[RCC](https://rcc.uchicago.edu/) and [up there](#top)"
    assert links.unresolved(text, CORPUS) == []


class TestImagesInAnAnswer:
    """Eighteen indexed sections carry markdown images — the SDE3 connection
    tutorial is nothing but screenshots — so a model quoting one echoes the syntax.

    The link rules saw `[alt](images/avd_login.png)`, could not resolve an image path
    in a corpus of documents, and unlinked it: the reader got `!Screenshot showing AVD
    login{ width="1000" }`. A stray exclamation mark, a stray attribute list, and no
    hint that the thing being described was a picture.
    """

    def test_an_image_becomes_a_figure_note(self):
        out = links.fix_links(
            'Then: ![Screenshot showing AVD login](images/avd_login.png)'
            '{ width="1000" } and sign in.',
            CORPUS,
        )
        assert out == "Then: [figure: Screenshot showing AVD login] and sign in."

    def test_an_image_with_no_alt_text_still_says_it_was_there(self):
        assert links.fix_links("See ![](img/x.png).", CORPUS) == "See [figure]."

    def test_a_real_link_beside_one_is_untouched(self):
        out = links.fix_links(
            "![x](img/x.png) then [Batch jobs](docs/slurm/sbatch.md).", CORPUS
        )
        assert "slurm/sbatch/" in out

    def test_an_image_path_is_not_logged_as_an_invented_citation(self):
        assert links.unresolved("![alt](images/x.png)", CORPUS) == []

    def test_an_image_the_browser_can_fetch_is_left_alone(self):
        """Only the relative form is broken. The geocoding tutorial links four
        absolute ones, and those render — turning them into a caption would take a
        working figure away."""
        text = "![RCC-GIS geocoding](https://gis.rcc.uchicago.edu/x/summary.png)"
        assert links.fix_links(text, CORPUS) == text

    def test_a_badge_inside_a_link_survives(self):
        text = "[![build](https://img.shields.io/x.svg)](https://github.com/rcc/x)"
        assert links.fix_links(text, CORPUS) == text


class TestNestedBracketsInALabel:
    """`[Batch jobs [beta]](docs/…)` is a link a model writes.

    The label pattern could not match one, so the target was neither resolved nor
    unlinked and shipped as a live relative href — which a browser resolves against
    the app's own host, giving the reader a 404 that looks exactly like a working
    citation. `unresolved()` could not see it either, so not even the log knew.
    """

    def test_it_resolves(self):
        out = links.fix_links("See [Batch jobs [beta]](docs/slurm/sbatch.md).", CORPUS)
        assert "docs/slurm/sbatch.md" not in out
        assert "slurm/sbatch/" in out

    def test_an_unresolvable_one_is_unlinked_and_counted(self):
        text = "See [Batch jobs [beta]](docs/nope.md)."
        assert links.fix_links(text, CORPUS) == "See Batch jobs [beta]."
        assert links.unresolved(text, CORPUS) == ["docs/nope.md"]


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

    @pytest.mark.parametrize(
        ("answer", "why"),
        [
            (
                "Use the RCC's own wording.\n\nCitation: please reference the "
                "University of Chicago's Research Computing Center.",
                "the citation IS the answer to 'how do I acknowledge RCC'",
            ),
            (
                "Acknowledge it like this.\n\nReference: The University of Chicago's "
                "Research Computing Center provided the resources for this work.",
                "a sentence under a label is prose, not a reference list",
            ),
            (
                "Acknowledge RCC like this:\n\nCitation:\nThis work was completed in "
                "part with resources provided by the\nUniversity of Chicago's "
                "Research Computing Center.",
                "and the same thing spread over the lines below the label",
            ),
        ],
    )
    def test_a_citation_that_is_the_answer_is_not_a_footer(self, answer, why):
        """The rule was "shorter than 120 characters", and under a `Citation:` label
        that ate the answer: the model printed the wording to copy into a paper and
        the strip deleted it — from the transcript, and from the history sent
        upstream, so the follow-up could not see it either."""
        assert links.strip_source_footer(answer) == answer, why

    @pytest.mark.parametrize(
        "footer",
        [
            # A full stop is how a model ends a line, and a title and a short
            # sentence look the same with one on the end. Gating on it alone kept
            # 115 of the corpus's 572 headings as footers — a duplicate under every
            # answer that cited a page whose name is one word.
            "Sources: Storage System Layout — Quotas.",
            "Sources: Storage.",
            "Sources: Midway3 partitions.",
            # A heading with a comma in it: split on commas first and the name the
            # strip is showing becomes three fragments that match nothing.
            "Sources: Service units, allocations, and accounts",
        ],
    )
    def test_a_footer_that_ends_like_a_sentence_still_goes(self, footer):
        sources = [
            {"id": f"docs/x{n}.md#s", "label": label,
             "url": f"https://docs.rcc.uchicago.edu/x{n}/#s", "source": "docs"}
            for n, label in enumerate((
                "Storage System Layout — Quotas", "Storage", "Midway3 partitions",
                "Running jobs — Service units, allocations, and accounts",
            ))
        ]
        answer = "Quota on /project2 is 100 GB."
        assert links.strip_source_footer(f"{answer}\n\n{footer}", None, sources) == answer

    def test_a_footer_the_strip_proves_is_cut_whatever_its_punctuation(self):
        """The shape rule above is deliberately cautious, so it leaves a footer that
        ends on a full stop. When the caller hands over what the strip is showing,
        the duplication is provable and punctuation stops mattering."""
        sources = [{
            "id": "docs/storage/main.md#quotas",
            "label": "Storage System Layout — Quotas",
            "url": "https://docs.rcc.uchicago.edu/storage/main/#quotas",
            "source": "docs",
        }]
        answer = "Quota on /project2 is 100 GB."
        text = f"{answer}\n\nSources: Storage System Layout — Quotas."
        assert links.strip_source_footer(text, None, sources) == answer

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


class TestAFooterWithTheAnswerContinuingUnderneath:
    """The shape every trailing rule above is blind to.

    Measured on 98 live turns: two answers wrote a `**Citations:**` block and then one
    more sentence. One of them listed the same two sections the Sources strip printed
    three lines below — the duplicate this module exists to prevent, in a position it
    could not see.

    Cutting inside an answer is more dangerous than cutting off its end, so the bar is
    proof rather than shape: every line of the block must carry a link, and every link
    must resolve to a page the strip already shows.
    """

    @staticmethod
    def two_chunks(corpus):
        chunks = [chunk for chunk in corpus.chunks if "cli" in chunk.path][:2]
        sources = [
            {"id": c.id, "label": c.label, "url": c.url, "source": c.source}
            for c in chunks
        ]
        return chunks, sources

    def answer(self, chunks, *, tail=True, described=True):
        entries = "\n".join(
            f"- {'How to do it: ' if described else ''}[{chunk.heading}]({chunk.id})"
            for chunk in chunks
        )
        end = (
            "\n\nIf you are moving very large datasets, use Globus instead."
            if tail else ""
        )
        return f"Copy it with `scp`.\n\n---\n\n**Citations:**\n{entries}{end}"

    def test_the_block_goes_and_the_sentence_after_it_stays(self, real_corpus):
        chunks, sources = self.two_chunks(real_corpus)
        out = links.strip_source_footer(self.answer(chunks), real_corpus, sources)
        assert "Citations" not in out
        assert "If you are moving very large datasets" in out
        assert out.startswith("Copy it with `scp`.")

    def test_the_rule_it_was_fenced_off_with_goes_too(self, real_corpus):
        chunks, sources = self.two_chunks(real_corpus)
        out = links.strip_source_footer(self.answer(chunks), real_corpus, sources)
        assert "---" not in out

    def test_a_description_before_the_link_does_not_save_it(self, real_corpus):
        """What defeated the shape rules: `- How to do it: [CLI › SCP](…)` is not a bare
        title and not a bare link, so `_is_citation_line` declined to judge it."""
        chunks, sources = self.two_chunks(real_corpus)
        out = links.strip_source_footer(
            self.answer(chunks, described=True), real_corpus, sources
        )
        assert "Citations" not in out

    def test_a_link_to_a_page_the_strip_does_not_show_keeps_the_block(self, real_corpus):
        """No proof of duplication, no cut — the reader may be being sent somewhere new.

        A different *page*, not a different section of the same one: `_pages` compares at
        page granularity on purpose, because a chip linking `…/cli/#scp` already gives the
        reader the page whatever anchor the model chose.
        """
        chunks, sources = self.two_chunks(real_corpus)
        elsewhere = next(
            chunk for chunk in real_corpus.chunks if "storage" in chunk.path
        )
        answer = self.answer([chunks[0], elsewhere])
        out = links.strip_source_footer(answer, real_corpus, sources)
        assert "Citations" in out

    def test_prose_entries_are_left_alone(self, real_corpus):
        """The other real case: a `**Citations**` heading over two sentences summarising
        what each source says. That is content, not a duplicate list, and there is no link
        to prove anything with."""
        chunks, sources = self.two_chunks(real_corpus)
        answer = (
            "Copy it with `scp`.\n\n**Citations**\n"
            "- The CLI page lists the scp command format and gives two examples.\n"
            "- The rsync section explains the flags for a whole directory.\n\n"
            "Contact the help desk if it still fails."
        )
        out = links.strip_source_footer(answer, real_corpus, sources)
        assert "Citations" in out

    def test_nothing_happens_without_the_strip_to_compare_against(self, real_corpus):
        chunks, _sources = self.two_chunks(real_corpus)
        answer = self.answer(chunks)
        assert links.strip_source_footer(answer, real_corpus, None) == answer

    def test_a_trailing_footer_is_still_the_trailing_rules_business(self, real_corpus):
        """One decision in one place: with nothing after it, the rules above own it."""
        chunks, sources = self.two_chunks(real_corpus)
        out = links.strip_source_footer(
            self.answer(chunks, tail=False), real_corpus, sources
        )
        assert "Citations" not in out
        assert out.startswith("Copy it with `scp`.")


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



class TestInlineParentheticalCitations:
    """The shape none of the rules above can see: a parenthetical of bare section
    titles inside a sentence.

    Reported from a real answer — "…used on a cluster (Allocations and Service Units
    FAQ, Running jobs on RCC clusters)." — where the same two titles were printed in
    the Sources strip three lines below. It is not a trailing line, it holds no links,
    and it carries no label, so the labelled, bare-link and citation-sentence rules
    all pass over it.
    """

    SOURCES = [
        {
            "label": "Allocations and Service Units FAQ — How do I check how many "
            "service units I have remaining on my allocation?",
            "url": "https://docs.rcc.uchicago.edu/facts/allocations-faq/#check",
        },
        {
            "label": "Running jobs on RCC clusters",
            "url": "https://docs.rcc.uchicago.edu/slurm/main/#running",
        },
        {
            "label": "Batch jobs — Submitting a sbatch script",
            "url": "https://docs.rcc.uchicago.edu/slurm/sbatch/#submitting",
        },
        {
            "label": "Partitions — Midway3 partitions",
            "url": "https://docs.rcc.uchicago.edu/slurm/partitions/#midway3",
        },
    ]

    def test_the_reported_answer_loses_only_its_citation(self):
        text = (
            "For reference, service units are what your jobs consume — they measure "
            "the computing resources (CPUs/GPUs/time) used on a cluster (Allocations "
            "and Service Units FAQ, Running jobs on RCC clusters)."
        )
        assert links.strip_inline_citations(text, self.SOURCES) == (
            "For reference, service units are what your jobs consume — they measure "
            "the computing resources (CPUs/GPUs/time) used on a cluster."
        )

    @pytest.mark.parametrize(
        "text,expected,why",
        [
            (
                "Submit with sbatch (see Batch jobs).",
                "Submit with sbatch.",
                "a citation the model introduces rather than states bare",
            ),
            (
                "Use --gres=gpu:1 (Batch jobs) to reserve the device.",
                "Use --gres=gpu:1 to reserve the device.",
                "mid-sentence, not only at the end",
            ),
            (
                "Check the FAQ (Allocations and Service Units FAQ).",
                "Check the FAQ.",
                "'and' inside a title must not split it",
            ),
            (
                "Pick one (Batch jobs and Running jobs on RCC clusters).",
                "Pick one.",
                "'and' between two titles is a separator",
            ),
        ],
    )
    def test_citation_shapes_that_come_off(self, text, expected, why):
        assert links.strip_inline_citations(text, self.SOURCES) == expected, why

    @pytest.mark.parametrize(
        "text,why",
        [
            (
                "They measure the resources (CPUs/GPUs/time) used on a cluster.",
                "an ordinary aside in the very sentence that carried the bug",
            ),
            (
                "Run it on the login node (not a compute node).",
                "prose in brackets",
            ),
            (
                "Submit with sbatch ([Batch jobs](docs/slurm/sbatch.md)).",
                "a real link is the citation form the prompt asks for",
            ),
            (
                "Quotas differ (Allocations and Service Units FAQ, but ask your PI).",
                "one real aside keeps the whole parenthetical",
            ),
            (
                "Install the package (Python) first.",
                "a single-word title is also an ordinary word",
            ),
            (
                "Install both (Python and R) first.",
                "two single-word titles are still ordinary words",
            ),
            (
                "Jobs land on a partition (see the scheduler docs).",
                "a name the strip is not showing",
            ),
            (
                "Pick one (Batch jobs and Partitions).",
                "one single-word title is enough to keep the bracket",
            ),
        ],
    )
    def test_prose_in_brackets_survives(self, text, why):
        assert links.strip_inline_citations(text, self.SOURCES) == text, why

    def test_no_strip_means_nothing_to_duplicate(self):
        text = "Service units are what jobs consume (Running jobs on RCC clusters)."
        assert links.strip_inline_citations(text, []) == text
        assert links.strip_inline_citations(text, None) == text


class TestInlineMarkers:
    """A numbered marker at the end of each sentence that rests on a source.

    The Sources strip says what the whole answer rests on; it cannot say which
    sentence rests on which, and that is what a reader asks of any particular claim.
    Built from the links the model already writes, so no model has to learn anything
    and the tool-less ones get it too.
    """

    SOURCES = [
        {"id": "docs/slurm/sbatch.md#gpu-jobs", "label": "Batch jobs — GPU jobs",
         "url": "https://docs.rcc.uchicago.edu/slurm/sbatch/#gpu-jobs",
         "source": "docs"},
        {"id": "web/faqs.txt#1", "label": "FAQs",
         "url": "https://cloud-skyway.rcc.uchicago.edu/faqs", "source": "web"},
    ]

    def mark(self, text):
        return links.mark_sources(text, self.SOURCES)

    def test_the_marker_lands_after_the_sentence_not_mid_clause(self):
        out = self.mark(
            "Request one with [GPU jobs](https://docs.rcc.uchicago.edu/slurm/"
            "sbatch/#gpu-jobs) and --gres. Then submit it."
        )
        assert out == (
            "Request one with GPU jobs and --gres."
            ":small[:gray[[1](https://docs.rcc.uchicago.edu/slurm/sbatch/#gpu-jobs)]]"
            " Then submit it."
        )

    def test_the_number_is_the_one_the_strip_shows(self):
        out = self.mark("See [FAQs](https://cloud-skyway.rcc.uchicago.edu/faqs).")
        assert "[2](" in out, "FAQs is the second entry in the strip"

    def test_a_different_anchor_on_a_cited_page_takes_that_page_s_number(self):
        """The strip lists one entry per destination, so a model citing another
        section of the same page is citing entry 1, not a new one."""
        out = self.mark(
            "As in [Submitting](https://docs.rcc.uchicago.edu/slurm/sbatch/#submit)."
        )
        assert "[1](" in out

    def test_two_sources_in_one_sentence_get_two_markers_in_order(self):
        out = self.mark(
            "Both [GPU jobs](https://docs.rcc.uchicago.edu/slurm/sbatch/#gpu-jobs) "
            "and [FAQs](https://cloud-skyway.rcc.uchicago.edu/faqs) apply."
        )
        assert out.index("[1](") < out.index("[2](")
        assert out.count(":small[") == 2

    def test_the_same_source_twice_in_a_sentence_is_marked_once(self):
        out = self.mark(
            "See [GPU jobs](https://docs.rcc.uchicago.edu/slurm/sbatch/#gpu-jobs) and "
            "[GPU jobs](https://docs.rcc.uchicago.edu/slurm/sbatch/#gpu-jobs) again."
        )
        assert out.count(":small[") == 1

    def test_the_prose_keeps_its_words(self):
        """The label is unlinked, not deleted — the sentence still has to read."""
        out = self.mark(
            "read [Batch jobs](https://docs.rcc.uchicago.edu/slurm/sbatch/#gpu-jobs) "
            "for the flags."
        )
        assert "read Batch jobs for the flags." in out

    def test_a_link_the_strip_does_not_list_is_left_alone(self):
        out = self.mark("See [elsewhere](https://example.org/page) for that.")
        assert out == "See [elsewhere](https://example.org/page) for that."

    def test_code_is_never_touched(self):
        fenced = (
            "```bash\n"
            "sbatch [x](https://docs.rcc.uchicago.edu/slurm/sbatch/#gpu-jobs)\n"
            "```"
        )
        assert self.mark(fenced) == fenced
        span = "Run `[x](https://docs.rcc.uchicago.edu/slurm/sbatch/#gpu-jobs)` now."
        assert self.mark(span) == span

    def test_a_sentence_that_never_ends_is_marked_at_the_end_of_its_line(self):
        out = self.mark(
            "- [GPU jobs](https://docs.rcc.uchicago.edu/slurm/sbatch/#gpu-jobs)"
        )
        assert out.endswith(
            ":small[:gray[[1](https://docs.rcc.uchicago.edu/slurm/sbatch/#gpu-jobs)]]"
        )

    def test_the_marker_goes_outside_a_closing_quote(self):
        out = self.mark(
            'It says "use [GPU jobs](https://docs.rcc.uchicago.edu/slurm/sbatch/'
            '#gpu-jobs)." Next.'
        )
        assert '."' + ":small[" in out

    @pytest.mark.parametrize("sources", [None, []])
    def test_no_sources_means_no_change(self, sources):
        text = "See [GPU jobs](https://docs.rcc.uchicago.edu/slurm/sbatch/#gpu-jobs)."
        assert links.mark_sources(text, sources) == text

    def test_an_answer_with_no_citations_is_untouched(self):
        text = "You cannot run commands from here.\n\nAsk RCC instead."
        assert self.mark(text) == text


class TestAttributingWhatTheModelDidNotLink:
    """Markers cannot depend on whether a free model felt like citing.

    Asked the same question twice, `nemotron-3.5-lightning` linked two sections on one
    run and none on the next — which is how an answer came back with a Sources strip
    and no markers at all. A paragraph the model left unlinked is attributed from what
    the turn actually read, and only where that cannot be wrong.
    """

    SUBMITTING = "docs/slurm/sbatch.md#submitting"
    SCRIPTS = "docs/slurm/sbatch.md#scripts"

    def one_source(self):
        return (
            [{"id": self.SUBMITTING, "label": "Batch jobs — Submitting",
              "url": "https://docs.rcc.uchicago.edu/slurm/sbatch/#submitting",
              "source": "docs"}],
            {self.SUBMITTING: "Submit the script with the sbatch command. Slurm "
                              "replies with a job identifier you can watch using "
                              "squeue on the login node."},
        )

    def test_a_paragraph_with_no_link_is_attributed_to_the_one_section_read(self):
        sources, evidence = self.one_source()
        out = links.mark_sources(
            "Submit it with the sbatch command and Slurm returns a job identifier.",
            sources, evidence,
        )
        assert out.endswith(
            ":small[:gray[[1](https://docs.rcc.uchicago.edu/slurm/sbatch/#submitting)]]"
        )

    def test_a_sentence_the_section_has_nothing_to_do_with_is_left_alone(self):
        sources, evidence = self.one_source()
        text = "The weather in Chicago is fine today."
        assert links.mark_sources(text, sources, evidence) == text

    def test_two_sections_read_means_no_guessing(self):
        """Measured on the real corpus: word overlap handed almost every sentence to
        the longer of two sections, because a longer section owns more words. A
        plausible wrong citation is the thing this module exists to prevent."""
        sources = [
            {"id": self.SUBMITTING, "label": "a", "source": "docs",
             "url": "https://docs.rcc.uchicago.edu/slurm/sbatch/#submitting"},
            {"id": self.SCRIPTS, "label": "b", "source": "docs",
             "url": "https://docs.rcc.uchicago.edu/slurm/sbatch/#scripts"},
        ]
        evidence = {
            self.SUBMITTING: "Submit the script with the sbatch command.",
            self.SCRIPTS: "A script begins with a shebang and SBATCH directives "
                          "such as job-name and partition and time and memory.",
        }
        out = links.mark_sources(
            "Submit it with the sbatch command and set the directives you need.",
            sources, evidence,
        )
        assert ":small[" not in out

    def test_the_model_s_own_link_still_wins_where_it_wrote_one(self):
        """An exact citation beats an inferred one, so a linked paragraph is marked
        from the link and never attributed a second time."""
        sources, evidence = self.one_source()
        out = links.mark_sources(
            "Submit it with [Batch jobs](https://docs.rcc.uchicago.edu/slurm/"
            "sbatch/#submitting) and watch it with squeue.",
            sources, evidence,
        )
        assert out.count(":small[") == 1

    def test_one_marker_per_paragraph_not_per_sentence(self):
        sources, evidence = self.one_source()
        out = links.mark_sources(
            "Submit the script with sbatch. Slurm replies with a job identifier. "
            "Watch it with squeue on the login node.",
            sources, evidence,
        )
        assert out.count(":small[") == 1

    @pytest.mark.parametrize("line", [
        "## Submitting the sbatch script to Slurm",
        "> Submit the script with the sbatch command and squeue.",
        "| sbatch | submit the script to Slurm with squeue |",
    ])
    def test_headings_quotes_and_tables_are_not_prose_making_a_claim(self, line):
        sources, evidence = self.one_source()
        assert links.mark_sources(line, sources, evidence) == line

    def test_evidence_the_strip_does_not_list_is_ignored(self):
        sources, _ = self.one_source()
        stray = {"docs/somewhere/else.md#x": "sbatch squeue slurm job identifier"}
        text = "Submit it with the sbatch command and watch with squeue."
        assert links.mark_sources(text, sources, stray) == text

    def test_no_evidence_is_the_behaviour_it_had_before(self):
        sources, _ = self.one_source()
        text = "Submit it with the sbatch command and watch with squeue."
        assert links.mark_sources(text, sources) == text


class TestWhatTheAnswerLinksTo:
    """`cited_pages` is the inverse of `unresolved`: the pages a reader can reach.

    Needed because the Sources strip is built from `read_doc` calls alone, so "what did
    this turn put in front of the reader" and "what did it read" are different questions —
    and the benchmark was answering the second while labelling it the first.
    """

    def test_a_section_link_resolves_to_its_page(self, real_corpus):
        assert links.cited_pages(
            "see [GPU jobs](docs/slurm/sbatch.md#gpu-jobs)", real_corpus
        ) == {"slurm/sbatch.md"}

    def test_a_page_link_resolves_too(self, real_corpus):
        assert links.cited_pages(
            "see [Batch jobs](docs/slurm/sbatch.md)", real_corpus
        ) == {"slurm/sbatch.md"}

    def test_several_links_come_back_deduplicated(self, real_corpus):
        found = links.cited_pages(
            "[a](docs/slurm/sbatch.md#gpu-jobs) [b](docs/slurm/sbatch.md) "
            "[c](docs/storage/main.md)",
            real_corpus,
        )
        assert found == {"slurm/sbatch.md", "storage/main.md"}

    @pytest.mark.parametrize("text", [
        "[x](docs/nope.md)",                      # a page the corpus does not have
        "[x](https://docs.rcc.uchicago.edu/)",    # already a URL
        "![diagram](docs/img/x.png)",             # an image is not a citation
        "no links at all",
        "",
    ])
    def test_nothing_to_count(self, text, real_corpus):
        assert links.cited_pages(text, real_corpus) == set()

    def test_an_invented_path_is_still_reported_by_the_other_half(self, real_corpus):
        """The two are complementary: one counts what resolves, one what does not."""
        text = "[good](docs/slurm/sbatch.md) and [bad](docs/nope.md)"
        assert links.cited_pages(text, real_corpus) == {"slurm/sbatch.md"}
        assert links.unresolved(text, real_corpus) == ["docs/nope.md"]
