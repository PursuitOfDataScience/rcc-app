"""Each answer check, given an answer that must trip it and one that must not.

A check that cannot fail reads as a pass, and an answer-fidelity check is the easiest
place in this repository to write one: the checks run over model output, model output is
usually fine, and a rule with a typo in its regular expression reports a clean run
forever. So every check here is exercised in both directions.

The answers are written rather than recorded. A recorded transcript is better evidence
of what models do, and `tools/agent_bench.py` collects those — but it needs a key and a
network, and this file has to hold in CI.
"""

from __future__ import annotations

import pytest

from evals import checks

# A flag, a path and a module target that appear nowhere in the RCC documentation. If
# any of these ever turns up in the corpus, `test_the_invented_tokens_are_still_invented`
# fails and says so, rather than this file quietly testing nothing.
INVENTED_FLAG = "--wibble-frobnicate"
INVENTED_PATH = "/opt/rcc/wibble/frobnicate"
INVENTED_MODULE = "wibblegromacs/9.9"


@pytest.fixture(scope="module")
def haystack(real_corpus):
    return checks.Haystack(real_corpus)


class TestTechnicalTokens:
    def test_it_collects_flags_paths_and_module_targets(self):
        found = checks.technical_tokens(
            "Run `module load python/3.10`, pass `--partition=caslake`, "
            "and write to /project2/pi-example/data."
        )
        assert "--partition" in found
        assert "python/3.10" in found

    def test_it_ignores_a_placeholder_path(self):
        """Answers are full of `/path/to/your/script.sh`, which claims nothing."""
        found = checks.technical_tokens("Save it as /path/to/your/script.sh")
        assert not any(token.startswith("/path") for token in found)

    def test_it_ignores_a_flag_that_means_the_same_thing_everywhere(self):
        assert "--help" not in checks.technical_tokens("Run `sbatch --help` for more.")

    def test_it_takes_a_numbered_name_only_from_code(self):
        """`Midway3` in a sentence is a name. `midway3` in a command is a literal."""
        assert "midway3" not in checks.technical_tokens("Midway3 has more memory.")
        assert "midway3" in checks.technical_tokens("Run `ssh midway3.rcc.uchicago.edu`.")


class TestUnsupportedTokens:
    def test_a_flag_nowhere_in_the_corpus_is_a_defect(self, haystack):
        found = checks.unsupported_tokens(
            f"Pass `{INVENTED_FLAG}` to sbatch.", {"a": "some evidence"}, haystack
        )
        assert [item.kind for item in found] == ["invented-token"]
        assert found[0].severity == checks.DEFECT

    def test_a_flag_in_the_corpus_but_not_in_what_was_read_is_a_warning(self, haystack):
        found = checks.unsupported_tokens(
            "Pass `--partition=caslake`.", {"a": "nothing relevant"}, haystack
        )
        assert [item.kind for item in found] == ["unsupported-token"]
        assert found[0].severity == checks.WARNING

    def test_a_flag_in_the_evidence_is_clean(self, haystack):
        found = checks.unsupported_tokens(
            "Pass `--partition=caslake`.",
            {"a": "use --partition=caslake for ordinary work"},
            haystack,
        )
        assert found == []

    def test_the_invented_tokens_are_still_invented(self, haystack):
        """Guards the fixtures above: this file means nothing if the corpus gains them."""
        for token in (INVENTED_FLAG, INVENTED_PATH, INVENTED_MODULE):
            assert not haystack.contains(token), f"{token} is now in the corpus"


class TestInventedCitations:
    def test_a_path_the_corpus_does_not_have(self, real_corpus):
        found = checks.invented_citations(
            "See [Batch jobs](docs/slurm/nope.md).", real_corpus
        )
        assert [item.kind for item in found] == ["invented-citation"]

    def test_a_path_it_does(self, real_corpus):
        assert checks.invented_citations(
            "See [Batch jobs](docs/slurm/sbatch.md).", real_corpus
        ) == []


class TestSurvivingFooter:
    @pytest.mark.parametrize(
        "text",
        [
            "The answer.\n\nSources:\n- [Batch jobs](docs/slurm/sbatch.md)",
            "The answer.\n\n**References**\n\n- one",
            "The answer.\n\nBased on the Batch jobs page.",
            "The answer.\n\n## Citations\n\n- one",
        ],
    )
    def test_it_catches_every_shape_the_stripper_should_have_taken(self, text):
        assert [item.kind for item in checks.surviving_footer(text)] == [
            "footer-survived"
        ]

    def test_an_answer_that_cites_inline_is_clean(self):
        assert checks.surviving_footer(
            "Submit with sbatch ([Batch jobs](docs/slurm/sbatch.md))."
        ) == []

    def test_the_word_sources_inside_a_sentence_is_not_a_footer(self):
        assert checks.surviving_footer(
            "RCC sources its documentation from the User Guide."
        ) == []


