"""The card itself, which had no tests.

`tools/scorecard.py` is the answer to "how is this project doing" — four axes in one
table, and `--against` diffs it with the last one. Every input it reads is tested
somewhere: the gate in `test_gate_eval.py`, corpus health in `test_corpus_health.py`,
retrieval in `test_retrieval_eval.py`, the per-turn records in `test_bench_harness.py`.
The assembly was not, and it is the step that decides what a reader of the card believes.

Two things it must get right and had no way of being held to. A cell nobody measured has
to print `unmeasured` rather than being dropped — a missing row reads as "fine". And a row
has to say which of the app's two answering paths it describes, because `agents.json` can
now hold both for one model, and the diff used to key on the model alone: a grounded row
and a tool row collided, one silently replaced the other, and the surviving comparison was
across two different paths through the app.
"""

from __future__ import annotations

import json

import pytest

from tools import scorecard

REQUIRED = (
    "model", "n", "answered", "empty", "searched", "read", "cited_gold", "rounds",
    "calls", "first_text_p50", "seconds_p95", "defects_per_answer", "refusal_correct",
)


def agent_row(**overrides) -> dict:
    base = {
        "model": "opencode:m", "n": 10, "answered": 1.0, "empty": 0.0,
        "searched": 1.0, "read": 1.0, "cited_gold": 0.9, "rounds": 3.0, "calls": 3.0,
        "first_text_p50": 4.0, "seconds_p95": 9.0, "defects_per_answer": 0.0,
        "refusal_correct": 1.0, "path": "tools",
    }
    return base | overrides


@pytest.fixture(scope="module")
def card():
    """The real card, from the report files this repository ships. 1.7 seconds."""
    return scorecard.build_card(with_suite=False, with_layout=False)


class TestTheShippedCardAssembles:
    def test_every_axis_has_a_cell(self, card):
        for key in ("retrieval", "gate", "corpus", "agents"):
            assert key in card, key

    def test_what_was_not_run_says_unmeasured_rather_than_going_missing(self, card):
        """Built without `--with-suite` or `--with-layout`, so those two are unmeasured.

        The contract that matters: a cell nobody measured is present and says so. Dropping
        it reads as a clean card, which is how an unrun check comes to look like a passing
        one.
        """
        assert card["suite"] == scorecard.UNMEASURED
        assert card["layout"] == scorecard.UNMEASURED

    def test_every_shipped_row_says_which_path_it_describes(self, card):
        """Read with `.get`, so an `agents.json` predating the field still loads.

        This used to assert the shipped file was *all* tool-path rows, which was true when
        it was written and stopped being true the day the grounded arm was run — a test
        pinned to a fixture rather than to the property. The property is that every row
        names an arm, and that a row without the key is read as the tool loop, because
        when those runs were made there was nothing else to run them down.
        """
        rows = card["agents"]["models"]
        assert rows, "the shipped agents.json should have model rows"
        assert {row["path"] for row in rows} <= {"tools", "grounded", "mixed"}
        without = dict(rows[0])
        without.pop("path", None)
        assert scorecard._row_label(without).startswith(without["model"][:8])
        assert "[" not in scorecard._row_label(without)

    def test_every_field_the_table_prints_survives_into_the_card(self, card):
        for row in card["agents"]["models"]:
            for key in REQUIRED:
                assert key in row, f"{key} missing from a card row"


def with_agents(card: dict, rows: list[dict]) -> dict:
    """The real card with a synthetic Axis-B section.

    Built from the real one rather than invented: `report` and `report_against` read the
    other three axes too, and a hand-made stub would be testing a card shape the tool
    never produces. Only the part under test is replaced.
    """
    return card | {
        "agents": {"models": rows, "conversations": [], "injections": []}
    }


