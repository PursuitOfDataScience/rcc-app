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

    def test_a_row_written_before_there_were_two_paths_counts_as_the_tool_loop(self, card):
        """The shipped `agents.json` has no `path` key in any of its rows.

        Read with `.get`, precisely so that file still loads: requiring the key would have
        crashed the whole card on the repository's own data. Absent means the tool loop,
        because when those runs were made there was nothing else to run them down.
        """
        rows = card["agents"]["models"]
        assert rows, "the shipped agents.json should have model rows"
        assert {row["path"] for row in rows} == {"tools"}

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