class TestBareTitleCitations:
    """Asked of the occurrence, not of the text before it.

    The rule looked back for the nearest `[` and accepted any `](` within forty
    characters, so a link *anywhere earlier in the line* marked every later bare title as
    linked. Answers usually carry a link in their first sentence, so the check was inert:
    three findings across 173 real answers.
    """

    SOURCES = [{"label": "Running jobs on RCC clusters", "url": "https://x/#a"}]

    def test_a_section_named_in_plain_text(self):
        found = checks.bare_title_citations(
            "See Running jobs on RCC clusters for more.", self.SOURCES
        )
        assert [item.kind for item in found] == ["bare-title-citation"]

    def test_the_same_title_inside_a_link_is_fine(self):
        assert checks.bare_title_citations(
            "See [Running jobs on RCC clusters](docs/slurm/main.md).", self.SOURCES
        ) == []

    def test_an_earlier_link_does_not_excuse_a_later_bare_title(self):
        """The false negative that made this check inert."""
        text = (
            "Start with [the overview](docs/index.md), " + "and read on. " * 6
            + "Running jobs on RCC clusters has the flags."
        )
        found = checks.bare_title_citations(text, self.SOURCES)
        assert [item.kind for item in found] == ["bare-title-citation"]

    def test_a_link_whose_label_is_something_else_does_not_excuse_it(self):
        text = (
            "See [the GPU section](docs/slurm/sbatch.md) — "
            "Running jobs on RCC clusters is the page."
        )
        found = checks.bare_title_citations(text, self.SOURCES)
        assert [item.kind for item in found] == ["bare-title-citation"]

    def test_a_title_quoted_as_a_literal_is_not_a_citation(self):
        assert checks.bare_title_citations(
            "Search for `Running jobs on RCC clusters` in the sidebar.", self.SOURCES
        ) == []

    def test_a_title_inside_a_code_block_is_not_a_citation(self):
        assert checks.bare_title_citations(
            "```\nRunning jobs on RCC clusters\n```", self.SOURCES
        ) == []

    def test_a_nested_bracket_in_the_label_still_counts_as_linked(self):
        sources = [{"label": "Batch jobs [beta]", "url": "https://x/"}]
        assert checks.bare_title_citations(
            "See [Batch jobs [beta]](docs/slurm/sbatch.md).", sources
        ) == []


class TestForm:
    def test_an_h1_heading(self):
        assert [item.kind for item in checks.form_violations("# Batch jobs\n\ntext")] == [
            "h1-heading"
        ]

    def test_a_fence_with_no_language(self):
        found = checks.form_violations("Run this:\n\n```\nsbatch job.sh\n```\n")
        assert [item.kind for item in found] == ["unlabelled-code-fence"]

    def test_a_tagged_fence_under_an_h2(self):
        assert checks.form_violations("## Batch jobs\n\n```bash\nsbatch job.sh\n```\n") == []


class TestCitationCoverage:
    def test_it_counts_paragraphs_not_lines(self):
        text = (
            "You submit a job with sbatch, which takes a script and queues it for "
            "the scheduler ([Batch jobs](docs/slurm/sbatch.md)).\n\n"
            "The scheduler will then run it whenever the resources you asked for "
            "become available on a suitable compute node."
        )
        coverage, findings = checks.citation_coverage(text)
        assert coverage == 0.5
        assert [item.kind for item in findings] == ["uncited-paragraph"]

    def test_a_code_block_does_not_split_a_paragraph(self):
        text = (
            "Submit it like this ([Batch jobs](docs/slurm/sbatch.md)):\n\n"
            "```bash\nsbatch job.sh\n\nsqueue -u $USER\n```\n"
        )
        coverage, findings = checks.citation_coverage(text)
        assert coverage == 1.0
        assert findings == []


class TestRefusal:
    CONTACT = "help@rcc.uchicago.edu"

    def test_an_answer_that_does_not_decline(self):
        found = checks.refusal_shape("Use `sbatch` on Frontera as usual.", self.CONTACT)
        assert [item.kind for item in found] == ["no-refusal"]

    def test_a_refusal_with_no_address(self):
        found = checks.refusal_shape(
            "The RCC documentation does not appear to cover that.", self.CONTACT
        )
        assert [item.kind for item in found] == ["refused-without-contact"]

    def test_a_refusal_that_hands_over(self):
        assert checks.refusal_shape(
            "The documentation does not cover that. Ask the RCC Help Desk "
            "(help@rcc.uchicago.edu).",
            self.CONTACT,
        ) == []


