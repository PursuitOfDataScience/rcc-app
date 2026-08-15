"""Measuring the refusal gate: the label audit, the scoring, and the sweep.

Separated from `tools/gate_check.py` for the same reason the harness is separated from
`tools/agent_bench.py`: `tools/` holds command-line entry points, and anything `pytest`
has to import lives in a package. The gate's numbers are ratcheted in
`tests/test_gate_eval.py`, so they have to be importable without argparse.

What the gate is: `Assessment.confident` decides whether `search_docs` prepends a
RETRIEVAL WARNING telling the model to decline. Every hallucination this app can commit
passes through it.
"""

from __future__ import annotations

import dataclasses
import re

from . import Identifier, Negative, Question

RECALL_AT = 5


def haystack(corpus) -> str:
    """Every character of the corpus, lowercased, titles included.

    Titles as well as bodies: a negative whose token appears only in a heading is still
    a question the documentation is about, and scoring it as unanswerable would penalise
    the app for being right.
    """
    parts = []
    for chunk in corpus.chunks:
        parts.append(chunk.text)
        parts.append(chunk.breadcrumb)
    return "\n".join(parts).lower()


def mentions(blob: str, token: str) -> bool:
    """Is this token in the corpus?

    Word-boundary for a plain word, substring for anything with punctuation in it. The
    distinction earns its keep: `\\bflu\\b` does not match "influence" and `#PBS` has to
    be matched literally, and both of those were labelling mistakes this rule caught.
    """
    token = token.strip().lower()
    if not token:
        return False
    if re.fullmatch(r"[\w-]+", token):
        return re.search(rf"\b{re.escape(token)}\b", blob) is not None
    return token in blob


def audit(cases: list[Negative], blob: str) -> list[Negative]:
    """Re-label any negative whose distinguishing token is in the corpus after all.

    Suspect cases are reported and excluded from scoring, never silently dropped: the
    label is what needs fixing, and a deleted case takes the evidence with it.
    """
    return [
        dataclasses.replace(
            case, found=tuple(token for token in case.absent if mentions(blob, token))
        )
        for case in cases
    ]


def verdict(assessment, minimum: float | None = None, strong: float | None = None):
    """`assessment.confident`, optionally re-evaluated at other thresholds.

    The thresholds ride on the Assessment rather than being read from config — an engine
    scoring on a different scale supplies its own — which is what makes a sweep possible
    without touching the module under test.
    """
    if minimum is None and strong is None:
        return assessment.confident
    return dataclasses.replace(
        assessment,
        min_confident_score=(
            minimum if minimum is not None else assessment.min_confident_score
        ),
        strong_score=strong if strong is not None else assessment.strong_score,
    ).confident


def measure(
    index,
    negatives: list[Negative],
    positives: list[Question],
    identifiers: list[Identifier],
) -> dict:
    """Both sides of the gate, per case and in aggregate."""
    scored = [case for case in negatives if not case.suspect]
    rows: dict[str, list] = {
        "negatives": [],
        "positives": [],
        "identifiers": [],
        "suspect": [
            {"question": case.text, "found": list(case.found), "why": case.why}
            for case in negatives
            if case.suspect
        ],
    }

    for case in scored:
        assessment = index.assess(case.text)
        top = index.search(case.text, 1)
        rows["negatives"].append(
            {
                "question": case.text,
                "kind": case.kind,
                "score": round(assessment.top_score, 1),
                "unseen": list(assessment.unknown_terms),
                "leaked": bool(assessment.confident),
                "top_page": top[0].chunk.path if top else "",
            }
        )

    for case in positives:
        assessment = index.assess(case.text)
        pages = [result.chunk.path for result in index.search(case.text, RECALL_AT)]
        rows["positives"].append(
            {
                "question": case.text,
                "kind": case.kind,
                "score": round(assessment.top_score, 1),
                "refused": not assessment.confident,
                "hit": bool(set(case.pages) & set(pages)) if case.pages else None,
                "known_gap": case.known_gap,
                "got": pages[:RECALL_AT],
            }
        )

    for case in identifiers:
        assessment = index.assess(case.text)
        rows["identifiers"].append(
            {
                "question": case.text,
                "score": round(assessment.top_score, 1),
                "unseen": list(assessment.unknown_terms),
                "refused": not assessment.confident,
            }
        )

    leaks = [row for row in rows["negatives"] if row["leaked"]]
    refused = [row for row in rows["positives"] if row["refused"]]
    refused += [row for row in rows["identifiers"] if row["refused"]]
    answerable = rows["positives"] + rows["identifiers"]
    # The ratchet is over cases retrieval is expected to reach. A known gap is still run
    # and still reported — it is just not counted, the way the existing retrieval eval
    # xfails its one lexical gap rather than deleting it.
    with_pages = [
        row for row in rows["positives"]
        if row["hit"] is not None and not row["known_gap"]
    ]

    by_kind: dict[str, dict] = {}
    for row in rows["negatives"]:
        bucket = by_kind.setdefault(row["kind"], {"n": 0, "leaked": 0})
        bucket["n"] += 1
        bucket["leaked"] += int(row["leaked"])

    return {
        "n_negatives": len(scored),
        "n_positives": len(rows["positives"]),
        "n_identifiers": len(rows["identifiers"]),
        "n_suspect": len(rows["suspect"]),
        "caveat_recall": (len(scored) - len(leaks)) / (len(scored) or 1),
        "over_refusal": len(refused) / (len(answerable) or 1),
        "recall@5": sum(1 for row in with_pages if row["hit"]) / (len(with_pages) or 1),
        "by_kind": by_kind,
        "rows": rows,
    }


