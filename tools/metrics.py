"""Print retrieval metrics for the golden set. Run it instead of quoting a comment.

Three places in this repository carried hand-written metrics — the eval's docstring and
two config comments — and the docstring's numbers were never true of the code beside
them. A number nobody re-derives goes stale silently, so this derives them.

    python tools/metrics.py                 # the current tree
    python tools/metrics.py --against a.json
    python tools/metrics.py --save a.json   # to compare a later change against

`depth` is the metric the eval itself cannot see: how many sections *of an acceptable
page* are among the six results the model is handed. Recall counts pages, so a change
that swaps five sections of the right page for one section each of five pages scores
identically and takes the answer's evidence away.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from sage import corpus as corpus_mod  # noqa: E402
from sage.search import Index  # noqa: E402

EVAL = os.path.join(ROOT, "tests", "test_retrieval_eval.py")


def cases() -> tuple[list, list]:
    """The eval's own case lists.

    Read with `ast` rather than imported, because the eval module imports pytest and
    this has to run in environments that cannot install it — which is exactly when
    someone is reaching for a number and tempted to quote the stale comment instead.
    """
    with open(EVAL, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    found: dict[str, list] = {}
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign):
            target = getattr(node.target, "id", None)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = getattr(node.targets[0], "id", None)
        if target in ("CASES", "KNOWN_GAPS"):
            found[target] = ast.literal_eval(node.value)
    return found["CASES"], found["KNOWN_GAPS"]


def measure(index: Index, questions: list, limit: int = 6) -> dict:
    hits = {5: 0, 3: 0, 1: 0}
    reciprocal = 0.0
    depth = 0
    ranks: dict[str, int] = {}
    for question, expected in questions:
        paths = [result.chunk.path for result in index.search(question, limit)]
        for at in hits:
            hits[at] += bool(set(expected) & set(paths[:at]))
        rank = next((i + 1 for i, path in enumerate(paths) if path in expected), 0)
        ranks[question] = rank
        reciprocal += 1 / rank if rank else 0.0
        depth += sum(1 for path in paths[:limit] if path in expected)
    total = len(questions) or 1
    return {
        "n": len(questions),
        "recall@5": hits[5] / total,
        "recall@3": hits[3] / total,
        "p@1": hits[1] / total,
        "MRR": reciprocal / total,
        "depth": depth / total,
        "ranks": ranks,
    }


def report(label: str, now: dict, before: dict | None) -> None:
    print(f"{label} (n={now['n']})")
    for key, form in (("recall@5", "pct"), ("recall@3", "pct"), ("p@1", "pct"),
                      ("MRR", "num"), ("depth", "num")):
        value = f"{now[key]:6.1%}" if form == "pct" else f"{now[key]:6.3f}"
        change = ""
        if before and key in before:
            delta = now[key] - before[key]
            change = (f"  ({delta:+.1%})" if form == "pct" else f"  ({delta:+.3f})")
        print(f"   {key:9s} {value}{change}")
    if not before:
        return
    def shown(rank: int | None) -> str:
        return str(rank) if rank else "miss"

    for question, rank in now["ranks"].items():
        was = before["ranks"].get(question)
        if was is None or was == rank:
            continue
        print(f"   {'better' if (rank or 99) < (was or 99) else 'WORSE '}: "
              f"{question!r} {shown(was)} -> {shown(rank)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--against", help="a JSON file saved by --save")
    parser.add_argument("--save", help="write this run's numbers here")
    parser.add_argument("--label", default="retrieval")
    parsed = parser.parse_args()

    known, gaps = cases()
    index = Index(corpus_mod.build())
    if not index.total:
        print("no documentation trees available", file=sys.stderr)
        return 2

    before = None
    if parsed.against:
        with open(parsed.against, encoding="utf-8") as handle:
            before = json.load(handle)

    # Both, separately: the ratchets in the eval are over CASES, and the known gaps
    # are the ones a ranking change is most likely to move.
    now = measure(index, known)
    report(f"{parsed.label}: golden set", now, before)
    report(f"{parsed.label}: + known gaps", measure(index, known + gaps), None)

    if parsed.save:
        with open(parsed.save, "w", encoding="utf-8") as handle:
            json.dump(now, handle, indent=1)
        print(f"\nsaved to {parsed.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
