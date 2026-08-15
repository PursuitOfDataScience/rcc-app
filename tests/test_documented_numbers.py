"""The figures `EVAL.md` states, checked against a live measurement.

This repository already learnt the lesson once, for retrieval: `tools/metrics.py` exists
because the eval's own docstring claimed "recall@3 94%" for a configuration that never
measured it, and a hand-written number nobody re-derives goes stale silently. Six passes of
edits later, `EVAL.md` said "77 answerable questions" over a set of 78, a ratchet comment
said "2 of 77", and `CLAUDE.md`'s test total had rotted three times.

So the headline figures are pinned here. Deliberately only the ones that move when the
*datasets or the gate* move — set sizes and the gate's three rates. A test count changes on
every commit that adds a test, so gating one would fail on every legitimate addition and
teach people to edit the number rather than read the failure; that total is no longer
written down anywhere.

A failure here means a document and the code disagree. Fix the document — or, if the code
moved on purpose, fix both and say so in the commit.
"""

from __future__ import annotations

import os
import re

import pytest

import evals
from evals import gate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_MD = os.path.join(ROOT, "EVAL.md")


@pytest.fixture(scope="module")
def prose() -> str:
    with open(EVAL_MD, encoding="utf-8") as handle:
        return handle.read()


@pytest.fixture(scope="module")
def measured(real_index, real_corpus):
    negatives = gate.audit(evals.negatives(), gate.haystack(real_corpus))
    return gate.measure(
        real_index, negatives, evals.questions(), evals.identifiers()
    )


class TestTheSetSizes:
    """`EVAL.md` states these in the sentence reporting the gate's result."""

    def test_the_negative_count_is_current(self, prose, measured):
        stated = re.search(r"Result on (\d+) labelled negatives", prose)
        assert stated, "EVAL.md no longer states the negative count"
        assert int(stated.group(1)) == measured["n_negatives"], (
            f"EVAL.md says {stated.group(1)} negatives; the set has "
            f"{measured['n_negatives']}"
        )

    def test_the_answerable_count_is_current(self, prose, measured):
        stated = re.search(r"and (\d+) answerable questions", prose)
        assert stated, "EVAL.md no longer states the answerable count"
        live = measured["n_positives"] + measured["n_identifiers"]
        assert int(stated.group(1)) == live, (
            f"EVAL.md says {stated.group(1)} answerable questions; the set has {live}"
        )


class TestTheHeadlineRates:
    """The three numbers the card leads with, to one decimal place."""

    def rate(self, prose: str, pattern: str) -> float:
        found = re.search(pattern, prose)
        assert found, f"EVAL.md no longer states {pattern!r}"
        return float(found.group(1))

    def test_caveat_recall(self, prose, measured):
        stated = self.rate(prose, r"caveat recall 36\.8% →\s*\n?([\d.]+)%")
        assert stated == pytest.approx(measured["caveat_recall"] * 100, abs=0.05), (
            f"EVAL.md says {stated}% caveat recall; measured "
            f"{measured['caveat_recall']:.1%}"
        )

    def test_over_refusal(self, prose, measured):
        stated = self.rate(prose, r"over-refusal unchanged at ([\d.]+)%")
        assert stated == pytest.approx(measured["over_refusal"] * 100, abs=0.05), (
            f"EVAL.md says {stated}% over-refusal; measured {measured['over_refusal']:.1%}"
        )

    def test_recall_at_five(self, prose, measured):
        stated = self.rate(prose, r"recall@5 unchanged at ([\d.]+)%")
        assert stated == pytest.approx(measured["recall@5"] * 100, abs=0.05), (
            f"EVAL.md says {stated}% recall@5; measured {measured['recall@5']:.1%}"
        )


class TestTheRatchetsQuoteWhatTheyMeasure:
    """A ratchet's comment says what it measured. That comment is a number too.

    `MAXIMUM_OVER_REFUSAL = 0.04  # measured 0.026 (2 of 78)` — the denominator drifted to
    77 when a case was added, which is exactly how the retrieval eval's docstring came to
    claim a figure that had never been true of the code beside it.
    """

    def test_the_denominators_in_the_comments_are_current(self, measured):
        path = os.path.join(ROOT, "tests", "test_gate_eval.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        negatives = re.search(r"measured [\d.]+ \((\d+) of (\d+)\)", source)
        assert negatives, "the caveat-recall ratchet no longer quotes its measurement"
        assert int(negatives.group(2)) == measured["n_negatives"]

        answerable = re.search(r"measured 0\.0\d+ \((\d+) of (\d+)\)", source)
        assert answerable, "the over-refusal ratchet no longer quotes its measurement"
        live = measured["n_positives"] + measured["n_identifiers"]
        assert int(answerable.group(2)) == live, (
            f"the ratchet comment says {answerable.group(2)} answerable; the set has {live}"
        )

    def test_the_ratchets_still_sit_below_what_is_measured(self, measured):
        from tests import test_gate_eval as gate_eval  # noqa: PLC0415

        assert measured["caveat_recall"] >= gate_eval.MINIMUM_CAVEAT_RECALL
        assert measured["over_refusal"] <= gate_eval.MAXIMUM_OVER_REFUSAL
        assert measured["recall@5"] >= gate_eval.MINIMUM_RECALL_AT_5
