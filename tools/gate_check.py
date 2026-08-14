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
centre does not run. Those score 26–64 and sail straight through.

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


def report_sweep(swept: dict) -> None:
    print(f"\nthreshold sweep ({swept['grid']} pairs) — Pareto front only")
    print("   caveat recall   answerable kept   min_confident   strong")
    for point in swept["front"]:
        print(f"   {point['caveat_recall']:12.1%}   {point['answerable_kept']:14.1%}   "
              f"{point['min']:13d}   {point['strong']:6d}")
    if gate.separable(swept):
        print("   -> a threshold pair reaching 90% caveat recall while keeping 95% of "
              "answerable questions EXISTS; the fix may be a number after all")
    else:
        print("   -> no threshold pair reaches 90% caveat recall while keeping 95% of "
              "answerable questions: the two sides overlap, so the fix is not a number")


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
        report_sweep(gate.sweep(index, negatives, positives, identifiers))
    if parsed.against:
        report_against(measured, parsed.against)
    if parsed.save:
        with open(parsed.save, "w", encoding="utf-8") as handle:
            json.dump(measured, handle, indent=1)
        print(f"\nsaved to {parsed.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
