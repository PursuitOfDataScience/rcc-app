"""BM25 over the chunked corpus — the engine this repository ships.

The previous scorer was `+8` title / `+5` path / `+min(count, 5)` body with no IDF
and no length normalization, so a 71 KB publication dump competed on equal footing
with a focused 2 KB page and a term appearing in 100 documents weighed the same as
one appearing in 2. BM25 fixes both, and the profile's synonyms cover the case
keyword search cannot: users describe symptoms ("my job got killed") while docs
describe mechanisms ("OOM", "time limit").

Registered as `bm25`. Everything specific to *this* way of scoring — the k1/b
constants, the title and path boosts, the two confidence thresholds — is read here
and nowhere else, so a second engine is not obliged to have an opinion about them.
"""

from __future__ import annotations

import math
from collections import Counter

from .. import config
from ..corpus import Corpus
from ..profile import Retrieval, active
from .base import Assessment, Result, engines
from .text import Vocabulary, snippet


class Index:
    """In-memory BM25 index. Built once per process and cached by the UI layer."""

    def __init__(
        self,
        corpus: Corpus,
        vocabulary: Vocabulary | None = None,
        documentation: str = "",
    ) -> None:
        self.corpus = corpus
        self.vocabulary = vocabulary or Vocabulary(
            active().retrieval, config.SYNONYM_WEIGHT
        )
        self.documentation = documentation or active().identity.documentation
        self._frequencies: list[Counter[str]] = []
        self._lengths: list[int] = []
        self._titles: list[set[str]] = []
        self._paths: list[set[str]] = []
        self._document_frequency: Counter[str] = Counter()

        tokenize = self.vocabulary.tokenize
        for chunk in corpus.chunks:
            counts = Counter(tokenize(chunk.text))
            self._frequencies.append(counts)
            self._lengths.append(max(sum(counts.values()), 1))
            self._titles.append(set(tokenize(chunk.breadcrumb)))
            self._paths.append(set(tokenize(chunk.path.replace("/", " "))))
            self._document_frequency.update(counts.keys())

        self.total = len(corpus.chunks)
        self.average_length = (
            sum(self._lengths) / self.total if self.total else 1.0
        )

    def _inverse_document_frequency(self, term: str) -> float:
        frequency = self._document_frequency.get(term, 0)
        if not frequency:
            return 0.0
        return math.log(1 + (self.total - frequency + 0.5) / (frequency + 0.5))

    def search(self, query: str, limit: int | None = None) -> list[Result]:
        limit = config.SEARCH_RESULTS if limit is None else limit
        weights = self.vocabulary.expand(query)
        if not weights or not self.total:
            return []

        scored: list[tuple[float, int]] = []
        for position, chunk in enumerate(self.corpus.chunks):
            counts = self._frequencies[position]
            length = self._lengths[position]
            title = self._titles[position]
            path = self._paths[position]
            score = 0.0
            matched = False

            for term, weight in weights.items():
                idf = self._inverse_document_frequency(term)
                if not idf:
                    continue
                frequency = counts.get(term, 0)
                if frequency:
                    matched = True
                    denominator = frequency + config.BM25_K1 * (
                        1 - config.BM25_B
                        + config.BM25_B * length / self.average_length
                    )
                    score += weight * idf * frequency * (config.BM25_K1 + 1) / denominator
                if term in title:
                    matched = True
                    score += weight * idf * config.TITLE_BOOST
                if term in path:
                    matched = True
                    score += weight * idf * config.PATH_BOOST

            if matched and score > 0:
                # The prior travels with the corpus, because it is a statement about
                # these trees — a maintained guide against a scraped site — and not a
                # setting of the scorer.
                score *= self.corpus.weight(chunk.source)
                scored.append((score, position))

        scored.sort(key=lambda item: (-item[0], self.corpus.chunks[item[1]].id))
        return [
            Result(
                chunk=self.corpus.chunks[position],
                score=round(score, 4),
                snippet=snippet(
                    self.corpus.chunks[position].text, weights, config.SNIPPET_CHARS
                ),
            )
            for score, position in self._spread(scored, limit)
        ]

    def assess(self, query: str, results: list[Result] | None = None) -> Assessment:
        """Judge a query's retrieval without re-ranking it."""
        if results is None:
            results = self.search(query)
        surface = self.vocabulary.surface_forms(query)

        unknown = []
        for term, weight in self.vocabulary.expand(query).items():
            if weight < 1.0:
                continue          # a synonym the reader never typed
            if any(character.isdigit() for character in term):
                # A job ID or a node number is not a topic the documentation could
                # have a section about, and counting one as an unseen word told a
                # reader asking why job 41235567 failed that RCC has no docs on it.
                continue
            if self._document_frequency.get(term):
                continue
            if any(term in title for title in self._titles):
                continue
            unknown.append(surface.get(term, term))

        top = results[0].score if results else 0.0
        runner_up = results[1].score if len(results) > 1 else 0.0
        return Assessment(
            top_score=top,
            margin=round(top - runner_up, 4),
            unknown_terms=tuple(unknown),
            documentation=self.documentation,
            min_confident_score=config.MIN_CONFIDENT_SCORE,
            strong_score=config.STRONG_SCORE,
        )

    def _spread(
        self, scored: list[tuple[float, int]], limit: int
    ) -> list[tuple[float, int]]:
        """The best `limit`, but no more than `MAX_PER_PAGE` sections of one page.

        Without this, a third of the golden-set questions came back with all of the
        top three from a single page: a search asked for six sections and really
        returned two pages' worth, so the model saw one page's view of the answer and
        never learned that another page contradicted or completed it.

        The cap is a trade, not a free win, and the thing it trades away is invisible
        to a page-level eval: every slot given to a second page is a slot taken from
        the depth of the first. `MAX_PER_PAGE` is the dial. See config for what the
        measurements said about where to set it.

        Overflow is deferred, not discarded: once every page has had its share the
        leftovers backfill in score order, so a query that genuinely only matches one
        page still returns a full set of results rather than a short list.
        """
        if limit <= 0:
            return []
        cap = max(1, config.MAX_PER_PAGE)
        kept: list[tuple[float, int]] = []
        deferred: list[tuple[float, int]] = []
        seen: Counter[str] = Counter()
        for score, position in scored:
            chunk = self.corpus.chunks[position]
            page = f"{chunk.source}/{chunk.path}"
            if seen[page] >= cap:
                deferred.append((score, position))
                continue
            seen[page] += 1
            kept.append((score, position))
            if len(kept) >= limit:
                return kept
        return (kept + deferred)[:limit]


def build(corpus: Corpus, retrieval: Retrieval, documentation: str = "") -> Index:
    return Index(
        corpus, Vocabulary(retrieval, config.SYNONYM_WEIGHT), documentation
    )


engines.register("bm25", build)
