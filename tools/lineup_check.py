#!/usr/bin/env python3
"""What the provider serves today, against what this repository says it serves.

The app does not need this to work. Model lists are discovered from `GET /models` at
runtime and filtered by a *rule* (`free_marks`), so a model Zen starts serving free
under a `-free` suffix appears in the picker the moment it exists, with no commit —
`muse-spark-1.2-contributor-free` was offered before anything named it. And a model
that vanishes is handled too: `app.current_model` falls through a missing
`SAGE_DEFAULT_MODEL` to the first discovered option.

So this is not a fetch-the-list script. It exists for the four things the rule cannot
do on its own, each of which has already cost something here:

1. **A stealth codename.** Zen publishes some models free under a name with no marker
   in it — `big-pickle` is in `free_marks` as a literal for exactly this reason. The
   rule cannot invent the next one. Nothing but a probe distinguishes it from the
   fifty-odd paid models served from the same endpoint, and the only person who can
   decide to widen a rule is a person. This reports the candidate; it never edits
   `free_marks`.

2. **Served is not working.** `north-mini-code-free` was in the profile's list and
   answered 401 from Zen's own upstream; `ling-3.0-tiny-free` answered 503. Both were
   in the catalogue while neither could answer a question. A list-only check would
   have called that lineup healthy.

3. **How long a thing has been gone.** The profile declines to remove a model for
   being broken today, on the grounds that a free tier's outages come back — and it is
   right, `hy3-free` left and returned. What it could not say is whether a given
   absence is two days old or two months. The ledger accrues `missing_since`, which
   turns that judgement into a date the owner can act on.

4. **Whether the repository's own record is still true.** The fallback list, the
   default model, `EVAL.md`'s per-model table: all of them go stale silently, because
   nothing reads them against reality.

    python tools/lineup_check.py                    # drift, no requests spent at all
    python tools/lineup_check.py --probe            # + a real completion per new name
    python tools/lineup_check.py --probe --update   # + append the new free ones
    python tools/lineup_check.py --summary-out drift.md

`GET /models` on Zen needs no key — measured, with no header and with a bogus one, both
200 with the full catalogue — so the drift half of this runs in CI with no secret. Only
`--probe` spends a request, and only on a name the ledger has not classified before: a
day Zen changes nothing costs nothing.

**Probes send `config.MAX_TOKENS`, and that is not incidental.** A reasoning model
spends the budget on thinking it does not emit: `muse-spark-1.2-contributor-free` at
`max_tokens=200` returns `completion_tokens: 200` and an empty completion, three times
out of three, and reads as a dead endpoint. A cheap probe would have libelled it — and
would libel every reasoning model Zen adds from here on.

Never a CI gate, for the reason `EVAL.md` gives about Axis B: a free tier rotating its
lineup is not this repository's fault, and a red build for it would get loosened until
it was quiet. The output is a report, a ledger and — when there is something to add — a
diff.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from sage import config, providers  # noqa: E402
from sage.profile import ProviderEntry  # noqa: E402
from sage.profile import active as _active  # noqa: E402

LEDGER = os.path.join(ROOT, "report", "lineup.json")

# What a probe asks. Short enough to be cheap, and phrased so that calling the offered
# tool is the obvious move — because otherwise the verdict cannot mean anything.
#
# It used to read "Reply with the single word: ready", and
# `muse-spark-1.2-contributor-free` sensibly answered it in five characters without
# touching the tool. The verdict then said "no tool call" about a model measured
# separately making two of them, which is a report that invents a limitation. A probe
# that does not ask for the behaviour it is grading cannot grade it.
PROBE_PROMPT = (
    "Use the search_docs tool to look up 'storage quota', then reply with the single "
    "word: ready"
)

# A tool the probe offers, so the verdict can record whether the model can call one at
# all. Shaped like the app's own search tool rather than a toy, because a model that
# rejects a real schema and accepts `{"type": "object"}` is not usable here.
PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "search_docs",
        "description": "Search the documentation for a phrase.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}

# Bodies that mean "this model is real, you just cannot pay for it". Zen answers a paid
# model on a free key with `401 CreditsError: Insufficient balance`, which is a
# different fact from a 401 on a model that does not exist.
PAID_MARKS = ("insufficient balance", "creditserror", "payment", "quota exceeded")

# An error body is whatever a gateway feels like sending, and this one ends up in a
# ledger committed to a public repository. Zen's `CreditsError` embeds a billing URL
# carrying the workspace id — `https://opencode.ai/workspace/wrk_01K…/billing` — which
# is account state, not a fact about the model, and which nothing here needs to keep in
# order to say "this one is paid". Found by reading the first ledger this wrote.
_URL = re.compile(r"https?://\S+")
_OPAQUE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9]{16,}\b")


def scrub(body: str, limit: int = 200) -> str:
    """An error body with the account state taken out of it."""
    cleaned = _URL.sub("<url>", body or "")
    cleaned = _OPAQUE.sub("<id>", cleaned)
    return " ".join(cleaned.split())[:limit]


def today() -> str:
    return dt.date.today().isoformat()


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


# --- what the endpoint says ------------------------------------------------


def discoverable() -> list[ProviderEntry]:
    """Provider entries whose catalogue can be asked for over HTTP.

    The Mistral adapter is deliberately not one: its lineup is three named models that
    do not rotate, and listing it needs the SDK and a key. This is about free tiers.
    """
    return [
        item for item in _active().providers if item.kind == "openai" and item.base_url
    ]


def served(entry: ProviderEntry, key: str = "") -> list[str]:
    """Every model id the endpoint lists, in the order it lists them.

    Raises, rather than returning empty: an unreachable endpoint and an endpoint
    serving nothing are different findings and only one of them is drift.
    """
    import httpx  # noqa: PLC0415

    base = _base_url(entry)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if entry.user_agent:
        headers["User-Agent"] = entry.user_agent
    response = httpx.get(f"{base}/models", headers=headers, timeout=20)
    response.raise_for_status()
    payload = response.json()
    return [
        str(item["id"])
        for item in payload.get("data", [])
        if isinstance(item, dict) and item.get("id")
    ]


def _base_url(entry: ProviderEntry) -> str:
    """The URL the app would use.

    Already carries `base_url_env`: the profile loader resolves the override when it
    reads the file, so pointing `OPENCODE_BASE_URL` at `tools/mock_provider.py` aims
    this script at the mock too, which is how it is tested without spending anything.
    """
    return entry.base_url.rstrip("/")


def is_free(entry: ProviderEntry, model_id: str) -> bool:
    """The profile's own rule, not a second copy of it.

    Deliberately routed through the adapter the app uses, so a change to how a free
    model is recognised cannot be true in the picker and false here.
    """
    return providers.adapters.get(entry.kind)(entry, "probe")._is_free(model_id)


# --- probing ---------------------------------------------------------------


def probe(entry: ProviderEntry, key: str, model_id: str, *, tools: bool = True) -> dict:
    """One real streamed completion, and what it says about the model.

    `max_tokens` is the app's own, for the reason in the module docstring: a reasoning
    model given a tight budget emits nothing and looks broken.
    """
    import httpx  # noqa: PLC0415

    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": PROBE_PROMPT}],
        "max_tokens": config.MAX_TOKENS,
        "temperature": config.TEMPERATURE,
        "stream": True,
    }
    if tools:
        payload["tools"] = [PROBE_TOOL]
        payload["tool_choice"] = "auto"

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if entry.user_agent:
        headers["User-Agent"] = entry.user_agent

    verdict: dict = {"model": model_id, "checked": now()}
    started = time.time()
    text: list[str] = []
    calls = 0
    try:
        with (
            httpx.Client(timeout=httpx.Timeout(90.0, connect=15.0)) as client,
            client.stream(
                "POST",
                f"{_base_url(entry)}/chat/completions",
                json=payload,
                headers=headers,
            ) as response,
        ):
            if response.status_code >= 400:
                response.read()
                body = scrub(response.text[:600])
                verdict.update(
                    status=response.status_code,
                    error=body,
                    tier="paid" if _looks_paid(body) else "unknown",
                    answered=False,
                )
                verdict["seconds"] = round(time.time() - started, 2)
                return verdict
            for chunk in providers.parse_sse(response.iter_lines()):
                text.append(chunk.text)
                calls += len(chunk.tool_calls)
    except Exception as exc:  # a probe that cannot complete is a verdict, not a crash
        verdict.update(
            error=scrub(f"{type(exc).__name__}: {exc}"), tier="unknown", answered=False
        )
        verdict["seconds"] = round(time.time() - started, 2)
        return verdict

    body = "".join(text)
    verdict.update(
        status=200,
        seconds=round(time.time() - started, 2),
        chars=len(body),
        tool_calls=calls,
        answered=bool(body.strip() or calls),
        # A 200 is the only thing that distinguishes a stealth free model from a paid
        # one: the endpoint served it and did not ask to be paid.
        tier="free",
    )
    return verdict


def _looks_paid(body: str) -> bool:
    lowered = (body or "").lower()
    return any(mark in lowered for mark in PAID_MARKS)


# --- the ledger ------------------------------------------------------------


def load_ledger(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            found = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"providers": {}}
    if not isinstance(found, dict):
        return {"providers": {}}
    found.setdefault("providers", {})
    return found


def _slot(ledger: dict, name: str) -> dict:
    slot = ledger["providers"].setdefault(name, {})
    slot.setdefault("missing_since", {})
    slot.setdefault("verdicts", {})
    slot.setdefault("paid", [])
    return slot


def review(entry: ProviderEntry, catalogue: list[str], ledger: dict) -> dict:
    """Drift for one provider: what appeared, what went, what needs a human.

    Pure — no requests, no writes. The probing pass reads the `unclassified` list this
    produces and decides what to spend on.
    """
    slot = _slot(ledger, entry.name)
    listed = list(entry.models)
    free = [model_id for model_id in catalogue if is_free(entry, model_id)]
    known_paid = set(slot["paid"])

    appeared = [model_id for model_id in free if model_id not in listed]
    vanished = [model_id for model_id in listed if model_id not in catalogue]

    # Every served name the rule calls not-free and the ledger has not already priced.
    # These are the only candidates for the next `big-pickle`, and the only names worth
    # spending a request on.
    unclassified = [
        model_id
        for model_id in catalogue
        if model_id not in free and model_id not in known_paid
    ]

    # `missing_since` accrues rather than being recomputed, so a model that has been
    # gone for a month says so instead of saying "gone today" every day.
    missing = dict(slot["missing_since"])
    for model_id in vanished:
        missing.setdefault(model_id, today())
    for model_id in list(missing):
        if model_id in catalogue:
            del missing[model_id]

    default = providers.parse_key(config.DEFAULT_MODEL)
    default_missing = bool(
        default and default.provider == entry.name and default.id not in catalogue
    )

    return {
        "provider": entry.name,
        "served": catalogue,
        "free": free,
        "listed": listed,
        "appeared": appeared,
        "vanished": vanished,
        "unclassified": unclassified,
        "missing_since": missing,
        "default_missing": default_missing,
        # The rule matching nothing at all is the one failure that makes the picker
        # offer every paid model as if it worked. The adapter logs it; nobody reads a
        # deployment's logs.
        "rule_matched_nothing": bool(catalogue) and not free,
    }


def material(before: dict, after: dict) -> list[str]:
    """Whether anything changed that a person should look at.

    Latency deliberately does not count. A free tier's models wobble by seconds
    between one request and the next, and a daily pull request that says so is a daily
    pull request nobody reads.
    """
    # No prior record is not the same as everything having changed. The first run
    # against an empty ledger listed all eight free models as news, which is the
    # report a person learns to skim.
    if (before or {}).get("free") is None:
        return ["first record of this lineup — nothing to compare against yet"]

    reasons = []
    was_free = set(before.get("free") or [])
    now_free = set(after["free"])
    for model_id in sorted(now_free - was_free):
        reasons.append(f"`{model_id}` is now served free")
    for model_id in sorted(was_free - now_free):
        reasons.append(f"`{model_id}` is no longer served")
    if after["appeared"]:
        reasons.append(
            "the profile's list does not name "
            + ", ".join(f"`{name}`" for name in after["appeared"])
        )
    old_verdicts = (before or {}).get("verdicts") or {}
    for model_id, verdict in sorted(after.get("verdicts", {}).items()):
        was = old_verdicts.get(model_id) or {}
        if was and bool(was.get("answered")) != bool(verdict.get("answered")):
            state = "answers again" if verdict.get("answered") else "stopped answering"
            reasons.append(f"`{model_id}` {state}")
    for model_id in sorted(after.get("candidates") or []):
        reasons.append(f"`{model_id}` answered without matching `free_marks`")
    if after["default_missing"]:
        reasons.append(f"`{config.DEFAULT_MODEL}` is not in the catalogue")
    if after["rule_matched_nothing"]:
        reasons.append("`free_marks` matched nothing served")
    return reasons


# --- writing the profile back ----------------------------------------------


def append_models(text: str, provider: str, additions: list[str]) -> str:
    """Add ids to one provider's `models = [...]`, keeping every comment in place.

    Append only, and at the end. Three separate reasons, and they are not the same
    reason:

    * **Order is a judgement.** The first entry is what a fresh session starts on and
      what an automatic failover lands on. A tool that decided that would be deciding,
      once a day, which model every reader gets — from a catalogue listing, which says
      nothing about whether the model is any good.
    * **Appending is close to a no-op.** Discovery already offers anything the rule
      matches, and `_order` puts unlisted models after listed ones, which is where an
      appended one lands anyway. So this makes the record true without moving anything.
    * **Removal is the profile's call, and it has already made it** — nothing goes for
      being broken today. The ledger reports how long an absence has run; a human ends
      it.
    """
    if not additions:
        return text

    lines = text.splitlines(keepends=True)
    start = _models_line(lines, provider)
    if start is None:
        raise ValueError(f"no `models = [` for provider {provider!r}")

    opening = lines[start]
    if "]" in opening.split("[", 1)[1]:
        # `models = ["a", "b"]` on one line. Rewritten in place, same shape.
        head, rest = opening.split("[", 1)
        body, tail = rest.rsplit("]", 1)
        existing = [part.strip() for part in body.split(",") if part.strip()]
        joined = ", ".join(existing + [f'"{name}"' for name in additions])
        lines[start] = f"{head}[{joined}]{tail}"
        return "".join(lines)

    close = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].lstrip().startswith("]")
        ),
        None,
    )
    if close is None:
        raise ValueError(f"unterminated `models` list for provider {provider!r}")
    indent = _indent_of(lines[start + 1 : close]) or "    "
    added = [f'{indent}"{name}",\n' for name in additions]
    return "".join(lines[:close] + added + lines[close:])


def _models_line(lines: list[str], provider: str) -> int | None:
    """Index of the `models = [` line inside `provider`'s `[[providers]]` block."""
    inside = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[["):
            inside = False
            continue
        if stripped.startswith("["):
            inside = False
            continue
        if re.match(r'name\s*=\s*["\']' + re.escape(provider) + r'["\']', stripped):
            inside = True
            continue
        if inside and re.match(r"models\s*=\s*\[", stripped):
            return index
    return None


def _indent_of(lines: list[str]) -> str:
    for line in lines:
        if line.strip() and not line.strip().startswith("#"):
            return line[: len(line) - len(line.lstrip())]
    return ""


# --- reporting -------------------------------------------------------------


def summarise(report: dict, reasons: list[str]) -> str:
    """Markdown, because this ends up in a pull request body."""
    out = [f"### {report['provider']}", ""]
    out.append(
        f"{len(report['served'])} models served, {len(report['free'])} of them free "
        f"by the profile's rule, {len(report['listed'])} named in the profile."
    )
    out.append("")
    if reasons:
        out.append("**Changed:**")
        out += [f"- {reason}" for reason in reasons]
        out.append("")
    if report["appeared"]:
        out.append("**Free and served, not named in the profile**")
        for model_id in report["appeared"]:
            verdict = (report.get("verdicts") or {}).get(model_id) or {}
            out.append(f"- `{model_id}`{_verdict_note(verdict)}")
        out.append("")
    if report["vanished"]:
        out.append("**Named in the profile, not served** — kept, per the profile's rule")
        for model_id in report["vanished"]:
            since = report["missing_since"].get(model_id)
            days = _days_since(since)
            when = f" — missing since {since}" if since else ""
            aged = f" ({days} days)" if days is not None and days > 0 else ""
            out.append(f"- `{model_id}`{when}{aged}")
        out.append("")
    if report.get("candidates"):
        out.append(
            "**Answered a probe without matching `free_marks`** — a stealth codename, "
            "possibly. Widening the rule is a human decision; nothing here edits it."
        )
        for model_id in report["candidates"]:
            verdict = (report.get("verdicts") or {}).get(model_id) or {}
            out.append(f"- `{model_id}`{_verdict_note(verdict)}")
        out.append("")
    broken = [
        model_id
        for model_id, verdict in sorted((report.get("verdicts") or {}).items())
        if verdict.get("status") == 200 and not verdict.get("answered")
    ]
    if broken:
        out.append("**Served, and answered nothing**")
        out += [f"- `{model_id}`" for model_id in broken]
        out.append("")
    if report["default_missing"]:
        out.append(
            f"⚠️ `SAGE_DEFAULT_MODEL` is `{config.DEFAULT_MODEL}`, which is not in the "
            "catalogue. The app falls through to the first discovered model, so this is "
            "not an outage — but the configured default is a fiction until it is changed."
        )
        out.append("")
    if report["rule_matched_nothing"]:
        out.append(
            "⚠️ `free_marks` matched nothing served. With `free_only` set the picker "
            "offers the whole paid lineup in this state. This is the one finding here "
            "that is urgent."
        )
        out.append("")
    if report.get("skipped"):
        out.append(
            f"{report['skipped']} unclassified name(s) went unprobed against the "
            "budget; they will be picked up on the next run."
        )
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _verdict_note(verdict: dict) -> str:
    if not verdict:
        return ""
    if verdict.get("status") and verdict["status"] != 200:
        return f" — HTTP {verdict['status']}: {(verdict.get('error') or '')[:120]}"
    if verdict.get("error"):
        return f" — {verdict['error'][:120]}"
    if not verdict.get("answered"):
        return f" — 200 and an empty completion in {verdict.get('seconds')}s"
    parts = [f"{verdict.get('seconds')}s", f"{verdict.get('chars', 0)} chars"]
    if verdict.get("tool_calls"):
        parts.append(f"{verdict['tool_calls']} tool calls")
    else:
        # "did not", not "cannot". The probe asks for a tool call, so declining one is
        # a finding — but a single prompt is not evidence of an incapacity, and
        # `config.TOOLLESS_MODELS` is the place that claim gets made.
        parts.append("declined the offered tool")
    return " — " + ", ".join(parts)


def _days_since(stamp: str | None) -> int | None:
    if not stamp:
        return None
    try:
        return (dt.date.today() - dt.date.fromisoformat(stamp)).days
    except ValueError:
        return None


# --- the run ---------------------------------------------------------------


def run(parsed: argparse.Namespace) -> tuple[int, str, bool]:
    """Returns (exit code, markdown summary, whether anything material changed)."""
    ledger = load_ledger(parsed.ledger)
    entries = discoverable()
    if parsed.provider:
        entries = [item for item in entries if item.name == parsed.provider]
    if not entries:
        return 2, "No discoverable provider in the active profile.\n", False

    sections: list[str] = []
    changed = False
    failed = False

    for entry in entries:
        key = providers.api_key(entry.name)
        try:
            catalogue = served(entry, key)
        except Exception as exc:
            failed = True
            sections.append(
                f"### {entry.name}\n\nCould not list models: "
                f"{scrub(f'{type(exc).__name__}: {exc}')}\n"
            )
            continue

        report = review(entry, catalogue, ledger)
        slot = _slot(ledger, entry.name)
        before = {"free": slot.get("free"), "verdicts": slot.get("verdicts")}

        verdicts: dict = {}
        candidates: list[str] = []
        skipped = 0
        if parsed.probe:
            if not key:
                # No heading: `summarise` writes one for this provider a few lines
                # down, and two in a row reads as two providers.
                sections.append(
                    f"No key in `{entry.key_env}`, so nothing was probed. What follows "
                    "is from the catalogue alone.\n"
                )
            else:
                # New free models get a probe because served is not working. Then the
                # unclassified names, which are the stealth-codename hunt. Budgeted
                # together so a day Zen rewrites its catalogue cannot spend sixty
                # requests, and what the budget dropped is reported rather than
                # silently omitted.
                queue = report["appeared"] + report["unclassified"]
                budget = parsed.probe_budget if parsed.probe_budget > 0 else len(queue)
                skipped = max(0, len(queue) - budget)
                for model_id in queue[:budget]:
                    verdict = probe(entry, key, model_id)
                    verdicts[model_id] = verdict
                    if verdict.get("tier") == "paid":
                        if model_id not in slot["paid"]:
                            slot["paid"].append(model_id)
                    elif (
                        model_id in report["unclassified"]
                        and verdict.get("tier") == "free"
                        and verdict.get("answered")
                    ):
                        candidates.append(model_id)

        report["verdicts"] = {**(slot.get("verdicts") or {}), **verdicts}
        report["candidates"] = candidates
        report["skipped"] = skipped

        reasons = material(before, report)
        if reasons:
            changed = True
        sections.append(summarise(report, reasons))

        slot.update(
            served=catalogue,
            free=report["free"],
            listed=report["listed"],
            missing_since=report["missing_since"],
            verdicts=report["verdicts"],
            candidates=candidates,
            checked=now(),
        )

        if parsed.update and report["appeared"]:
            # A model the profile does not name, that the rule calls free, and that no
            # probe has contradicted. A probe that came back empty or errored holds it
            # back — the whole point of #2 in the docstring.
            additions = [
                model_id
                for model_id in report["appeared"]
                if verdicts.get(model_id, {}).get("answered", True)
            ]
            held = [name for name in report["appeared"] if name not in additions]
            path = _active().origin
            if additions and not path:
                # A deployment running on the built-in defaults has no file to edit.
                # Worth saying rather than raising on `open("")`, because this runs
                # unattended and a traceback in a scheduled job is read as a bug in the
                # job.
                sections.append(
                    "Nothing to update: this profile is the built-in defaults, so "
                    "there is no file to append to. Set `SAGE_PROFILE`.\n"
                )
                additions = []
            if additions:
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                updated = append_models(text, entry.name, additions)
                if updated != text:
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write(updated)
                    sections.append(
                        f"Appended to `{os.path.relpath(path, ROOT)}`: "
                        + ", ".join(f"`{name}`" for name in additions)
                        + "\n"
                    )
            if held:
                sections.append(
                    "Held back, because a probe did not get an answer: "
                    + ", ".join(f"`{name}`" for name in held)
                    + "\n"
                )

    ledger["checked"] = now()
    os.makedirs(os.path.dirname(parsed.ledger) or ".", exist_ok=True)
    with open(parsed.ledger, "w", encoding="utf-8") as handle:
        json.dump(ledger, handle, indent=2, sort_keys=True)
        handle.write("\n")

    body = "\n".join(sections)
    if failed:
        return 2, body, changed
    if changed and parsed.fail_on_drift:
        return 1, body, changed
    return 0, body, changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="", help="just this one")
    parser.add_argument("--ledger", default=LEDGER)
    parser.add_argument(
        "--probe",
        action="store_true",
        help="spend one real completion per new or unclassified model id",
    )
    parser.add_argument(
        "--probe-budget",
        type=int,
        default=12,
        help="most probes one run may spend; 0 for no cap",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="append served free models the profile does not name",
    )
    parser.add_argument("--summary-out", default="", help="write the markdown here")
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="exit 1 when something material changed. Not for CI — see the docstring",
    )
    parsed = parser.parse_args()

    code, body, changed = run(parsed)
    print(body)
    if parsed.summary_out:
        with open(parsed.summary_out, "w", encoding="utf-8") as handle:
            handle.write(body)
    # Read by the workflow to decide whether there is anything worth a pull request.
    step_output = os.getenv("GITHUB_OUTPUT")
    if step_output:
        with open(step_output, "a", encoding="utf-8") as handle:
            handle.write(f"changed={'true' if changed else 'false'}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
