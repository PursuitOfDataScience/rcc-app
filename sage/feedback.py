"""Optional thumbs-up/down sink.

Answer ratings are the cheapest way to learn which pages are missing or wrong, and
queries that retrieve nothing are a documentation backlog in disguise. Both are
recorded only when `SAGE_FEEDBACK_LOG` names a writable file, so the default
deployment stores nothing.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from . import config, scrub

logger = logging.getLogger(__name__)

# What a thumbs-down was actually about. A bare verdict conflates three different
# failures with three different owners: retrieval, generation, and the documentation
# itself. Fixed categories rather than free text because they get completed, and
# because each one routes somewhere.
REASONS: tuple[tuple[str, str], ...] = (
    ("wrong", "Wrong or misleading"),
    ("missing", "Not covered by the docs"),
    ("irrelevant", "Cited the wrong section"),
    ("outdated", "Out of date"),
    ("unclear", "Hard to follow"),
)
REASON_KEYS = frozenset(key for key, _label in REASONS)


def enabled() -> bool:
    return bool(config.FEEDBACK_LOG)


def _write(payload: dict) -> bool:
    if not enabled():
        return False
    payload["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Fail closed. A credential shape surviving the scrubber drops the whole record:
    # losing one log line is cheaper than storing one key.
    for field in ("question", "answer", "detail"):
        value = payload.get(field)
        if isinstance(value, str) and scrub.contains_secret(value):
            logger.warning("Dropping a %s record: a secret survived scrubbing",
                           payload.get("kind"))
            return False
    try:
        directory = os.path.dirname(config.FEEDBACK_LOG)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(config.FEEDBACK_LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return True
    except OSError as exc:
        logger.warning("Could not write feedback: %s", exc)
        return False


def record_rating(
    verdict: str,
    question: str,
    answer: str,
    sources: list[dict],
    reason: str = "",
    model: str = "",
) -> bool:
    return _write(
        {
            "kind": "rating",
            "verdict": verdict,
            "reason": reason if reason in REASON_KEYS else "",
            "model": model,
            "question": scrub.scrub(question)[:1000],
            "answer": scrub.scrub(answer)[:4000],
            "sources": [source.get("id", "") for source in sources],
        }
    )


def record_miss(queries: list[str], question: str) -> bool:
    """A turn whose searches returned nothing useful."""
    return _write(
        {
            "kind": "miss",
            "queries": [scrub.scrub(query)[:200] for query in queries[:10]],
            "question": scrub.scrub(question)[:1000],
        }
    )


def record_turn(event: dict) -> bool:
    """One row per answered turn: the table every metric is a GROUP BY over.

    Deliberately one flat event rather than a metrics system. What was missing was
    never a backend, it was a schema and the habit of writing to it — and the
    highest-value fields here are the ones that were already sitting in local
    variables and being thrown away: the queries issued, the top score, whether a
    search missed, which model answered, whether history was trimmed.

    Field names follow the OpenTelemetry GenAI conventions where one exists, so
    replaying this into a real tracing backend later is a script rather than a
    migration.
    """
    payload = dict(event)
    payload["kind"] = "turn"
    for field in ("question", "answer"):
        if field in payload:
            payload[field] = scrub.scrub(str(payload[field]))[:2000]
    if "queries" in payload:
        payload["queries"] = [
            scrub.scrub(str(query))[:200] for query in payload["queries"][:10]
        ]
    return _write(payload)
