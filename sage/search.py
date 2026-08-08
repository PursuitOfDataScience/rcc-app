"""BM25 retrieval over the chunked corpus.

The previous scorer was `+8` title / `+5` path / `+min(count, 5)` body with no IDF
and no length normalization, so a 71 KB publication dump competed on equal footing
with a focused 2 KB page and a term appearing in 100 documents weighed the same as
one appearing in 2. BM25 fixes both, and domain synonyms cover the case keyword
search cannot: users describe symptoms ("my job got killed") while docs describe
mechanisms ("OOM", "time limit").
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from . import config
from .corpus import Chunk, Corpus

_WORD = re.compile(r"[a-z0-9]+")
_ALNUM_SPLIT = re.compile(r"^([a-z]+)(\d+)$")

# Stemming these would help nothing and hurt matching.
_PROTECTED = frozenset(
    {
        "gres",
        "globus",
        "https",
        "lammps",
        "gromacs",
        "dss",
        "hpss",
        "tmux",
        "linux",
        "emacs",
    }
)

# Bidirectional groups. Members are expanded at query time only, at a reduced
# weight, so an exact match always outranks a synonym match.
_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("ssh", "login", "connect", "logon"),
    ("thinlinc", "vdi", "desktop", "gui"),
    ("sbatch", "batch", "submit", "script"),
    ("sinteractive", "srun", "interactive", "salloc"),
    ("squeue", "sacct", "status", "queue"),
    ("partition", "queue", "qos"),
    ("scavenge", "preemptible", "preempt"),
    ("oom", "memory", "killed", "cancelled", "timeout"),
    ("quota", "limit", "usage", "space"),
    ("allocation", "su", "balance", "accounts"),
    ("module", "software", "lmod", "package"),
    ("conda", "venv", "environment", "virtualenv", "mamba"),
    ("globus", "transfer", "scp", "rsync", "upload", "download"),
    ("gpu", "cuda", "a100", "v100", "nvidia"),
    ("scratch", "temporary", "purge"),
    ("project", "shared", "group"),
    ("cnetid", "account", "username"),
    ("midway", "cluster", "hpc"),
    ("snapshot", "backup", "restore", "recover"),
)


def _stem(token: str) -> str:
    if token in _PROTECTED or len(token) < 4:
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("sses"):
        return token[:-2]
    if token.endswith("es") and len(token) > 4:
        return token[:-1]
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lowercase, stem, and additionally emit the split form of `midway3`.

    Keeping both `midway3` and (`midway`, `3`) means an exact cluster reference
    still wins on its own IDF while the bare name provides recall.
    """
    tokens: list[str] = []
    for raw in _WORD.findall(text.lower()):
        # Single characters are kept: `R` and `C` are languages users ask about,
        # and IDF already drives genuinely ubiquitous letters towards zero weight.
        tokens.append(_stem(raw))
        split = _ALNUM_SPLIT.match(raw)
        if split:
            tokens.append(_stem(split.group(1)))
            tokens.append(split.group(2))
    return tokens


def _build_synonyms() -> dict[str, set[str]]:
    table: dict[str, set[str]] = {}
    for group in _SYNONYM_GROUPS:
        stems = {_stem(term) for term in group}
        for stem in stems:
            table.setdefault(stem, set()).update(stems - {stem})
    return table


_SYNONYMS = _build_synonyms()


def expand_query(query: str) -> dict[str, float]:
    """Query terms mapped to weights; synonyms enter at a reduced weight."""
    weights: dict[str, float] = {}
    for token in tokenize(query):
        weights[token] = max(weights.get(token, 0.0), 1.0)
    for token in list(weights):
        for synonym in _SYNONYMS.get(token, ()):
            if synonym not in weights:
                weights[synonym] = config.SYNONYM_WEIGHT
    return weights


@dataclass
class Result:
    chunk: Chunk
    score: float
    snippet: str

    @property
    def id(self) -> str:
        return self.chunk.id

    @property
    def label(self) -> str:
        return self.chunk.label

    @property
    def url(self) -> str:
        return self.chunk.url

    @property
    def source(self) -> str:
        return self.chunk.source


class Index:
    """In-memory BM25 index. Built once per process and cached by the UI layer."""

    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus
        self._frequencies: list[Counter[str]] = []
        self._lengths: list[int] = []
        self._titles: list[set[str]] = []
        self._paths: list[set[str]] = []
        self._document_frequency: Counter[str] = Counter()

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
        weights = expand_query(query)
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
                score *= config.SOURCE_WEIGHT.get(chunk.source, 1.0)
                scored.append((score, position))

        scored.sort(key=lambda item: (-item[0], self.corpus.chunks[item[1]].id))
        return [
            Result(
                chunk=self.corpus.chunks[position],
                score=round(score, 4),
                snippet=snippet(self.corpus.chunks[position].text, weights),
            )
            for score, position in scored[:limit]
        ]


def snippet(text: str, weights: dict[str, float], width: int | None = None) -> str:
    """Excerpt around the best match, in the document's original casing.

    The old implementation sliced a lowercased copy, so `sbatch --gres=gpu:1`
    reached the model as `sbatch --gres=gpu:1` but `Midway3` became `midway3`.
    """
    width = config.SNIPPET_CHARS if width is None else width
    lowered = text.lower()
    best = -1
    for term in sorted(weights, key=lambda item: -weights[item]):
        position = lowered.find(term)
        if position != -1 and (best == -1 or position < best):
            best = position

    start = 0 if best <= 0 else max(0, best - 70)
    if start:
        space = text.find(" ", start)
        start = space + 1 if 0 <= space < start + 25 else start
    excerpt = re.sub(r"\s+", " ", text[start : start + width]).strip()

    prefix = "…" if start > 0 else ""
    suffix = "…" if start + width < len(text) else ""
    return f"{prefix}{excerpt}{suffix}"
