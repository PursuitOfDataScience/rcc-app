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
    # No "cancelled" here. It was added for "my job was cancelled by the scheduler",
    # which is an OOM or a timeout — but now that verb inflections collapse, it keys on
    # `cancel`, and *the user cancelling their own job* is the opposite question. It
    # made "cancel a running job" retrieve the exceeded-memory FAQ ahead of the page
    # about scancel. The words that carry the meaning are the other four.
    ("oom", "memory", "killed", "timeout"),
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


# Final consonants that double before `-ed`/`-ing`, so `cancelled` and `cancel`,
# `running` and `run`, `submitting` and `submit` land on one key.
_DOUBLES = frozenset("bdfglmnprt")


def _stem(token: str) -> str:
    """Collapse plurals *and* verb inflections onto one key.

    This stripped plurals only, while claiming to be "Porter-ish". The gap was not
    cosmetic: `preempted` stayed `preempted`, so the synonym group ("scavenge",
    "preemptible", "preempt") — written for exactly that query — could never fire, and
    `purged`, `running`, `exceeded`, `installed` and `submitting` all failed to reach
    the documentation's own wording.

    The output is a key, not a word: `purge` and `purged` both become `purg`. That is
    fine because the same function stems the index and the query, and it is why the
    silent `-e` is dropped — without it `purge`/`purges` would key on `purge` while
    `purged`/`purging` keyed on `purg`, which is the bug in a new place.
    """
    if token in _PROTECTED or len(token) < 4:
        return token
    original = token

    if token.endswith("ies") and len(token) > 4:
        token = token[:-3] + "y"
    elif token.endswith("sses"):
        token = token[:-2]
    elif (token.endswith("es") and len(token) > 4) or (
        token.endswith("s") and not token.endswith("ss")
    ):
        token = token[:-1]

    plural = token
    # A gerund is usually a *thing* in technical prose — "scoring", "sharing",
    # "mapping", "logging" — so a short stem of one stops being the same word: it was
    # `scoring` → `scor`, which matched a GIS page titled "Match Score" and scored a
    # radiology question the corpus cannot answer at 28.7 on a title boost.
    # `-ed` forms are almost always verbs, so they keep the shorter floor and
    # `purged` → `purg` still reaches the documentation's "purge".
    floor = 5
    inflected = False
    if token.endswith("ing") and len(token) > 5:
        token, inflected = token[:-3], True
    elif token.endswith("ed") and not token.endswith("eed") and len(token) > 4:
        # `eed` is excluded so `exceed` is not mistaken for an inflection of `exce` —
        # it would then never match `exceeded`, which is the exact phrasing of the OOM
        # message in docs/slurm/faq.md.
        token, inflected = token[:-2], True
        floor = 4

    if len(token) > 3 and token[-1] == token[-2] and token[-1] in _DOUBLES:
        token = token[:-1]
    if len(token) > 3 and token.endswith("e"):
        token = token[:-1]

    # A three-letter verb stem is `run`, `get`, `set`, `mak` — English scaffolding
    # every page uses and no page is about. Collapsing `running` onto `run` hands that
    # key the frequency of both and IDF charges for it: measured on the golden set,
    # doing so cost 2.9pp of recall@3 and recall@5 and dropped "what clusters does RCC
    # run" out of the top five entirely, because `ecosystems.md` lost its edge over
    # every page that merely mentions running something. Inflections of a *topical*
    # verb — preempted, purged, exceeded, submitting — are four letters or more and
    # still collapse, which is the whole reason to stem verbs at all.
    if inflected and len(token) < floor:
        return plural

    return token if len(token) >= 3 else original


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
class Assessment:
    """Whether a query looks answerable, from properties of *this* retrieval.

    Deliberately not a percentage. BM25 scores are unnormalised sums of IDF-weighted
    contributions plus title and path boosts and a source multiplier; they are not
    comparable across queries, and turning one into "87% confident" would be theatre.
    Everything here is a checkable fact instead: how well the top hit scored, how far
    ahead of the runner-up it is, and which query words appear nowhere in the corpus.

    `unknown_terms` holds the words as the reader typed them, not the stems they were
    matched on. Quoting stems put "No section contains: prostat, unspecifi, instal" in
    front of a model and asked it to relay that to a person.
    """

    top_score: float = 0.0
    margin: float = 0.0
    unknown_terms: tuple[str, ...] = ()

    @property
    def strong(self) -> bool:
        """Enough evidence that an unrecognised word does not overturn it.

        A question can be perfectly answerable and still contain a word the docs have
        never seen — a job ID, a CNetID, the name of a daemon in an error message. That
        is the common case, not the exception, and treating any unknown word as
        disqualifying is what made this idea unusable the first time round.
        """
        return self.top_score >= config.STRONG_SCORE

    @property
    def confident(self) -> bool:
        if self.top_score < config.MIN_CONFIDENT_SCORE:
            return False
        return self.strong or not self.unknown_terms

    def caveat(self) -> str:
        """One honest sentence for the model, empty when retrieval looks sound."""
        if self.confident:
            return ""
        if self.unknown_terms:
            missing = ", ".join(sorted(self.unknown_terms))
            return (
                f"No section of the RCC documentation mentions: {missing}. The results "
                "below matched the other words only, so they are probably not about "
                "what was asked. Say the documentation does not appear to cover it "
                "rather than answering from these."
            )
        return (
            "These are weak matches and may not answer the question. If they do not, "
            "say the documentation does not appear to cover it."
        )


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
            for score, position in self._spread(scored, limit)
        ]

    def assess(self, query: str, results: list[Result] | None = None) -> Assessment:
        """Judge a query's retrieval without re-ranking it."""
        if results is None:
            results = self.search(query)
        # Stem -> the spelling the reader used, so the caveat can quote words rather
        # than search keys.
        surface: dict[str, str] = {}
        for raw in _WORD.findall(query.lower()):
            surface.setdefault(_stem(raw), raw)

        unknown = []
        for term, weight in expand_query(query).items():
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
