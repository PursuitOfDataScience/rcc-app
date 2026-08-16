#!/usr/bin/env python3
"""The refusal gate, calibrated: does retrieval admit it is weak when it is?

This is the one number every hallucination this app can commit passes through. When
`search_docs` reports a caveat, the model is told to decline; when it does not, the model
is handed six confident-looking sections and left to its own judgement. Before this file
existed the boundary was pinned by ten labelled probes — six out-of-scope and four
in-scope-carrying-an-unseen-word — and all six negatives were *lexically* alien
("sourdough", "PI-RADS", "weather"), scoring at most 23.9 against a `STRONG_SCORE` of 26.
Every one was caught by the score floor alone.

The class nobody had tested was a question in fluent RCC dialect about something the RCC
does not have: another site's cluster, a partition that does not exist, a scheduler this
centre does not run. Those scored 26–64 and sailed straight through, 14 of 38 caveated.

It is 39 of 45 now, and not because a threshold moved: `--sweep` showed the two sides
occupying the same score range, so the fix distinguishes an unfamiliar word that *names a
thing* from one that *carries a value* (`sage/retrieval/text.py`). What remains leaking has
no unknown term at all — every word is in the corpus and only the fact is missing — which
is the boundary of the mechanism rather than a backlog.

    python tools/gate_check.py                  # the report
    python tools/gate_check.py --audit          # only the label audit
    python tools/gate_check.py --sweep          # can any threshold pair separate them?
    python tools/gate_check.py --save card.json --against previous.json

Nothing here needs a model, a key or the network. The measuring lives in `evals/gate.py`
so `pytest` can ratchet it; this file is the report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import evals  # noqa: E402
from evals import gate  # noqa: E402
from sage import corpus as corpus_mod  # noqa: E402
from sage import retrieval  # noqa: E402


def report(measured: dict, *, verbose: bool) -> None:
    print(f"negatives   n={measured['n_negatives']:3d}   "
          f"caveat recall {measured['caveat_recall']:6.1%}")
    print(f"answerable  n={measured['n_positives'] + measured['n_identifiers']:3d}   "
          f"over-refusal  {measured['over_refusal']:6.1%}")
    print(f"gold pages           recall@{gate.RECALL_AT}     {measured['recall@5']:6.1%}")

    if measured["n_suspect"]:
        print(f"\nSUSPECT LABELS ({measured['n_suspect']}) — excluded from scoring; "
              "the corpus mentions their supposedly-absent token")
        for row in measured["rows"]["suspect"]:
            print(f"   {row['question']!r}\n      found {row['found']}  ({row['why']})")

    print("\nby class")
    for kind, bucket in sorted(measured["by_kind"].items()):
        print(f"   {kind:22s} {bucket['n'] - bucket['leaked']}/{bucket['n']} caveated")

    leaks = [row for row in measured["rows"]["negatives"] if row["leaked"]]
    if leaks:
        print(f"\nLEAKS ({len(leaks)}) — passed as answerable")
        for row in sorted(leaks, key=lambda item: -item["score"]):
            print(f"   {row['score']:5.1f}  unseen={str(row['unseen']):26s} "
                  f"top={row['top_page']:28s} {row['question']!r}")

    refused = [row for row in measured["rows"]["positives"] if row["refused"]]
    refused += [row for row in measured["rows"]["identifiers"] if row["refused"]]
    if refused:
        print(f"\nOVER-REFUSED ({len(refused)}) — answerable, told to decline")
        for row in refused:
            print(f"   {row['score']:5.1f}  {row['question']!r}")

    missed = [
        row for row in measured["rows"]["positives"]
        if row["hit"] is False and not row["known_gap"]
    ]
    if missed:
        print(f"\nRETRIEVAL MISSES ({len(missed)}) — gold page outside the top "
              f"{gate.RECALL_AT}")
        for row in missed:
            print(f"   {row['question']!r}\n      got {row['got']}")

    gaps = [row for row in measured["rows"]["positives"] if row["known_gap"]]
    if gaps:
        print(f"\nknown gaps ({len(gaps)}) — reported, not counted")
        for row in gaps:
            print(f"   {'NOW PASSES' if row['hit'] else 'still missing'}: "
                  f"{row['question']!r}")
        if any(row["hit"] for row in gaps):
            print("   -> a gap that now passes is a gap to promote, not to leave here")

    if verbose:
        print("\nscore ranges")
        for name in ("negatives", "positives", "identifiers"):
            scores = sorted(row["score"] for row in measured["rows"][name])
            if scores:
                print(f"   {name:12s} min {scores[0]:5.1f}  "
                      f"median {scores[len(scores) // 2]:5.1f}  max {scores[-1]:5.1f}")


def _by_how_much(swept: dict, measured: dict) -> str:
    """Why the operating point is off the front, in questions rather than percentages.

    "Dominated" on its own reads as an error. It is usually one question: at n=45 and n=78
    a single case is 2.2pp and 1.3pp, and `gate.dominating` deliberately ignores a
    one-case gain for exactly that reason. Saying which pair and by how much is the
    difference between a number a reader can act on and an alarm.
    """
    negatives = max(measured["n_negatives"], 1)
    answerable = max(measured["n_positives"] + measured["n_identifiers"], 1)
    kept = 1 - measured["over_refusal"]
    better = [
        (
            round((point["caveat_recall"] - measured["caveat_recall"]) * negatives),
            round((point["answerable_kept"] - kept) * answerable),
            point,
        )
        for point in swept["front"]
        if point["caveat_recall"] >= measured["caveat_recall"] - 1e-9
        and point["answerable_kept"] >= kept - 1e-9
    ]
    if not better:
        return ""
    caveats, answers, point = max(better, key=lambda row: row[0] + row[1])
    gains = [
        f"{n} more {noun}" for n, noun in
        ((caveats, "caveated negative"), (answers, "answerable question")) if n
    ]
    if not gains:
        return ""
    return f" by {' and '.join(gains)} at {point['min']:g}/{point['strong']:g}"


def report_sweep(swept: dict, measured: dict) -> None:
    print(f"\nthreshold sweep ({swept['grid']} pairs) — Pareto front, one row per trade")
    print("   caveat recall   answerable kept   min_confident   strong")
    for point in swept["front"]:
        mark = "  <- as shipped" if point.get("shipped") else ""
        print(f"   {point['caveat_recall']:12.1%}   {point['answerable_kept']:14.1%}   "
              f"{point['min']:13g}   {point['strong']:6g}{mark}")
    # Where the app actually stands, so the front is read against something — printed
    # whether or not the operating point is *on* the front, because "it is dominated" is
    # the single most important thing this table can say.
    on_front = any(point.get("shipped") for point in swept["front"])
    print(f"   {measured['caveat_recall']:12.1%}   "
          f"{1 - measured['over_refusal']:14.1%}   "
          f"{'as shipped':>13s}   {'':>6s}"
          + ("" if on_front else "  <- off the front" + _by_how_much(swept, measured)))
    free = gate.dominating(swept, measured)
    if free:
        print("   -> BETTER AT NO COST: "
              + ", ".join(f"{point['min']}/{point['strong']}" for point in free)
              + " beats the shipped pair on one axis and loses on neither, which means a "
                "constant is set wrong rather than traded")
    else:
        print("   -> nothing beats the shipped pair for free. Every pair above it on "
              "caveat recall pays for it in over-refusal, and which side of that trade to "
              "take is a judgement, not a measurement.")
    for point in gate.separable(swept):
        print(f"      available trade: {point['min']}/{point['strong']} would caveat "
              f"{point['caveat_recall']:.1%} and keep {point['answerable_kept']:.1%}")


def report_against(measured: dict, path: str) -> None:
    with open(path, encoding="utf-8") as handle:
        before = json.load(handle)
    print("\nagainst the saved run")
    for key in ("caveat_recall", "over_refusal", "recall@5"):
        if key in before:
            print(f"   {key:14s} {measured[key]:6.1%}  "
                  f"({measured[key] - before[key]:+.1%})")
    # Per question, not only in aggregate: a count can hold still while the membership
    # changes, which is what a refactor does and what a percentage hides.
    was = {row["question"]: row["leaked"] for row in before["rows"]["negatives"]}
    for row in measured["rows"]["negatives"]:
        previous = was.get(row["question"])
        if previous is not None and previous != row["leaked"]:
            print(f"   {'REGRESSED' if row['leaked'] else 'fixed'}: {row['question']!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", action="store_true", help="only the label audit")
    parser.add_argument("--sweep", action="store_true", help="add the threshold sweep")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--save", help="write this run's numbers here")
    parser.add_argument("--against", help="a JSON file saved by --save")
    parsed = parser.parse_args()

    built = corpus_mod.build()
    if not built.chunks:
        print("no documentation trees available", file=sys.stderr)
        return 2
    index = retrieval.build(built)

    negatives = gate.audit(evals.negatives(), gate.haystack(built))
    positives = evals.questions()
    identifiers = evals.identifiers()

    if parsed.audit:
        suspect = [case for case in negatives if case.suspect]
        for case in suspect:
            print(f"SUSPECT {case.text!r} -> corpus mentions {list(case.found)}")
        print(f"{len(negatives) - len(suspect)}/{len(negatives)} labels hold")
        return 1 if suspect else 0

    measured = gate.measure(index, negatives, positives, identifiers)
    report(measured, verbose=parsed.verbose)

    if parsed.sweep:
        report_sweep(gate.sweep(index, negatives, positives, identifiers), measured)
    if parsed.against:
        report_against(measured, parsed.against)
    if parsed.save:
        with open(parsed.save, "w", encoding="utf-8") as handle:
            json.dump(measured, handle, indent=1)
        print(f"\nsaved to {parsed.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
