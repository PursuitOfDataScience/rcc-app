"""Words: how they are cut, how they are collapsed, and which ones mean each other.

The stemming rules here are about English, so they are code. Which technical terms
must survive them, and which words are synonyms of which, is about the subject the
corpus is about — so that is data, and it arrives from the profile in a `Vocabulary`.
The previous version had both in one module-level constant, which meant a deployment
about something other than HPC inherited "sbatch is a synonym for script".
"""

from __future__ import annotations

import re

from ..profile import Retrieval

_WORD = re.compile(r"[a-z0-9]+")
_ALNUM_SPLIT = re.compile(r"^([a-z]+)(\d+)$")

# Final consonants that double before `-ed`/`-ing`, so `cancelled` and `cancel`,
# `running` and `run`, `submitting` and `submit` land on one key.
_DOUBLES = frozenset("bdfglmnprt")


def stem(token: str, protected: frozenset[str] = frozenset()) -> str:
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
    if token in protected or len(token) < 4:
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


class Vocabulary:
    """One subject's words: what not to stem, and what stands in for what.

    Built once per profile and handed to the engine, rather than read from a global
    at every call. That is what lets one process index two corpora about two
    different things without their synonym tables leaking into each other.
    """

    def __init__(self, retrieval: Retrieval, synonym_weight: float = 0.8) -> None:
        self.protected = frozenset(term.lower() for term in retrieval.protected)
        self.synonym_weight = synonym_weight
        table: dict[str, set[str]] = {}
        for group in retrieval.synonyms:
            stems = {self.stem(term.lower()) for term in group}
            for key in stems:
                table.setdefault(key, set()).update(stems - {key})
        self.synonyms = table

    def stem(self, token: str) -> str:
        return stem(token, self.protected)

    def tokenize(self, text: str) -> list[str]:
        """Lowercase, stem, and additionally emit the split form of `midway3`.

        Keeping both `midway3` and (`midway`, `3`) means an exact cluster reference
        still wins on its own IDF while the bare name provides recall.
        """
        tokens: list[str] = []
        for raw in _WORD.findall(text.lower()):
            # Single characters are kept: `R` and `C` are languages users ask about,
            # and IDF already drives genuinely ubiquitous letters towards zero weight.
            tokens.append(self.stem(raw))
            split = _ALNUM_SPLIT.match(raw)
            if split:
                tokens.append(self.stem(split.group(1)))
                tokens.append(split.group(2))
        return tokens

    def expand(self, query: str) -> dict[str, float]:
        """Query terms mapped to weights; synonyms enter at a reduced weight."""
        weights: dict[str, float] = {}
        for token in self.tokenize(query):
            weights[token] = max(weights.get(token, 0.0), 1.0)
        for token in list(weights):
            for synonym in self.synonyms.get(token, ()):
                if synonym not in weights:
                    weights[synonym] = self.synonym_weight
        return weights

    def surface_forms(self, query: str) -> dict[str, str]:
        """Stem -> the spelling the reader used, so a caveat can quote words."""
        surface: dict[str, str] = {}
        for raw in _WORD.findall(query.lower()):
            surface.setdefault(self.stem(raw), raw)
        return surface


def snippet(text: str, weights: dict[str, float], width: int) -> str:
    """Excerpt around the best match, in the document's original casing.

    The old implementation sliced a lowercased copy, so `sbatch --gres=gpu:1`
    reached the model as `sbatch --gres=gpu:1` but `Midway3` became `midway3`.
    """
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
