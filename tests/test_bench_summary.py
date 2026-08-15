"""The aggregation step, which had no tests and is where the numbers come from.

`tests/test_bench_harness.py` calibrates one turn: rounds, searches, outcome, evidence.
Nothing calibrated what happens to a *set* of turns on the way to a table — and that is
the step the card quotes. `summarise` and `rescore` between them decide what a row means,
and both grouped on the model alone.

That was survivable while the app had one answering path. It stopped being survivable the
moment `--toolless` made the second one runnable, because `transcripts.jsonl` is opened in
**append** mode: two runs into one `--out` directory accumulate in one file, and a row
averaged over three tool-loop turns and three grounded ones reported `srch 50%  rnd 2.0`.
Neither arm searches half the time and neither takes two rounds. Worse, it hid a real
difference — `gold 33%` on the tool path against `100%` on the grounded one, blended to a
67% that described nothing.
"""

from __future__ import annotations

import json

import pytest

from tools import agent_bench


def record(**overrides) -> dict:
    """One turn's record, with only the fields `summarise` reads."""
    base = {
        "model": "opencode:m", "path": "tools", "outcome": "answered",
        "expect": "answer", "error_kind": "", "tool_calls": [],
        "defects": [], "warnings": [], "findings": [], "defect_count": 0,
        "pages": ["slurm/sbatch.md"], "source_pages": ["slurm/sbatch.md"],
        "searches": 1, "reads": 1, "rounds": 3, "provider_calls": 3,
        "read_errors": 0, "first_text": 0.5, "seconds": 1.0, "queries": ["sbatch"],
        "question": "how do I submit a batch job",
    }
    return base | overrides


GROUNDED = {"path": "grounded", "searches": 0, "reads": 0, "rounds": 1,
            "provider_calls": 1, "tool_calls": [], "queries": []}


class TestASummaryKnowsWhichPathItDescribes:
    def test_a_tool_run_is_labelled_as_one(self, real_index):
        row = agent_bench.summarise("opencode:m", [record()], real_index)
        assert row["path"] == "tools"

    def test_a_grounded_run_is_labelled_as_one(self, real_index):
        rows = [record(**GROUNDED) for _ in range(3)]
        row = agent_bench.summarise("opencode:m", rows, real_index)
        assert row["path"] == "grounded"
        assert row["searched"] == 0
        assert row["rounds"] == 1

    def test_being_handed_both_says_mixed_rather_than_averaging_quietly(
        self, real_index
    ):
        """The self-check. A row that covers two architectures must not look like one.

        It still reports the blended arithmetic — throwing the turns away would lose data
        somebody paid for — but it says `mixed`, so the number cannot be read as either
        arm's.
        """
        rows = [record(), record(), record(), *[record(**GROUNDED) for _ in range(3)]]
        row = agent_bench.summarise("opencode:m", rows, real_index)
        assert row["path"] == "mixed"
        assert row["n"] == 6

    def test_a_record_from_before_the_field_existed_counts_as_the_tool_path(
        self, real_index
    ):
        """Which is what those runs were: there was no other path to run them down."""
        old = record()
        del old["path"]
        assert agent_bench.summarise("opencode:m", [old], real_index)["path"] == "tools"

    def test_a_crashed_turn_carries_the_arm_it_was_run_on(self):
        """`crashed_record` had no `path` at all, so an all-crashed grounded run
        summarised as a tool run — and a partly-crashed one as `mixed`."""
        crashed = agent_bench.crashed_record(
            "q", "opencode:m", "answer", (), (), RuntimeError("boom"), 0.0,
            toolless=True,
        )
        assert crashed["path"] == "grounded"
        assert agent_bench.crashed_record(
            "q", "opencode:m", "answer", (), (), RuntimeError("boom"), 0.0
        )["path"] == "tools"


class TestRescoreSplitsTheArms:
    """The integration point: one transcript file, two arms, two rows."""

    @pytest.fixture(scope="class")
    def rescored(self, tmp_path_factory):
        path = tmp_path_factory.mktemp("bench") / "transcripts.jsonl"
        rows = [record(text="Use `sbatch`.", raw="Use `sbatch`.", sources=[],
                       evidence={}, must_mention=[])
                for _ in range(3)]
        rows += [record(text="Use `sbatch`.", raw="Use `sbatch`.", sources=[],
                        evidence={}, must_mention=[], **GROUNDED)
                 for _ in range(3)]
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        return agent_bench.rescore(str(path))

    def test_it_reports_two_rows_not_one_blend(self, rescored):
        assert len(rescored["models"]) == 2

    def test_each_row_describes_one_arm(self, rescored):
        by_arm = {row["path"]: row for row in rescored["models"]}
        assert set(by_arm) == {"tools", "grounded"}
        assert by_arm["tools"]["n"] == 3
        assert by_arm["grounded"]["n"] == 3
        assert by_arm["tools"]["searched"] == 1.0
        assert by_arm["grounded"]["searched"] == 0.0

    def test_no_row_is_mixed(self, rescored):
        """If a row came out `mixed`, the bucketing did not take."""
        assert not [row for row in rescored["models"] if row["path"] == "mixed"]


class TestTheReportedTableIsUnchangedForAToolRun:
    """The arm is printed only when it is not the default, so nothing else moves."""

    def test_a_tool_row_prints_the_model_name_alone(self, capsys, real_index):
        agent_bench.report(
            {"models": [agent_bench.summarise("opencode:m", [record()], real_index)]}
        )
        printed = capsys.readouterr().out
        assert "opencode:m " in printed
        assert "[tools]" not in printed

    def test_a_grounded_row_says_so(self, capsys, real_index):
        agent_bench.report({"models": [
            agent_bench.summarise("opencode:m", [record(**GROUNDED)], real_index)
        ]})
        assert "opencode:m [grounded]" in capsys.readouterr().out
