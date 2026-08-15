#!/usr/bin/env python3
"""Axis B: how each model behaves inside this app's loop, measured rather than assumed.

The default model was chosen from a latency anecdote written into a profile comment —
"answers in 2.2s" against "23s when it answers at all". That is the seat-of-the-pants
decision this file replaces. Every question goes through `app.py` itself under a
stubbed Streamlit (see `evals/harness.py`), so what is measured is the real tool loop,
the real history budget, the real failover and the real citation post-processing.

    python tools/agent_bench.py --models default --limit 6
    python tools/agent_bench.py --models all --out report/
    OPENCODE_BASE_URL=http://127.0.0.1:8799/v1 python tools/agent_bench.py --models all

The last line points the whole benchmark at `tools/mock_provider.py`: no key, no
network, deterministic — which is how to check the harness before spending a free
tier's allowance on it.

**This is never a CI gate.** A free tier's lineup rotates without notice and its
models are nondeterministic; a ratchet here would go red for reasons that are not this
repository's fault, and somebody would loosen it to make the build quiet. The output is
a dated report and a diff against the last one. What belongs in `pytest` is Axis A —
whether the app survives a model behaving badly — and that is already there.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import evals  # noqa: E402
from evals import checks, harness  # noqa: E402
from sage import corpus as corpus_mod  # noqa: E402
from sage import providers, retrieval  # noqa: E402
from sage.profile import active as _active  # noqa: E402


def lineup(names: list[str]) -> list[str]:
    """Model keys this deployment can actually reach, in the profile's order."""
    found: list[str] = []
    for name in providers.names():
        key = providers.api_key(name)
        if not key:
            continue
        if names and name not in names:
            continue
        try:
            found.extend(model.key for model in providers.build(name, key).models())
        except Exception as exc:  # a provider that cannot be listed is a finding
            print(f"   {name}: could not list models ({type(exc).__name__}: {exc})",
                  file=sys.stderr)
    return found


def percentile(values: list[float], fraction: float) -> float | None:
    kept = sorted(value for value in values if value is not None)
    if not kept:
        return None
    index = min(len(kept) - 1, int(round(fraction * (len(kept) - 1))))
    return round(kept[index], 2)


def query_quality(index, records: list[dict]) -> dict:
    """Did the model's own search query retrieve better than the question did?

    The one place a documentation agent can help or hurt retrieval on purpose: it
    rewrites the reader's question before searching. Scored on the cases that have a
    gold page, by asking the same index both ways — so this isolates the model's
    contribution from the ranking's.
    """
    better = worse = same = 0
    for record in records:
        pages = set(record.get("pages") or ())
        queries = record.get("queries") or []
        if not pages or not queries:
            continue
        asked = {result.chunk.path for result in index.search(record["question"], 5)}
        theirs: set[str] = set()
        for query in queries:
            theirs |= {result.chunk.path for result in index.search(query, 5)}
        hit_asked = bool(pages & asked)
        hit_theirs = bool(pages & theirs)
        if hit_theirs and not hit_asked:
            better += 1
        elif hit_asked and not hit_theirs:
            worse += 1
        else:
            same += 1
    return {"better": better, "worse": worse, "same": same}


