"""Axis C: what the corpus can and cannot answer, before any model is involved.

The app's ceiling is its documents. No prompt, model or ranking change can answer a
question the corpus does not contain, so a benchmark that measures the app without
measuring the corpus attributes the corpus's limits to the app — and the corpus is the
cheaper thing to fix.

Reachability is reported with its own ceiling attached, and no percentage is offered when
the ceiling is below the chunk count. An earlier version of this reported "20.6% of
chunks reachable" from 50 questions at six results each — 300 slots for 572 chunks —
which is a statement about the question set that reads as a statement about the index.
"""

from __future__ import annotations

import hashlib
import os
import re

from sage import config
from sage.profile import active as _active

from . import identifiers, questions

SEARCH_LIMIT = 6
TINY_DOC_BYTES = 200
SHINGLE = 5
NEAR_DUPLICATE = 0.8


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _shingles(text: str) -> set[str]:
    words = _normalise(text).split()
    if len(words) < SHINGLE:
        return {" ".join(words)} if words else set()
    return {
        " ".join(words[index:index + SHINGLE])
        for index in range(len(words) - SHINGLE + 1)
    }


def sources(corpus) -> dict:
    out: dict[str, dict] = {}
    for chunk in corpus.chunks:
        bucket = out.setdefault(chunk.source, {"chunks": 0, "chars": 0, "pages": set()})
        bucket["chunks"] += 1
        bucket["chars"] += len(chunk.text)
        bucket["pages"].add(chunk.path)
    return {
        name: {
            "chunks": row["chunks"], "chars": row["chars"], "pages": len(row["pages"])
        }
        for name, row in out.items()
    }


def empty_documents() -> list[dict]:
    """Files on disk with nothing in them — a topic the app cannot answer at all.

    Walked from the profile's own source list, so the paths are the ones the corpus was
    built from, environment overrides included.
    """
    found = []
    for source in _active().sources:
        root = source.path
        if not os.path.isdir(root):
            continue
        for base, _dirs, files in os.walk(root):
            for name in sorted(files):
                if not any(name.endswith(ext) for ext in source.extensions):
                    continue
                full = os.path.join(base, name)
                size = os.path.getsize(full)
                if size < TINY_DOC_BYTES:
                    found.append(
                        {
                            "source": source.name,
                            "path": os.path.relpath(full, root),
                            "bytes": size,
                        }
                    )
    return found


def duplicates(corpus) -> dict:
    """Sections that say the same thing twice.

    Two costs, both already paid once here. A duplicate takes one of the six result slots
    the model is handed, and it arrives in the Sources strip as the same page listed
    twice — which is what "Show each destination once" and "Stop citing the same section
    twice" were both about. The User Guide and the scraped website overlap by
    construction, so cross-source pairs are expected; the count is what matters.
    """
    exact: dict[str, list[str]] = {}
    for chunk in corpus.chunks:
        digest = hashlib.sha1(_normalise(chunk.text).encode()).hexdigest()
        exact.setdefault(digest, []).append(chunk.id)

    # Near-duplicates, compared only within a length band so this stays fast enough to
    # belong in a check rather than a job.
    prints = [(chunk, _shingles(chunk.text)) for chunk in corpus.chunks]
    prints.sort(key=lambda pair: len(pair[1]))
    near: list[dict] = []
    for index, (chunk, marks) in enumerate(prints):
        if not marks:
            continue
        for other, other_marks in prints[index + 1:]:
            if len(other_marks) > len(marks) * 1.35:
                break
            if not other_marks:
                continue
            overlap = len(marks & other_marks) / len(marks | other_marks)
            if overlap >= NEAR_DUPLICATE and _normalise(chunk.text) != _normalise(other.text):
                near.append(
                    {
                        "a": chunk.id,
                        "b": other.id,
                        "overlap": round(overlap, 2),
                        "cross_source": chunk.source != other.source,
                    }
                )
                break
    return {
        "exact_groups": [ids for ids in exact.values() if len(ids) > 1],
        "near": near,
    }


def reachability(index, asked: list[str]) -> dict:
    """How much of the index a realistic question set ever surfaces.

    Reported with the ceiling, because the ceiling is usually the binding constraint:
    `len(asked) * SEARCH_LIMIT` is the most that *could* be touched, and a percentage
    computed without it says nothing about dead index weight.
    """
    touched: set[str] = set()
    for question in asked:
        touched.update(result.chunk.id for result in index.search(question, SEARCH_LIMIT))
    ceiling = len(asked) * SEARCH_LIMIT
    return {
        "questions": len(asked),
        "touched": len(touched),
        "ceiling": ceiling,
        "total": index.total,
        "measurable": ceiling >= index.total,
    }


def topic_coverage(index) -> list[dict]:
    """Every topic the profile advertises, asked about in its own words.

    `identity.topics` is what `search_docs` tells the model it covers. A topic that comes
    back caveated is a promise the app breaks on the one question a reader most expects
    it to handle — though note that a one-word query is a hard case for an unnormalised
    score, which is itself worth knowing.
    """
    names = [
        part.strip()
        for part in re.split(r",| or ", _active().identity.topics)
        if part.strip()
    ]
    out = []
    for name in names:
        assessment = index.assess(name)
        top = index.search(name, 1)
        out.append(
            {
                "topic": name,
                "confident": bool(assessment.confident),
                "score": round(assessment.top_score, 1),
                "top_page": top[0].chunk.path if top else "",
            }
        )
    return out


def unresolvable_ids(corpus) -> list[str]:
    """Every chunk id must resolve back to its chunk.

    `read_doc` resolves against the in-memory corpus and nothing else, so an id
    `search_docs` can advertise but `read_doc` cannot resolve is a dead end the model has
    to recover from. The existing suite checks this for the first twelve golden cases;
    this checks all of them.
    """
    return [chunk.id for chunk in corpus.chunks if corpus.chunk(chunk.id) is None]


def chunks_without_url(corpus) -> list[str]:
    return [chunk.id for chunk in corpus.chunks if not chunk.url]


def measure(corpus, index) -> dict:
    asked = [case.text for case in questions()] + [case.text for case in identifiers()]
    return {
        "chunks": index.total,
        "sources": sources(corpus),
        "empty_documents": empty_documents(),
        "duplicates": duplicates(corpus),
        "reachability": reachability(index, asked),
        "topics": topic_coverage(index),
        "unresolvable_ids": unresolvable_ids(corpus),
        "chunks_without_url": chunks_without_url(corpus),
        "freshness": config.snapshot(),
    }
