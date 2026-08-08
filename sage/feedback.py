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

from . import config

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(config.FEEDBACK_LOG)


def _write(payload: dict) -> bool:
    if not enabled():
        return False
    payload["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
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
    verdict: str, question: str, answer: str, sources: list[dict]
) -> bool:
    return _write(
        {
            "kind": "rating",
            "verdict": verdict,
            "question": question[:1000],
            "answer": answer[:4000],
            "sources": [source.get("id", "") for source in sources],
        }
    )


def record_miss(queries: list[str], question: str) -> bool:
    """A turn whose searches returned nothing useful."""
    return _write(
        {"kind": "miss", "queries": queries[:10], "question": question[:1000]}
    )