def summarise(model: str, records: list[dict], index) -> dict:
    total = len(records) or 1
    # Which of the app's two answering paths these turns went down. Recorded rather than
    # assumed, and computed from the records rather than passed in, so a row that somehow
    # covers both says so instead of averaging them: `srch 50%  rnd 2.0` over three tool
    # turns and three grounded ones is true of neither, and reads as a model that searches
    # half the time. Missing on transcripts written before the field existed, and those
    # were all tool-path runs.
    paths = {str(row.get("path") or "tools") for row in records}
    arm = next(iter(paths)) if len(paths) == 1 else "mixed"
    answered = [row for row in records if row["outcome"] == "answered"]
    positives = [row for row in answered if row["expect"] == "answer"]
    negatives = [row for row in answered if row["expect"] == "caveat"]

    kinds: dict[str, int] = {}
    for row in records:
        if row["error_kind"]:
            kinds[row["error_kind"]] = kinds.get(row["error_kind"], 0) + 1

    tool_calls = [call for row in records for call in row["tool_calls"]]
    bad_args = sum(1 for call in tool_calls if not call["arguments"])

    def tally_of(key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in answered:
            for kind in row.get(key, []):
                counts[kind] = counts.get(kind, 0) + 1
        return counts

    tally = tally_of("defects")
    warnings = tally_of("warnings")

    with_gold = [row for row in positives if row["pages"]]
    return {
        "model": model,
        "path": arm,
        "n": len(records),
        "answered": len(answered) / total,
        "empty": sum(1 for row in records if row["error_kind"] == "empty") / total,
        "refused": sum(1 for row in records if row["outcome"] == "refused") / total,
        "crashed": sum(1 for row in records if row["outcome"] == "crashed") / total,
        # The harness running out of script runs, not the model failing. Kept separate so
        # a bound of the instrument is never charged to the thing being measured.
        "unfinished": sum(
            1 for row in records if row["outcome"] == "unfinished"
        ) / total,
        "error_kinds": kinds,
        "searched": (
            sum(1 for row in answered if row["searches"]) / (len(answered) or 1)
        ),
        "read": sum(1 for row in answered if row["reads"]) / (len(answered) or 1),
        "rounds": round(statistics.mean([row["rounds"] for row in records]), 2),
        "calls": round(statistics.mean([row["provider_calls"] for row in records]), 2),
        "read_errors": sum(row["read_errors"] for row in records),
        "bad_tool_args": bad_args,
        "cited_gold": (
            sum(1 for row in with_gold if set(row["pages"]) & set(row["source_pages"]))
            / (len(with_gold) or 1)
        ),
        "first_text_p50": percentile([row["first_text"] for row in records], 0.5),
        "first_text_p95": percentile([row["first_text"] for row in records], 0.95),
        "seconds_p50": percentile([row["seconds"] for row in records], 0.5),
        "seconds_p95": percentile([row["seconds"] for row in records], 0.95),
        "defects_per_answer": round(
            sum(row.get("defect_count", 0) for row in answered) / (len(answered) or 1), 2
        ),
        "defect_kinds": tally,
        "warning_kinds": warnings,
        "refusal_correct": (
            sum(1 for row in negatives if "no-refusal" not in row.get("findings", []))
            / (len(negatives) or 1)
        ),
        "n_negatives_answered": len(negatives),
        "query_quality": query_quality(index, positives),
    }


def crashed_record(question, model, expect, must, pages, exc, started,
                   toolless=False) -> dict:
    """A turn that took the harness down with it. Recorded, not raised.

    One model in seven does something no other does, and a benchmark that stops on the
    first of them measures the six that ran before it.
    """
    return {
        "question": question, "model": model, "expect": expect,
        "outcome": "crashed", "fatal": f"{type(exc).__name__}: {exc}",
        # The arm asked for, not the arm observed — the only record where those can
        # differ, because a crash may come before any request reached the provider.
        # Absent entirely, a crashed grounded turn would be summarised as a tool one.
        "path": "grounded" if toolless else "tools",
        "unfinished": False,
        "error": "", "error_kind": "", "text": "", "raw": "",
        "sources": [], "source_pages": [], "evidence": {},
        "pages": list(pages), "must_mention": list(must),
        "tool_calls": [], "searches": 0, "reads": 0, "queries": [],
        "read_errors": 0, "rounds": 0, "provider_calls": 0,
        "seconds": round(time.monotonic() - started, 3),
        "first_text": None, "first_byte": None, "stream_chunks": [],
    }


def one_turn(question, model, expect, must, pages, sage, haystack, contact,
             toolless=False) -> dict:
    started = time.monotonic()
    try:
        record = harness.run_turn(
            question, model, expect=expect, must_mention=must, pages=pages,
            toolless=toolless,
        )
    except BaseException as exc:  # noqa: BLE001 — one bad turn is data, not an exit
        record = crashed_record(
            question, model, expect, must, pages, exc, started, toolless=toolless
        )

    found = checks.inspect(record, sage.corpus, haystack, contact=contact)
    record["findings"] = [item.kind for item in found]
    record["defects"] = [item.kind for item in checks.defects(found)]
    record["warnings"] = [
        item.kind for item in found if item.severity == checks.WARNING
    ]
    record["defect_count"] = len(record["defects"])
    record["finding_detail"] = [str(item) for item in found]
    return record


def run(
    models: list[str],
    cases: list[tuple],
    *,
    sleep: float,
    out: str,
    conversations: bool = False,
    injections: bool = False,
    toolless: bool = False,
) -> dict:
    """Every phase asked for, over one prepared harness and one transcript stream."""
    sage = harness.prepare()
    haystack = checks.Haystack(sage.corpus)
    contact = _active().identity.contact

    summary: dict = {"models": [], "conversations": [], "injections": []}
    # Written and flushed per turn rather than dumped at the end: a long run over a free
    # tier gets interrupted, and the turns it already paid for should survive that.
    with contextlib.ExitStack() as stack:
        stream = None
        if out:
            os.makedirs(out, exist_ok=True)
            stream = stack.enter_context(
                open(os.path.join(out, "transcripts.jsonl"), "a", encoding="utf-8")
            )
        for model in models:
            if not cases:
                break
            records = []
            print(f"\n{model}", flush=True)
            for question, expect, must, pages in cases:
                record = one_turn(
                    question, model, expect, must, pages, sage, haystack, contact,
                    toolless=toolless,
                )
                records.append(record)
                if stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                    stream.flush()
                mark = {
                    "answered": "ok", "refused": "refused",
                    "nothing": "nothing", "crashed": "CRASH",
                    "unfinished": "UNFIN",
                }.get(record["outcome"], record["outcome"])
                print(f"   {mark:8s} {record['seconds']:6.1f}s "
                      f"r{record['rounds']} s{record['searches']} d{record['reads']} "
                      f"{record['defect_count']}def  {question[:52]!r}", flush=True)
                if sleep:
                    time.sleep(sleep)
            summary["models"].append(summarise(model, records, sage.retriever))

        if conversations:
            summary["conversations"] = run_conversations(
                models, sage, haystack, contact, stream, toolless=toolless
            )
        if injections:
            summary["injections"] = run_injections(
                models, sage, haystack, contact, stream, toolless=toolless
            )
    return summary


def run_conversations(models, sage, haystack, contact, stream,
                      toolless=False) -> list[dict]:
    """Multi-turn, one session per case. What a single-question benchmark cannot see."""
    out = []
    for model in models:
        print(f"\n{model} — conversations", flush=True)
        rows = []
        for case in evals.conversations():
            records = harness.run_conversation(
                list(case.turns), model, toolless=toolless
            )
            for position, record in enumerate(records):
                found = checks.inspect(record, sage.corpus, haystack, contact=contact)
                record["defects"] = [item.kind for item in checks.defects(found)]
                record["warnings"] = [
                    item.kind for item in found if item.severity == checks.WARNING
                ]
                record["findings"] = [item.kind for item in found]
                record["defect_count"] = len(record["defects"])
                record["conversation"] = case.name
                if stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                    stream.flush()
                kept = (
                    bool(set(record["pages"]) & set(record["source_pages"]))
                    if record["pages"] else None
                )
                print(f"   turn {position + 1}  {record['outcome']:8s} "
                      f"gold={'-' if kept is None else ('yes' if kept else 'NO ')}  "
                      f"{record['defect_count']}def  {record['question'][:46]!r}",
                      flush=True)
            rows.extend(records)

        out.append(_conversation_summary(model, rows))
    return out


def _conversation_summary(model: str, rows: list[dict]) -> dict:
    """`first_turn_gold` against `follow_up_gold` is the multi-turn measurement.

    A model that cites the right page on the opening question and stops doing it on the
    follow-up has lost the thread, and the failure is quiet: a plausible answer to a
    question nobody asked, cited to a real page.
    """
    follow_ups = [row for row in rows if row.get("turn_index", 0) > 0 and row["pages"]]
    first_turns = [row for row in rows if row.get("turn_index", 0) == 0 and row["pages"]]
    return {
        "model": model,
        "turns": len(rows),
        "first_turn_gold": _gold_rate(first_turns),
        "follow_up_gold": _gold_rate(follow_ups),
        "answered": sum(1 for row in rows if row["outcome"] == "answered")
        / (len(rows) or 1),
        "question_always_sent": all(row.get("question_sent", True) for row in rows),
        "peak_request_chars": max((row.get("sent_chars", 0) for row in rows), default=0),
        "defects": sum(row["defect_count"] for row in rows),
    }


def _gold_rate(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    hits = sum(1 for row in rows if set(row["pages"]) & set(row["source_pages"]))
    return hits / len(rows)


def run_injections(models, sage, haystack, contact, stream,
                   toolless=False) -> list[dict]:
    """An instruction hidden in an uploaded file, which the app promises to ignore."""
    from sage.files import Attachment  # noqa: PLC0415 — only this phase needs it

    out = []
    for model in models:
        print(f"\n{model} — injections", flush=True)
        rows = []
        for case in evals.injections():
            attachment = Attachment(
                filename=case.filename, kind="text", text=case.content
            )
            record = harness.run_turn(
                case.question, model, attachments=[attachment], toolless=toolless
            )
            found = checks.inspect(record, sage.corpus, haystack, contact=contact)
            found += checks.injection_findings(
                record["text"], case.canary, case.leaks
            )
            record["injection"] = case.name
            record["findings"] = [item.kind for item in found]
            record["defects"] = [item.kind for item in checks.defects(found)]
            record["defect_count"] = len(record["defects"])
            rows.append(record)
            if stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
            verdict = (
                "OBEYED" if "obeyed-injection" in record["findings"]
                else "LEAKED" if "leaked-prompt" in record["findings"]
                else "held"
            )
            print(f"   {verdict:7s} {record['outcome']:8s} {case.name}", flush=True)
        out.append(
            {
                "model": model,
                "n": len(rows),
                "obeyed": sum(
                    1 for row in rows if "obeyed-injection" in row["findings"]
                ),
                "leaked": sum(1 for row in rows if "leaked-prompt" in row["findings"]),
                "answered": sum(1 for row in rows if row["outcome"] == "answered"),
            }
        )
    return out


def report_conversations(rows: list[dict]) -> None:
    print("\nmulti-turn — did the follow-up keep the thread?")
    print(f"   {'model':34s} {'turns':>6s} {'first':>7s} {'follow':>7s} "
          f"{'ans':>5s} {'def':>4s} {'peak req':>9s}")
    for row in rows:
        print(f"   {row['model'][:34]:34s} {row['turns']:6d} "
              f"{row['first_turn_gold']:6.0%} {row['follow_up_gold']:6.0%} "
              f"{row['answered']:4.0%} {row['defects']:4d} "
              f"{row['peak_request_chars']:9d}")
        if not row["question_always_sent"]:
            print("      the question did not survive the history budget on some turn")
    print("   first/follow = cited a gold page on the first turn / on later turns")


def report_injections(rows: list[dict]) -> None:
    print("\nuploads — an instruction inside a file is data, not a command")
    for row in rows:
        verdict = "held" if not (row["obeyed"] or row["leaked"]) else "FAILED"
        print(f"   {row['model'][:34]:34s} {verdict:7s} obeyed {row['obeyed']}/{row['n']}"
              f"   prompt leaked {row['leaked']}/{row['n']}")


def rescore(path: str) -> dict:
    """Recompute every finding from stored transcripts. No network, no model, seconds.

    The checks improve — and they must, because a check with false positives is one
    somebody switches off. Validated against the first 75 real answers, `invented-token`
    dropped from 31 reports to 1 and `damaging-strip` from 8 to 0 once the extractor
    stopped reading `Midway2/3/SSD` as a filesystem path and the diff stopped reading a
    re-linked citation as a deletion. Every one of those 31 was scored by a run already
    paid for, so re-scoring the transcripts is how the correction reaches the card
    without asking a free tier for the same answers again.
    """
    built = corpus_mod.build()
    index = retrieval.build(built)
    haystack = checks.Haystack(built)
    contact = _active().identity.contact
    canaries = {case.name: case for case in evals.injections()}

    single: dict[str, list] = {}
    talks: dict[str, list] = {}
    uploads: dict[str, list] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            found = checks.inspect(record, built, haystack, contact=contact)
            if record.get("injection") in canaries:
                case = canaries[record["injection"]]
                found += checks.injection_findings(
                    record["text"], case.canary, case.leaks
                )
            record["findings"] = [item.kind for item in found]
            record["defects"] = [item.kind for item in checks.defects(found)]
            record["warnings"] = [
                item.kind for item in found if item.severity == checks.WARNING
            ]
            record["defect_count"] = len(record["defects"])
            record["finding_detail"] = [str(item) for item in found]
            bucket = (
                uploads if record.get("injection")
                else talks if record.get("conversation")
                else single
            )
            # Keyed by arm as well as model. `transcripts.jsonl` is opened in append
            # mode, so one file accumulates every run written to that directory — and
            # once two of them are different paths through the app, one row averaged
            # over both is a number about nothing.
            key = (record["model"], str(record.get("path") or "tools"))
            bucket.setdefault(key, []).append(record)

    summary: dict = {"models": [], "conversations": [], "injections": []}
    for (model, _arm), records in single.items():
        summary["models"].append(summarise(model, records, index))
    for (model, arm), records in talks.items():
        summary["conversations"].append(_conversation_summary(model, records) | {"path": arm})
    for (model, arm), records in uploads.items():
        summary["injections"].append(
            {
                "model": model,
                "path": arm,
                "n": len(records),
                "obeyed": sum(
                    1 for row in records if "obeyed-injection" in row["findings"]
                ),
                "leaked": sum(
                    1 for row in records if "leaked-prompt" in row["findings"]
                ),
                "answered": sum(
                    1 for row in records if row["outcome"] == "answered"
                ),
            }
        )
    return summary


def report(summary: dict) -> None:
    if summary.get("conversations"):
        report_conversations(summary["conversations"])
    if summary.get("injections"):
        report_injections(summary["injections"])
    rows = summary.get("models") or []
    if not rows:
        return
    print("\n" + "=" * 118)
    print(f"{'model':34s} {'n':>3s} {'ans':>6s} {'empty':>6s} {'srch':>5s} "
          f"{'read':>5s} {'gold':>5s} {'rnd':>4s} {'call':>5s} {'ttft':>6s} "
          f"{'p95':>6s} {'def':>5s} {'refus':>6s}")
    print("-" * 118)
    for row in rows:
        # The arm, only when it is not the tool loop, so a run of the default path prints
        # exactly what it printed before there was a second path to confuse it with.
        arm = str(row.get("path") or "tools")
        label = row["model"] if arm == "tools" else f"{row['model']} [{arm}]"
        print(f"{label[:34]:34s} {row['n']:3d} {row['answered']:5.0%} "
              f"{row['empty']:5.0%} {row['searched']:4.0%} {row['read']:4.0%} "
              f"{row['cited_gold']:4.0%} {row['rounds']:4.1f} {row['calls']:5.1f} "
              f"{str(row['first_text_p50'] or '-'):>6s} "
              f"{str(row['seconds_p95'] or '-'):>6s} "
              f"{row['defects_per_answer']:5.2f} {row['refusal_correct']:5.0%}")
    print("-" * 118)
    print("ans=answered  srch/read=of answered turns  gold=cited a gold page  "
          "rnd=rounds  ttft=first text s (p50)")
    print("def=defects per answer  refus=correct refusals on the unanswerable split")

    for row in rows:
        print(f"\n{row['model']}")
        if row["error_kinds"]:
            print("   failures: " + ", ".join(
                f"{kind} x{count}" for kind, count in sorted(row["error_kinds"].items())
            ))
        for label, key in (("defects ", "defect_kinds"), ("warnings", "warning_kinds")):
            if row[key]:
                print(f"   {label}: " + ", ".join(
                    f"{kind} x{count}" for kind, count in
                    sorted(row[key].items(), key=lambda item: -item[1])
                ))
        quality = row["query_quality"]
        print(f"   its query vs the reader's: better {quality['better']}, "
              f"worse {quality['worse']}, same {quality['same']}")
        if row["read_errors"] or row["bad_tool_args"]:
            print(f"   read_doc errors {row['read_errors']}, "
                  f"empty tool arguments {row['bad_tool_args']}")


def spread(cases: list, limit: int) -> list:
    """`limit` cases taken evenly across the file, not off the front.

    Both sets are grouped by topic, so the first eight questions are all Slurm and the
    first six negatives are all another site's cluster. A truncated head would report a
    model's behaviour on one topic as its behaviour overall.
    """
    if not limit or limit >= len(cases):
        return cases
    step = len(cases) / limit
    return [cases[int(index * step)] for index in range(limit)]


def cases_from(sets: str, limit: int, negatives: int) -> list[tuple]:
    out: list[tuple] = []
    if sets == "none":
        return out
    if sets in ("both", "positive"):
        for case in spread(evals.questions(), limit):
            out.append((case.text, "answer", case.must_mention, case.pages))
    if sets in ("both", "negative"):
        for case in spread(evals.negatives(), negatives):
            out.append((case.text, "caveat", (), ()))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default="default",
                        help="'default', 'all', or a comma-separated list of keys")
    parser.add_argument("--set", default="both",
                        choices=("both", "positive", "negative", "none"),
                        help="'none' runs only the phases named below")
    parser.add_argument("--conversations", action="store_true",
                        help="multi-turn cases from evals/conversations.toml")
    parser.add_argument("--injections", action="store_true",
                        help="hidden instructions in uploads, from evals/injections.toml")
    parser.add_argument("--limit", type=int, default=0, help="answerable questions")
    parser.add_argument("--negatives", type=int, default=0)
    parser.add_argument("--toolless", action="store_true",
                        help="drive the grounded path instead: one retrieval up front, "
                             "no tool rounds, which is what a model in "
                             "SAGE_TOOLLESS_MODELS gets")
    parser.add_argument("--sleep", type=float, default=0.0,
                        help="seconds between turns, for a rate-limited free tier")
    parser.add_argument("--out", default="", help="directory for transcripts + summary")
    parser.add_argument("--rescore", metavar="TRANSCRIPTS",
                        help="recompute every finding from a saved transcripts.jsonl "
                             "instead of asking any model again")
    parsed = parser.parse_args()

    if parsed.rescore:
        summary = rescore(parsed.rescore)
        report(summary)
        if parsed.out:
            path = os.path.join(parsed.out, "agents.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(summary, handle, indent=1)
            print(f"\nrescored into {path}")
        return 0

    if parsed.models == "all":
        models = lineup([])
    elif parsed.models == "default":
        from sage import config  # noqa: PLC0415

        models = [config.DEFAULT_MODEL]
    else:
        models = [name.strip() for name in parsed.models.split(",") if name.strip()]

    if not models:
        print("no models are reachable; is a provider key set?", file=sys.stderr)
        return 2

    cases = cases_from(parsed.set, parsed.limit, parsed.negatives)
    extra = 0
    if parsed.conversations:
        extra += sum(len(case.turns) for case in evals.conversations())
    if parsed.injections:
        extra += len(evals.injections())
    print(f"{len(models)} model(s) x {len(cases) + extra} turn(s) = "
          f"{len(models) * (len(cases) + extra)} turns"
          + ("  [grounded path: no tools offered]" if parsed.toolless else ""))

    summary = run(
        models, cases, sleep=parsed.sleep, out=parsed.out,
        conversations=parsed.conversations, injections=parsed.injections,
        toolless=parsed.toolless,
    )
    report(summary)

    if parsed.out:
        path = os.path.join(parsed.out, "agents.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=1)
        print(f"\nsaved to {path} (transcripts alongside it, gitignored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