class TestCommandsForAnUncoveredQuestion:
    def test_a_script_for_something_undocumented(self):
        found = checks.commands_for_uncovered_question(
            "Here is a job script:\n\n```bash\n#SBATCH --partition=normal\n```\n"
        )
        assert [item.kind for item in found] == ["commands-for-uncovered-question"]

    def test_prose_with_no_command(self):
        assert checks.commands_for_uncovered_question(
            "The documentation does not cover that cluster."
        ) == []


class TestPostprocessDamage:
    def test_a_stripper_that_ate_a_code_fence(self):
        raw = "Answer.\n\n```bash\nsbatch job.sh\n```\n"
        final = "Answer.\n"
        assert "damaging-strip" in [item.kind for item in checks.postprocess_damage(raw, final)]

    def test_a_stripper_that_ate_a_sentence(self):
        raw = "Answer.\n\nThe scheduler runs your job when the resources you asked for become free.\n"
        final = "Answer.\n"
        assert "damaging-strip" in [item.kind for item in checks.postprocess_damage(raw, final)]

    def test_removing_a_short_footer_line_is_not_damage(self):
        raw = "Answer.\n\nSources:\n"
        final = "Answer.\n"
        assert checks.postprocess_damage(raw, final) == []

    def test_no_change_at_all(self):
        assert checks.postprocess_damage("same", "same") == []


class TestMissingRequired:
    def test_a_cancel_answer_with_no_scancel_in_it(self):
        found = checks.missing_required("Use the queue tools to stop it.", ("scancel",))
        assert [item.kind for item in found] == ["missing-required-token"]

    def test_the_token_present(self):
        assert checks.missing_required("Run `scancel 12345`.", ("scancel",)) == []


class TestInspect:
    """The composition, and the one thing it must not get backwards."""

    ANSWER = (
        "Submit it with `sbatch` ([Batch jobs](docs/slurm/sbatch.md)).\n\n"
        "```bash\nsbatch job.sh\n```\n"
    )

    def record(self, expect: str) -> dict:
        return {
            "text": self.ANSWER,
            "raw": self.ANSWER,
            "sources": [{"label": "Batch jobs", "url": "https://x/"}],
            "evidence": {"a": "submit with sbatch job.sh"},
            "expect": expect,
            "must_mention": ["sbatch"],
        }

    def test_a_command_block_is_right_on_one_side(self, real_corpus, haystack):
        found = checks.inspect(self.record("answer"), real_corpus, haystack)
        assert "commands-for-uncovered-question" not in [item.kind for item in found]

    def test_and_a_defect_on_the_other(self, real_corpus, haystack):
        found = checks.inspect(self.record("caveat"), real_corpus, haystack)
        kinds = [item.kind for item in found]
        assert "commands-for-uncovered-question" in kinds
        assert "no-refusal" in kinds

    def test_an_empty_answer_produces_no_content_findings(self, real_corpus, haystack):
        """An empty answer is an outcome the harness records, not a content defect.

        Checking nothing would report it as a clean answer, which is how a blank bubble
        would score better than a flawed one.
        """
        record = self.record("answer") | {"text": "   ", "raw": "   "}
        assert checks.inspect(record, real_corpus, haystack) == []

    def test_defects_and_tally(self, real_corpus, haystack):
        found = checks.inspect(self.record("caveat"), real_corpus, haystack)
        assert checks.defects(found)
        assert checks.tally(found)["no-refusal"] == 1


class TestACitationEntryWithADescription:
    """The shape that fooled two checks in a row.

    `- Why the connection closes: [Why does my sinteractive job fail…](docs/slurm/faq.md#…)`
    is a citation entry with a sentence fragment in front of the link. It defeated
    `strip_source_footer`'s shape rules — that is what `_interior_footer` was written for —
    and then defeated `postprocess_damage`'s exemption too, so a correct removal was
    reported as the stripper eating content.
    """

    ENTRY = (
        "- Why the connection closes: [Why does my sinteractive job fail with "
        "“Connection closed.”?](docs/slurm/faq.md#why-it-fails)"
    )

    def test_removing_it_is_not_damage(self):
        raw = f"The session ended early.\n\n**Citations:**\n{self.ENTRY}"
        final = "The session ended early."
        assert checks.postprocess_damage(raw, final) == []

    def test_a_real_sentence_with_a_link_is_still_damage(self):
        raw = (
            "The session ended early.\n\nIf none of those is the cause, check the exit "
            "reason in `squeue` and read [Running jobs](docs/slurm/faq.md#jobs) for the "
            "other resource limits that end a job early."
        )
        final = "The session ended early."
        assert [item.kind for item in checks.postprocess_damage(raw, final)] == [
            "damaging-strip"
        ]


