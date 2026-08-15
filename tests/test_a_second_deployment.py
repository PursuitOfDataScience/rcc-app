"""A profile that is not the RCC's, which is the thing this architecture is for.

`profiles/README.md` promises that serving different documents is a copy of one TOML file
with different values in it, and `tests/test_profile.py` holds the other half of that promise
by walking every string in `sage/` and failing on one that names the RCC. Nothing assembled
a second profile and asked it a question — and `tests/conftest.py` deliberately clears
`SAGE_PROFILE`, so no amount of running the suite under one could.

That gap hid a real bug. On a corpus whose prose is all declarative — most machine-generated
documentation — the words "how", "do" and "I" are all absent, so all three counted as unseen
topics; and `I`, being the one English word capitalised wherever it stands, read as the name
of a system the documentation had never heard of. Every "how do I …" question was refused.
The RCC corpus contains "i" in FAQ headings like "I accidentally deleted a file", which is
exactly why the RCC numbers never moved.
"""

from __future__ import annotations

import textwrap

import pytest

from sage import profile as profile_mod
from sage import runtime

MANUAL = (
    "A widget is made by pressing the lever twice and waiting for the chime to sound. "
)


@pytest.fixture(scope="module")
def widget_company(tmp_path_factory):
    """A minimal second deployment: one source, one page, its own URL and subject."""
    root = tmp_path_factory.mktemp("widgets")
    pages = root / "pages"
    pages.mkdir()
    # Enough pages, and varied enough, that IDF behaves like a real corpus. Sixty copies
    # of one sentence collapse it instead: every content word appears on every page, so
    # nothing discriminates and even an on-topic question scores near zero — an artefact of
    # the fixture that would read as a fault in the app.
    subjects = ["lever", "chime", "hopper", "spindle", "gasket", "flywheel"]
    verbs = ["adjust", "inspect", "replace", "calibrate", "lubricate", "reset"]
    for index in range(60):
        subject = subjects[index % len(subjects)]
        verb = verbs[(index // len(subjects)) % len(verbs)]
        (pages / f"p{index}.md").write_text(
            f"# The {subject} ({index})\n\n## How to {verb} the {subject}\n\n"
            + f"To {verb} the {subject} on unit {index}, open the panel and turn the "
              f"{subject} clockwise until it stops. " * 4
        )
    (pages / "widgets.md").write_text("# Widgets\n\n## Making a widget\n\n" + MANUAL * 6)
    toml = root / "mine.toml"
    toml.write_text(textwrap.dedent(f"""
        [assistant]
        name = "Helper"
        subject = "the Widget Company"
        topic = "widget"
        corpus_name = "the widget manual"
        contact = "help@widgets.example"
        contact_label = "Widget Support"
        [[sources]]
        name = "pages"
        path = "{pages}"
        extensions = [".md"]
        reader = "markdown"
        links = "mkdocs"
        base_url = "https://widgets.example/"
        [retrieval]
        engine = "bm25"
    """))
    return runtime.build(profile_mod.load(str(toml)))


class TestItAssembles:
    def test_the_documents_are_indexed(self, widget_company):
        assert len(widget_company.corpus.chunks) > 60

    def test_the_tools_are_bound_to_that_index(self, widget_company):
        assert len(widget_company.tool_schemas) == 2
        assert widget_company.retriever.search("making a widget")

    def test_the_prompt_is_about_the_widget_company(self, widget_company):
        assert "Widget Company" in widget_company.system_prompt
        assert "RCC" not in widget_company.system_prompt
        assert "help@widgets.example" in widget_company.system_prompt

    def test_citations_point_at_its_own_site(self, widget_company):
        result = widget_company.retriever.search("making a widget")[0]
        assert result.chunk.url.startswith("https://widgets.example/")

    def test_the_caveat_names_its_own_documentation(self, widget_company):
        assert "widget" in widget_company.identity.documentation


class TestTheGateTravels:
    """The part that did not, and the reason it is tested on a foreign corpus.

    Both rules below are inert on the RCC corpus — its numbers are unchanged to the decimal
    — so only a second deployment can hold them.
    """

    def test_an_on_topic_question_is_answerable(self, widget_company):
        assessment = widget_company.retriever.assess("how do I make a widget")
        assert assessment.unknown_terms == (), assessment.unknown_terms
        assert assessment.confident

    def test_the_pronoun_is_never_the_name_of_a_thing(self, widget_company):
        """`I` is capitalised wherever it stands, so its capital says nothing."""
        assessment = widget_company.retriever.assess("how do I run procedure 3")
        assert "i" not in [word.lower() for word in assessment.named_topics]

    @pytest.mark.parametrize("question", [
        "how do I make a widget",
        "What do I press to make a widget?",
        "how do I adjust the lever",
        "Where is the hopper and how do I inspect it?",
    ])
    def test_ordinary_words_are_never_unseen_topics(self, widget_company, question):
        """The property the fix establishes, stated without the floor in the way.

        Whether such a question clears `MIN_CONFIDENT_SCORE` is a separate matter — that
        constant is calibrated against a 572-chunk corpus, and the class below records what
        it does to a smaller one. What must hold everywhere is that "how", "do", "I" and
        "make" are not treated as topics the documentation has never heard of.
        """
        assessment = widget_company.retriever.assess(question)
        assert assessment.unknown_terms == (), assessment.unknown_terms
        assert assessment.named_topics == ()

    def test_something_the_manual_does_not_cover_is_still_caveated(self, widget_company):
        assessment = widget_company.retriever.assess("how do I submit a slurm job")
        assert not assessment.confident
        assert "slurm" in [word.lower() for word in assessment.unknown_terms]

    def test_a_resource_the_manual_does_not_have_is_still_caveated(self, widget_company):
        assert not widget_company.retriever.assess(
            "what is the turbo procedure"
        ).confident

    def test_a_named_thing_is_still_caught_on_a_foreign_corpus(self, widget_company):
        """The classification is not RCC-specific either."""
        assert not widget_company.retriever.assess(
            "how do I make a widget on Frontera"
        ).confident


class TestTheThresholdsDoNotTravel:
    """What a second deployment inherits that it should re-measure, recorded as a fact.

    BM25 scores are unnormalised sums whose IDF term grows with the size of the corpus, so
    `MIN_CONFIDENT_SCORE = 20` means something different on 61 pages than on 572 chunks.
    Measured on this fixture: an on-topic question whose every word is in the manual scores
    about 15 and is caveated by the floor alone.

    Not a bug and not fixed here — moving a constant on the strength of a synthetic corpus is
    the overfitting `tools/gate_check.py --sweep` exists to argue against. It is written down
    because a new deployment reading `profiles/README.md` would otherwise meet it as "the
    assistant says it knows nothing", and `SAGE_MIN_CONFIDENT_SCORE` is the dial.
    """

    def test_an_on_topic_question_can_fall_below_the_shipped_floor(self, widget_company):
        from sage import config

        assessment = widget_company.retriever.assess("how do I adjust the lever")
        assert assessment.unknown_terms == ()
        assert assessment.top_score < config.MIN_CONFIDENT_SCORE, (
            "the smaller corpus now clears the shipped floor — re-measure and update "
            "profiles/README.md, because the caveat this documents no longer fires"
        )

    def test_lowering_the_floor_for_that_deployment_answers_it(self, widget_company):
        """The dial works, which is what makes the note in README.md actionable."""
        import dataclasses

        assessment = widget_company.retriever.assess("how do I adjust the lever")
        retuned = dataclasses.replace(assessment, min_confident_score=10.0)
        assert retuned.confident
