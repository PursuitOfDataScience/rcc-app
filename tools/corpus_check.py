#!/usr/bin/env python3
"""Axis C: what the corpus can and cannot answer, before any model is involved.

    python tools/corpus_check.py
    python tools/corpus_check.py --save report/corpus.json

The measuring lives in `evals/corpus_health.py` so `pytest` can gate the parts that
should never regress — an id that stops resolving, a chunk that loses its URL, a new
empty document. This file is the report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from evals import corpus_health  # noqa: E402
from sage import corpus as corpus_mod  # noqa: E402
from sage import retrieval  # noqa: E402


def report(measured: dict) -> None:
    print(f"corpus     {measured['chunks']} chunks")
    for name, row in sorted(measured["sources"].items()):
        print(f"   {name:6s} {row['pages']:4d} pages  {row['chunks']:4d} chunks  "
              f"{row['chars'] / 1000:8.1f}k chars")

    empty = measured["empty_documents"]
    print(f"\nempty documents ({len(empty)}) — topics nothing can answer")
    for row in empty:
        print(f"   {row['bytes']:5d} bytes  {row['source']}/{row['path']}")

    duplicated = measured["duplicates"]
    exact, near = duplicated["exact_groups"], duplicated["near"]
    across = sum(1 for row in near if row["cross_source"])
    print(f"\nduplicate sections   exact groups {len(exact)}   "
          f"near-duplicate pairs {len(near)} ({across} across sources)")
    for group in exact:
        print(f"   identical: {group}")

    reach = measured["reachability"]
    print(f"\nreachability   {reach['touched']} of {reach['total']} chunks surfaced by "
          f"{reach['questions']} questions")
    if reach["measurable"]:
        print(f"   {reach['touched'] / reach['total']:.1%} of the index is reachable")
    else:
        print(f"   NOT MEASURABLE: {reach['questions']} questions x "
              f"{corpus_health.SEARCH_LIMIT} results is a ceiling of {reach['ceiling']} "
              f"chunks, below the {reach['total']} indexed. A percentage here would "
              "describe the question set, not the index.")

    print("\ntopics the profile advertises")
    for row in measured["topics"]:
        print(f"   {'ok      ' if row['confident'] else 'CAVEATED'} {row['score']:6.1f}  "
              f"{row['topic']:14s} -> {row['top_page']}")
    if any(not row["confident"] for row in measured["topics"]):
        print("   -> a one-word query scores low because the floor is an unnormalised "
              "sum, not because the topic is missing. Worth knowing: a reader who types "
              "one word gets the caveat.")

    broken = measured["unresolvable_ids"]
    urlless = measured["chunks_without_url"]
    print(f"\nintegrity   ids that do not resolve {len(broken)}   "
          f"chunks with no URL {len(urlless)}")
    for identifier in broken[:5]:
        print(f"   unresolvable: {identifier}")
    for identifier in urlless[:5]:
        print(f"   no url: {identifier}")

    snapshot = measured["freshness"]
    print("\nfreshness  " + (json.dumps(snapshot) if snapshot else "no snapshot recorded"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", help="write this run's numbers here")
    parsed = parser.parse_args()

    built = corpus_mod.build()
    if not built.chunks:
        print("no documentation trees available", file=sys.stderr)
        return 2
    measured = corpus_health.measure(built, retrieval.build(built))
    report(measured)

    if parsed.save:
        with open(parsed.save, "w", encoding="utf-8") as handle:
            json.dump(measured, handle, indent=1)
        print(f"\nsaved to {parsed.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