class TestARowSaysWhichPathItDescribes:
    def test_a_tool_row_prints_the_model_name_alone(self, card, capsys):
        scorecard.report(with_agents(card, [agent_row()]))
        printed = capsys.readouterr().out
        assert "opencode:m " in printed
        assert "[tools]" not in printed

    def test_a_grounded_row_is_labelled(self, card, capsys):
        scorecard.report(with_agents(card, [agent_row(path="grounded")]))
        assert "opencode:m [grounded]" in capsys.readouterr().out

    def test_the_label_survives_a_real_model_key(self, card, capsys):
        """The bug this test's own fixture was hiding.

        `opencode:nemotron-3.5-lightning-free` is 36 characters, the cell is 34, and the
        arm was appended *before* truncation — so the grounded row and the tool row for
        that model printed as the same string, which is the one thing `path` exists to
        prevent. A short fake model name never reached the truncation.
        """
        real = "opencode:nemotron-3.5-lightning-free"
        scorecard.report(with_agents(card, [
            agent_row(model=real),
            agent_row(model=real, path="grounded", answered=0.6),
        ]))
        printed = capsys.readouterr().out
        assert "[grounded]" in printed
        rows = [line for line in printed.splitlines() if "nemotron" in line]
        assert len(rows) == 2
        assert rows[0].split()[0] != rows[1].split()[0] or "[grounded]" in rows[1]

    def test_every_suffixed_row_keeps_its_suffix(self, card, capsys):
        """`(uploads)`, `(itself)`, `(follow-up)` say what the row measures."""
        real = "opencode:nemotron-3.5-lightning-free"
        scorecard.report(card | {"agents": {
            "models": [agent_row(model=real)],
            "conversations": [{"model": real, "turns": 4, "first_turn_gold": 1.0,
                               "follow_up_gold": 0.9, "answered": 1.0, "defects": 0,
                               "question_always_sent": True, "peak_request_chars": 10}],
            "injections": [{"model": real, "n": 6, "obeyed": 0, "leaked": 0,
                            "answered": 6}],
            "meta": [meta_row(model=real)],
        }})
        printed = capsys.readouterr().out
        for suffix in ("(follow-up)", "(uploads)", "(itself)"):
            assert suffix in printed, suffix

    def test_both_arms_appear_as_two_rows(self, card, capsys):
        scorecard.report(
            with_agents(card, [agent_row(), agent_row(path="grounded", answered=0.6)])
        )
        printed = capsys.readouterr().out
        assert "100% answered" in printed
        assert "60% answered" in printed


class TestTheDiffComparesLikeWithLike:
    """`report_against` keyed on the model alone, so the two arms overwrote each other."""

    def saved(self, card, tmp_path, rows: list[dict]) -> str:
        path = tmp_path / "before.json"
        path.write_text(json.dumps(with_agents(card, rows)))
        return str(path)

    def test_a_change_within_one_arm_is_reported(self, card, tmp_path, capsys):
        before = self.saved(card, tmp_path, [agent_row(answered=1.0)])
        scorecard.report_against(
            with_agents(card, [agent_row(answered=0.5)]), before
        )
        assert "answered: 100% -> 50%" in capsys.readouterr().out

    def test_the_two_arms_are_not_compared_against_each_other(
        self, card, tmp_path, capsys
    ):
        """The bug: same model, different paths, and the diff read one as the other.

        `answered 100% -> 60%` looks like news about a provider. It was news about which
        code answered the question.
        """
        before = self.saved(card, tmp_path, [agent_row(answered=1.0)])
        scorecard.report_against(
            with_agents(card, [agent_row(path="grounded", answered=0.6)]), before
        )
        printed = capsys.readouterr().out
        assert "100% -> 60%" not in printed
        assert "new model: opencode:m [grounded]" in printed
        assert "GONE from the lineup: opencode:m" in printed

    def test_both_arms_present_on_both_sides_are_each_compared_to_themselves(
        self, card, tmp_path, capsys
    ):
        before = self.saved(card, tmp_path, [
            agent_row(answered=1.0),
            agent_row(path="grounded", answered=1.0),
        ])
        scorecard.report_against(with_agents(card, [
            agent_row(answered=0.9),
            agent_row(path="grounded", answered=0.8),
        ]), before)
        printed = capsys.readouterr().out
        assert "opencode:m.answered: 100% -> 90%" in printed
        assert "opencode:m [grounded].answered: 100% -> 80%" in printed
        assert "new model" not in printed
        assert "GONE" not in printed

    def test_a_saved_card_from_before_the_field_existed_still_diffs(
        self, card, tmp_path, capsys
    ):
        """`report/agents.json` and `agents-before.json` both predate the field."""
        old = agent_row(answered=1.0)
        del old["path"]
        before = self.saved(card, tmp_path, [old])
        scorecard.report_against(
            with_agents(card, [agent_row(answered=0.5)]), before
        )
        printed = capsys.readouterr().out
        assert "answered: 100% -> 50%" in printed
        assert "new model" not in printed


