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


def record_turn(
    *,
    question: str,
    outcome: str,
    model: str,
    error_kind: str = "",
    rounds: int = 0,
    searches: int = 0,
    sections: int = 0,
    caveats: int = 0,
    sources: int = 0,
    seconds: float = 0.0,
) -> bool:
    """One line of mechanics per turn: what it cost and how it ended.

    Everything under `evals/` measures this app against questions somebody wrote down.
    That is a guess at what readers ask, and it is the only guess in the whole programme
    that cannot be checked offline — so this is the other end of it. A week of these says
    which questions arrive, how many rounds they really take, how often the refusal gate
    fires on live traffic against the 86.7% it scores on the labelled set, and which of
    `llm.classify`'s failure kinds a deployment actually sees.

    No answer text, and no ratings: `record_rating` already handles the reader's verdict
    and quotes them. What is here is arithmetic plus the question, which is what turns a
    log into a question set — and the question is logged because `record_miss` and
    `record_rating` already log it, so this adds no new kind of disclosure. As with both
    of those, nothing is written at all unless `SAGE_FEEDBACK_LOG` names a file.
    """
    return _write(
        {
            "kind": "turn",
            "question": question[:1000],
            "outcome": outcome,
            "model": model,
            "error_kind": error_kind,
            "rounds": rounds,
            # Sections the turn exposed, against `sources` — the destinations the
            # reader is shown, which is fewer whenever two sections share a page.
            "searches": searches,
            "sections": sections,
            "caveats": caveats,
            "sources": sources,
            "seconds": round(seconds, 2),
        }
    )