class TestTheRedirectAnswer:
    """The best answer in the first real run, which two checks called a defect.

    Asked "how do I check the queue with bjobs", a model replied that RCC's clusters use
    Slurm rather than PBS, that there is no `bjobs`, that the equivalent is `squeue` — and
    then documented `squeue` properly. Naming the absence and handing over the real command
    is better than declining, and "unanswerable therefore no commands" is simply wrong for
    the two largest classes in the negative set.
    """

    ANSWER = (
        "RCC's clusters use **Slurm**, not PBS/Torque, so there is no `bjobs` command. "
        "The Slurm equivalent is **`squeue`**.\n\n### Check your own jobs\n\n"
        "```bash\nsqueue -u $USER\n```\n"
    )

    def test_it_counts_as_declining(self):
        assert checks.refusal_shape(self.ANSWER, "help@rcc.uchicago.edu") == [] or [
            item.kind for item in checks.refusal_shape(self.ANSWER, "help@rcc.uchicago.edu")
        ] == ["refused-without-contact"]
        assert "no-refusal" not in [
            item.kind
            for item in checks.refusal_shape(self.ANSWER, "help@rcc.uchicago.edu")
        ]

    def test_the_equivalent_command_is_not_a_defect(self):
        assert checks.commands_for_uncovered_question(self.ANSWER) == []

    def test_a_command_with_no_word_about_the_absence_still_is(self):
        answer = (
            "Use `bjobs` to list your jobs:\n\n```bash\nbjobs -u $USER\n```\n"
        )
        assert [
            item.kind for item in checks.commands_for_uncovered_question(answer)
        ] == ["commands-for-uncovered-question"]


class TestTablesAreNotParagraphs:
    """Models reach for a table constantly, and a table makes no claim in prose.

    A four-row flag reference counted as one uncited paragraph, so the check was charging
    models for formatting. Measured across 143 real answers, `uncited-paragraph` was the
    most numerous warning of all.
    """

    TABLE = (
        "Use `squeue` to list jobs ([Running jobs](docs/slurm/main.md)).\n\n"
        "| Flag | What it does |\n|---|---|\n"
        "| `-u USER` | Show jobs for a specific user, replacing USER with a name |\n"
        "| `-p PART` | Show jobs in one partition, for example standard or gpu |\n"
    )

    def test_a_table_is_not_counted_as_uncited(self):
        coverage, findings = checks.citation_coverage(self.TABLE)
        assert coverage == 1.0
        assert findings == []

    def test_prose_after_a_table_is_still_counted(self):
        text = self.TABLE + (
            "\nIf the job is not listed it has already finished, and the exit state is "
            "the thing to look at next rather than the queue.\n"
        )
        coverage, findings = checks.citation_coverage(text)
        assert [item.kind for item in findings] == ["uncited-paragraph"]
        assert coverage == 0.5

    def test_a_pipe_inside_a_sentence_is_not_a_table(self):
        text = (
            "Pipe the output into grep to narrow it down, using the | character between "
            "the two commands, which the shell reads as a pipeline rather than as text.\n"
        )
        assert checks.prose_paragraphs(text)


class TestAOneWordTitleIsAlsoAnOrdinaryNoun:
    """`links._source_names` already knew this, and its floor is words, not characters.

    `Charliecloud` is a page title *and* the name of a container runtime, so "RCC supports
    Singularity/Apptainer and **Charliecloud**" was reported as a bare citation three times
    across 173 real answers. A character floor let every long single word through.
    """

    def test_a_single_word_title_is_not_a_citation(self):
        sources = [{"label": "Charliecloud", "url": "https://x/"}]
        text = (
            "RCC supports two container runtimes on Midway3: **Singularity/Apptainer** "
            "and **Charliecloud**. Both pull and run images."
        )
        assert checks.bare_title_citations(text, sources) == []

    def test_a_two_word_title_still_counts(self):
        sources = [{"label": "Interactive jobs", "url": "https://x/"}]
        text = "All of the above comes from the documentation page Interactive jobs."
        assert [
            item.kind for item in checks.bare_title_citations(text, sources)
        ] == ["bare-title-citation"]

    def test_a_hyphenated_pair_counts_as_two_words(self):
        sources = [{"label": "Data-transfer", "url": "https://x/"}]
        text = "The page Data-transfer covers it in full, with examples for each tool."
        assert [
            item.kind for item in checks.bare_title_citations(text, sources)
        ] == ["bare-title-citation"]