def meta_row(**overrides) -> dict:
    base = {
        "model": "opencode:m", "path": "tools", "n": 22, "n_probes": 16,
        "n_answerable": 6, "held": 1.0, "kept": 1.0, "unaided": 1.0, "caught": 0,
        "disclosed": 0, "leaked": 0, "stonewalled": 0, "narrated": 0, "answered": 1.0,
        "names": [],
    }
    return base | overrides


def with_meta(card: dict, rows: list[dict]) -> dict:
    return card | {
        "agents": {
            "models": [agent_row()], "conversations": [], "injections": [], "meta": rows
        }
    }


class TestTheSelfDisclosureCell:
    """Both numbers on one line, because either alone reads as solved.

    A model that answers every probe with "I'm not able to discuss that" scores 100% held
    and would look perfect in a cell that printed `held` on its own.
    """

    def test_an_unrun_phase_says_unmeasured(self, card, capsys):
        scorecard.report(with_meta(card, []))
        printed = capsys.readouterr().out
        assert "asked about itself" in printed
        assert scorecard.UNMEASURED in printed

    def test_it_prints_held_alongside_kept_and_what_got_out(self, card, capsys):
        scorecard.report(with_meta(card, [
            meta_row(held=0.94, unaided=0.81, kept=1.0, caught=2, names=["search_docs"])
        ]))
        printed = capsys.readouterr().out
        assert "94% held" in printed
        assert "81% unaided" in printed
        assert "100% of 6 ordinary questions kept" in printed
        assert "2 redacted" in printed
        assert "search_docs" in printed

    def test_a_card_written_before_this_phase_existed_still_assembles(self, card, capsys):
        """`report/agents.json` from an older run has no `meta` key at all."""
        older = card | {"agents": {"models": [agent_row()], "conversations": []}}
        scorecard.report(older)
        assert "asked about itself" in capsys.readouterr().out

    def test_a_half_with_nothing_in_it_says_unmeasured(self, card, capsys):
        """A model that spent its allowance answered none of one half. 0% would be a lie."""
        scorecard.report(with_meta(card, [meta_row(held=1.0, kept=None)]))
        printed = capsys.readouterr().out
        assert f"{scorecard.UNMEASURED} of 6 ordinary questions kept" in printed

    def test_the_diff_reports_a_name_that_newly_got_out(self, card, tmp_path, capsys):
        """A membership diff, because a count that stood still is not a run that did.

        `held` unchanged while the name changes from a tool to the model it runs on is a
        different hole, and the number cannot say so.
        """
        path = tmp_path / "before.json"
        path.write_text(json.dumps(with_meta(card, [meta_row(names=["search_docs"])])))
        scorecard.report_against(
            with_meta(card, [meta_row(held=0.9, names=["nemotron"])]), str(path)
        )
        printed = capsys.readouterr().out
        assert "self.held: 100% -> 90%" in printed
        assert "NEWLY disclosed by opencode:m: nemotron" in printed
        assert "no longer disclosed by opencode:m: search_docs" in printed


class TestAnUploadRowWithNoAnswersInIt:
    """"held, obeyed 0/5" over five provider refusals is a green line for zero data.

    Produced for real the day a free allowance ran out mid-session. The card's whole
    contract is that an unmeasured cell says so.
    """

    def upload_row(self, **overrides) -> dict:
        base = {"model": "opencode:m", "path": "tools", "n": 5, "obeyed": 0,
                "leaked": 0, "answered": 5}
        return base | overrides

    def with_uploads(self, card: dict, rows: list[dict]) -> dict:
        return card | {
            "agents": {"models": [agent_row()], "conversations": [], "injections": rows}
        }

    def test_a_measured_run_still_says_held(self, card, capsys):
        scorecard.report(self.with_uploads(card, [self.upload_row()]))
        printed = capsys.readouterr().out
        assert "(uploads)" in printed and "held" in printed

    def test_a_run_that_answered_nothing_says_unmeasured(self, card, capsys):
        scorecard.report(self.with_uploads(card, [self.upload_row(answered=0)]))
        printed = capsys.readouterr().out
        assert "0 of 5 turns answered" in printed
        assert scorecard.UNMEASURED in printed

    def test_a_row_from_before_the_field_existed_is_read_as_measured(self, card, capsys):
        """Every `agents.json` this repository has shipped predates `answered` here."""
        old = self.upload_row()
        del old["answered"]
        scorecard.report(self.with_uploads(card, [old]))
        assert "held" in capsys.readouterr().out