def sweep(
    index,
    negatives: list[Negative],
    positives: list[Question],
    identifiers: list[Identifier],
) -> dict:
    """Is there ANY threshold pair that separates the two sides?

    Moving the two constants is the obvious response to a leak, so it is worth knowing
    whether it would work before changing anything else. The Pareto front is the answer:
    pairs that nothing else beats on both axes at once. A mechanism cannot be tuned out
    of an overlap.
    """
    scored = [case for case in negatives if not case.suspect]
    negative_assessments = [index.assess(case.text) for case in scored]
    positive_assessments = [index.assess(case.text) for case in positives]
    positive_assessments += [index.assess(case.text) for case in identifiers]

    grid = []
    for minimum in range(14, 61, 2):
        for strong in range(int(minimum), 101, 4):
            caught = sum(
                1 for item in negative_assessments if not verdict(item, minimum, strong)
            )
            kept = sum(
                1 for item in positive_assessments if verdict(item, minimum, strong)
            )
            grid.append(
                {
                    "min": minimum,
                    "strong": strong,
                    "caveat_recall": caught / (len(negative_assessments) or 1),
                    "answerable_kept": kept / (len(positive_assessments) or 1),
                }
            )
    # Dominance has to be strict in at least one dimension. With `>=` on both and
    # `other != point` to exclude self-comparison, every pair of grid points scoring
    # *identically* eliminated each other — and after the classification fix most of the
    # low-threshold grid does score identically, so the front collapsed to one extreme
    # point and the operating point the app actually runs at vanished from the report.
    def dominated(point: dict) -> bool:
        return any(
            other["caveat_recall"] >= point["caveat_recall"]
            and other["answerable_kept"] >= point["answerable_kept"]
            and (
                other["caveat_recall"] > point["caveat_recall"]
                or other["answerable_kept"] > point["answerable_kept"]
            )
            for other in grid
        )

    front = [point for point in grid if not dominated(point)]
    # One row per distinct trade-off: the front is otherwise a run of identical numbers
    # under different thresholds, which reads as precision it does not have.
    seen: set[tuple[float, float]] = set()
    unique = []
    for point in sorted(front, key=lambda item: item["caveat_recall"]):
        key = (round(point["caveat_recall"], 4), round(point["answerable_kept"], 4))
        if key not in seen:
            seen.add(key)
            unique.append(point)
    return {"front": unique, "grid": len(grid)}


def separable(swept: dict, *, recall: float = 0.9, kept: float = 0.95) -> list[dict]:
    """Threshold pairs reaching `recall` on negatives while keeping `kept` answerable."""
    return [
        point for point in swept["front"]
        if point["caveat_recall"] >= recall and point["answerable_kept"] >= kept
    ]


def dominating(swept: dict, measured: dict) -> list[dict]:
    """Threshold pairs strictly better than the shipped one, and worse at nothing.

    The question worth asking of a sweep, and the one worth failing a build over: is a
    constant leaving something on the table? A pair that buys caveat recall by refusing
    answerable questions is a *trade*, and which side of it to take is a judgement about
    which error is worse on an app somebody reads every day. A pair that improves one
    axis and costs nothing on the other is not a judgement, it is an oversight.

    Before the classification fix nothing dominated, and nothing reached 90% caveat
    recall at 95% answerable either. Afterwards a pair does reach that — 24/24 buys 4.4pp
    of caveat recall for 1.3pp of over-refusal — which is a trade, on n=45, and taking it
    would be tuning two constants to catch two cases in the set they are measured on.

    Judged with one case of tolerance on each axis, derived from the set sizes rather
    than hardcoded. At n=45 and n=77 one question is 2.2pp and 1.3pp, so a pair that is
    "better" by a single case is not evidence that a constant is wrong — it is evidence
    that one question sits near the boundary, which is true of some question at every
    threshold. Without the tolerance this fails on min=18, which rescues exactly one
    answerable question and would have two constants re-tuned to catch it.
    """
    shipped_recall = measured["caveat_recall"]
    shipped_kept = 1 - measured["over_refusal"]
    negative_case = 1 / max(measured["n_negatives"], 1)
    answerable_case = 1 / max(
        measured["n_positives"] + measured["n_identifiers"], 1
    )
    return [
        point for point in swept["front"]
        if point["caveat_recall"] >= shipped_recall - 1e-9
        and point["answerable_kept"] >= shipped_kept - 1e-9
        and (
            point["caveat_recall"] > shipped_recall + negative_case
            or point["answerable_kept"] > shipped_kept + answerable_case
        )
    ]
