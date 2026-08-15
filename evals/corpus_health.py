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


def indexing_nothing(corpus) -> list[str]:
    """Pages the builder accepted and got no chunks out of.

    `empty_documents` asks how big a file is; this asks what came out of it, which is the
    question that matters and the one that survives a change to the reader. A 5 KB page
    that indexes to nothing — a reader that stops recognising a heading style, a section
    below `MIN_CHUNK_CHARS` after normalisation — is caught only here, and `self_reachability`
    cannot see it either, because a page with no chunks never enters the list to check.

    Read off the corpus rather than by walking the disk, which is what makes it exact: a
    page excluded on purpose (`exclude_files`, `exclude_hosts` — the publication dumps and
    the radiology scrape) never becomes a Document at all, while a page that was read and
    yielded nothing becomes one with no chunks. A first attempt walked the tree and
    reported all thirteen deliberate exclusions as problems.
    """
    with_chunks = {f"{chunk.source}/{chunk.path}" for chunk in corpus.chunks}
    return sorted(page for page in corpus.documents if page not in with_chunks)


def duplicates(corpus) -> dict:
    """Sections that say the same thing twice.

    Two costs, both already paid once here. A duplicate takes one of the six result slots
    the model is handed, and it arrives in the Sources strip as the same page listed
    twice — which is what "Show each destination once" and "Stop citing the same section
    twice" were both about. The User Guide and the scraped website overlap by
    construction, so cross-source pairs are expected; the count is what matters.
    """
    exact: dict[str, list[str]] = {}
    titles: dict[str, set[str]] = {}
    for chunk in corpus.chunks:
        digest = hashlib.sha1(_normalise(chunk.text).encode()).hexdigest()
        exact.setdefault(digest, []).append(chunk.id)
        titles.setdefault(digest, set()).add(chunk.doc_title)

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
    # Two very different things, and counting them together makes the number unreadable.
    # Identical text under ONE title is a page indexed twice — `web/midway2.txt` and
    # `web/support-and-services_midway2.txt` are the same RCC page at two URLs — and it
    # wastes a result slot. Identical text under DIFFERENT titles is shared boilerplate:
    # `bfi.md` and `booth.md` document two databases with the same Globus instructions,
    # and each must keep its own citation. Deduplicating the index would have answered a
    # Booth question with a link to the BFI page.
    repeated = [ids for ids in exact.values() if len(ids) > 1]
    same_page = [
        ids for digest, ids in exact.items()
        if len(ids) > 1 and len(titles[digest]) == 1
    ]
    return {
        "exact_groups": repeated,
        "same_page_twice": same_page,
        "shared_boilerplate": [ids for ids in repeated if ids not in same_page],
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


def self_reachability(index, corpus) -> dict:
    """Can each page be found by asking for it by its own title?

    The honest version of the reachability question, and it took two tries. Asking the 77
    labelled questions and reporting "160 of 572 chunks surfaced" says nothing about the
    index — 77 questions at six results is a ceiling of 462 — so that number stays
    unmeasurable by construction.

    The obvious next attempt, one query per *section*, measured the wrong thing too: it
    reported 72 sections unreachable, and they were sections like `sbatch.md#batch-jobs`
    losing to two siblings of their own page. That is `MAX_PER_PAGE` doing its job, not
    dead weight — the page is retrieved and `read_doc` reaches the section by anchor. A
    metric that moves when the cap moves is a statement about the cap.

    Page granularity is unaffected by it: the cap allows two sections of any page and this
    needs one. A page that cannot be retrieved when the query *is* its own title is weight
    the index carries and no reader can reach.
    """
    titles: dict[str, str] = {}
    for chunk in corpus.chunks:
        titles.setdefault(f"{chunk.source}/{chunk.path}", chunk.doc_title)

    unreachable = []
    for page, title in titles.items():
        if not title.strip():
            unreachable.append(page)
            continue
        found = {
            f"{result.chunk.source}/{result.chunk.path}"
            for result in index.search(title, SEARCH_LIMIT)
        }
        if page not in found:
            # The title travels with it: two of the seven are unreachable *because* of
            # their title. `singularity.md` is titled "Modules" upstream, so every
            # citation chip for it reads "Modules — …", and `MidwayGeoSpatial` returns
            # nothing at all because a CamelCase compound is one token the page's own
            # text never uses. Reporting the page alone hid both.
            unreachable.append({"page": page, "title": title})
    total = len(titles) or 1
    return {
        "pages": len(titles),
        "unreachable": unreachable,
        "rate": (total - len(unreachable)) / total,
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


def malformed_urls(corpus) -> list[dict]:
    """Citation targets that are not usable web addresses.

    "Has a URL" was the only thing asked, and a citation is the one string in this app
    that becomes an `href`. A URL with a space in it, two fragment markers, a control
    character or no scheme is a link that lands nowhere — and unlike a wrong *page*,
    nothing downstream notices: `tools/anchor_check.py` validates against the live site
    but is network-bound and out of the suite.
    """
    found = []
    for chunk in corpus.chunks:
        url = chunk.url
        why = ""
        if not url.startswith(("http://", "https://")):
            why = "no http scheme"
        elif url != url.strip() or " " in url:
            why = "whitespace"
        elif url.count("#") > 1:
            why = "two fragment markers"
        elif any(ord(character) < 32 for character in url):
            why = "control character"
        if why:
            found.append({"id": chunk.id, "url": url[:80], "why": why})
    return found


def unregistered_names(profile) -> list[dict]:
    """Names the profile hands to a registry that nothing has registered.

    Each of the five seams fails differently on a typo, and only two of them fail in a way
    anybody would notice. A bad `links` scheme or `retrieval.engine` raises at boot with the
    registry's own list of valid names, which is the right behaviour. A bad `reader` is
    deliberate the other way: `corpus.build` logs it and skips that source, so a
    multi-source deployment keeps working — and a single-source one boots looking healthy
    and answers every question with "the documentation does not appear to cover it", which
    is this app's worst state.

    So the names are checked directly, before anything is built, where a typo is one line
    with the valid names next to it rather than an empty corpus.
    """
    # `sage.corpus.readers` the *name* is the registry, not the module — the package
    # rebinds it. The URL schemes keep theirs inside the module.
    from sage.corpus import readers as reader_registry
    from sage.corpus.urls import schemes as url_registry
    from sage.providers import adapters
    from sage.retrieval import engines
    from sage.tools import factories

    wrong = []

    def check(kind: str, where: str, name: str, registry) -> None:
        if name and name not in registry:
            wrong.append(
                {
                    "kind": kind,
                    "where": where,
                    "name": name,
                    "registered": list(registry.names()),
                }
            )

    for source in profile.sources:
        check("reader", f"sources.{source.name}", source.reader, reader_registry)
        check("url scheme", f"sources.{source.name}", source.links, url_registry)
    check("retrieval engine", "retrieval", profile.retrieval.engine, engines)
    for entry in profile.providers:
        check("provider kind", f"providers.{entry.name}", entry.kind, adapters)
    for name in ("search_docs", "read_doc"):
        check("tool", "tools", name, factories)
    return wrong


def measure(corpus, index) -> dict:
    asked = [case.text for case in questions()] + [case.text for case in identifiers()]
    return {
        "unregistered_names": unregistered_names(_active()),
        "chunks": index.total,
        "sources": sources(corpus),
        "empty_documents": empty_documents(),
        "indexing_nothing": indexing_nothing(corpus),
        "duplicates": duplicates(corpus),
        "reachability": reachability(index, asked),
        "self_reachability": self_reachability(index, corpus),
        "topics": topic_coverage(index),
        "unresolvable_ids": unresolvable_ids(corpus),
        "chunks_without_url": chunks_without_url(corpus),
        "malformed_urls": malformed_urls(corpus),
        "freshness": config.snapshot(),
    }
