"""The refusal gate, ratcheted. Offline, deterministic, and the one axis worth gating.

Every hallucination this app can commit passes through `Assessment.confident`: a
caveat tells the model to decline, and its absence hands over six confident-looking
sections. `tests/test_retrieval.py::TestAssessment` pins the two thresholds on ten
labelled probes, all six of whose negatives are lexically alien ("sourdough",
"PI-RADS", "weather") and score at most 23.9 against a `STRONG_SCORE` of 26 — caught by
the score floor alone. This file adds the class none of them cover: a question in
fluent RCC dialect about something the RCC does not have, which scores 26–64.

The numbers are low and they are the measurement, not the target. `tools/gate_check.py`
prints them, `tools/gate_check.py --sweep` shows that no threshold pair fixes them, and
the ratchets below sit one case under what the tree measures today so a single
regression fails and the slack is stated rather than hidden.
"""

from __future__ import annotations

import pytest

import evals
from evals import gate

# Measured on the tree that introduced this file. One case is 2.6pp on the negative
# split and 1.3pp on the answerable one, so each ratchet is one case of slack.
#
# Raise them when the gate improves; never lower one to make CI pass. 36.8% is not an
# acceptable level, it is where this started — see EVAL.md.
MINIMUM_CAVEAT_RECALL = 0.34    # measured 0.368 (14 of 38)
MAXIMUM_OVER_REFUSAL = 0.04     # measured 0.026 (2 of 77)
MINIMUM_RECALL_AT_5 = 0.96      # measured 0.985


@pytest.fixture(scope="module")
def blob(real_corpus):
    return gate.haystack(real_corpus)


@pytest.fixture(scope="module")
def audited(blob):
    return gate.audit(evals.negatives(), blob)


@pytest.fixture(scope="module")
def measured(real_index, audited):
    return gate.measure(
        real_index, audited, evals.questions(), evals.identifiers()
    )


class TestTheLabels:
    """The dataset is a set of claims about the corpus, and they are checked.

    A negative says "these words appear nowhere in the documentation". That claim rots:
    the User Guide gains a page and a fair negative becomes a question the app is being
    punished for answering correctly. Written from memory, eight of the first
    forty-one were wrong — `gpu2` is a real Midway2 partition with K80s, EC2 is
    documented because Skyway bursts to AWS, and the compilers page names Julia. All
    eight were caught here rather than by a number that quietly moved.
    """

    def test_every_negative_label_holds(self, audited):
        suspect = [
            f"{case.text!r} (corpus mentions {list(case.found)})"
            for case in audited
            if case.suspect
        ]
        assert not suspect, "mislabelled negatives: " + "; ".join(suspect)

    def test_every_negative_names_what_makes_it_one(self):
        """No `absent` tokens means the label cannot be checked at all."""
        unverifiable = [case.text for case in evals.negatives() if not case.absent]
        assert not unverifiable, (
            "negatives with nothing to audit: " + "; ".join(unverifiable)
        )

    def test_gold_pages_exist_in_the_corpus(self, real_corpus):
        known = {chunk.path for chunk in real_corpus.chunks}
        missing = [
            f"{case.text!r} -> {page}"
            for case in evals.questions()
            for page in case.pages
            if page not in known
        ]
        assert not missing, "gold pages that are not indexed: " + "; ".join(missing)

    def test_the_two_sides_do_not_overlap(self):
        asked = {case.text for case in evals.questions()}
        refused = {case.text for case in evals.negatives()}
        assert not asked & refused


class TestTheGate:
    def test_caveat_recall_has_not_regressed(self, measured):
        score = measured["caveat_recall"]
        assert score >= MINIMUM_CAVEAT_RECALL, f"caveat recall fell to {score:.1%}"

    def test_answerable_questions_are_not_refused(self, measured):
        score = measured["over_refusal"]
        assert score <= MAXIMUM_OVER_REFUSAL, f"over-refusal rose to {score:.1%}"

    def test_gold_pages_are_still_retrieved(self, measured):
        score = measured["recall@5"]
        assert score >= MINIMUM_RECALL_AT_5, f"recall@5 fell to {score:.1%}"

    def test_an_unseen_identifier_never_refuses_an_answerable_question(self, measured):
        """The trap on the other side, and the one this must never trade away.

        A job number, a CNetID, a daemon in an error message: every one of these was
        refused by the first version of the weak-retrieval idea, which is what made it
        unusable. A fix aimed at the leaks that brings this back has made things worse.
        """
        refused = [row["question"] for row in measured["rows"]["identifiers"]
                   if row["refused"]]
        assert not refused, "refused over an identifier: " + "; ".join(refused)


class TestWhatLeaksToday:
    """The leaks, one test each, as xfails.

    Named rather than aggregated, because a count says the gate is weak and a list says
    which questions it is weak on — and because an xpass is how this file reports that
    one of them has been fixed. `strict=False`: a fix is good news, not a failure.
    """

    LEAKING = [
        "how do I submit a job on Frontera",
        "how do I run Jupyter on the Delta cluster",
        "what is the queue structure on Stampede3",
        "how do I get an allocation on Bridges-2",
        "how do I load modules on Perlmutter",
        "is there a scratch purge policy on Expanse",
        "how many GPUs per node does Midway4 have",
        "how do I connect to Midway5",
        "what is the memory limit on the bigmem3 partition",
        "what is the quota on scratch2",
        "how many nodes does Beagle4 have",
        "how do I submit to the turbo partition",
        "how do I submit a job with qsub",
        "how do I check the queue with bjobs",
        "how do I write PBS directives in my job script",
        "how do I submit with condor_submit",
        "how do I load the ANSYS Fluent module",
        "how do I run VASP on Beagle3",
        "can I get a static public IP for my desktop from RCC",
        "what does a service unit cost for an external collaborator",
        "what is the penalty for sharing my CNetID password",
        "how do I renew my parking permit",
        "how do I book a study room in the library",
        "how do I enrol in a computer science course",
    ]

    @pytest.mark.parametrize("question", LEAKING, ids=LEAKING)
    @pytest.mark.xfail(reason="known refusal-gate leak", strict=False)
    def test_it_should_be_caveated(self, real_index, question):
        assert not real_index.assess(question).confident

    def test_the_list_is_still_the_whole_list(self, measured):
        """No leak may appear that is not written down above.

        The ratchet catches the aggregate moving. This catches the aggregate holding
        still while the *membership* changes — a new leak arriving as an old one is
        fixed, which is the shape a refactor produces and the shape a percentage hides.
        """
        leaking = {
            row["question"] for row in measured["rows"]["negatives"] if row["leaked"]
        }
        surprises = sorted(leaking - set(self.LEAKING))
        assert not surprises, "new leaks, not in the recorded list: " + "; ".join(surprises)


def test_no_threshold_pair_separates_the_two_sides(real_index, audited):
    """Why the fix is not a number, kept as an executable claim.

    Moving `MIN_CONFIDENT_SCORE` and `STRONG_SCORE` is the obvious response to a leak
    and it cannot work: the leaks score 26–64 and answerable questions score 18–126, so
    every pair that catches the leaks refuses real questions in about equal measure. If
    this test ever fails, the score distributions have separated and a threshold change
    IS the fix — which would be worth knowing immediately.
    """
    swept = gate.sweep(
        real_index, audited, evals.questions(), evals.identifiers()
    )
    usable = [
        point for point in swept["front"]
        if point["caveat_recall"] >= 0.9 and point["answerable_kept"] >= 0.95
    ]
    assert not usable, (
        "a threshold pair now separates the two sides: " + str(usable[:3])
    )
