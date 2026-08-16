"""Words: how they are cut, how they are collapsed, and which ones mean each other.

The stemming rules here are about English, so they are code. Which technical terms
must survive them, and which words are synonyms of which, is about the subject the
corpus is about — so that is data, and it arrives from the profile in a `Vocabulary`.
The previous version had both in one module-level constant, which meant a deployment
about something other than HPC inherited "sbatch is a synonym for script".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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


@dataclass(frozen=True)
class Mention:
    """One word as the reader actually typed it, with the shape of its surroundings.

    `tokenize` lowercases and stems, which is right for matching and throws away the two
    things that say whether an unfamiliar word names a *thing* or carries a *value*: how
    the reader capitalised it, and what stands in front of it. "Frontera" and "jsmith" are
    both words this corpus has never seen; only one of them is a topic the documentation
    could have had a section about.
    """

    word: str
    stem: str
    #: Capitalised, including all-caps: `Frontera`, `ANSYS`, `VASP`.
    capitalized: bool
    #: First word, or straight after `:`/`.`/`!`/`?` — where capitalisation says nothing.
    #: "srun: error: … failed: Unspecified error" capitalises a word that is not a name.
    after_boundary: bool
    #: The whole query is upper case, so capitalisation distinguishes nothing at all.
    #: Without this, "MY JOB WAS KILLED BY SLURMSTEPD" refused over `slurmstepd` while
    #: the same sentence in ordinary case answered — readers paste error messages in
    #: caps, and a rule that reads shouting as a proper noun punishes them for it.
    shouting: bool
    #: The word before it, lowercased, or "".
    previous: str
    #: Inside a URL the reader pasted. Every label of a hostname is a name by
    #: construction — nobody types `tacc.utexas.edu` as a value — and inside one the two
    #: signals above are both blind: the labels are lower case and no preposition
    #: introduces them. Measured: `how do I use https://frontera.tacc.utexas.edu` scored
    #: 27.4 with `frontera`, `tacc` and `utexas` all unknown, and the gate stayed
    #: confident, so no caveat reached the model about another centre's machine.
    in_address: bool = False


_MENTION = re.compile(r"[A-Za-z0-9]+")
_BOUNDARY = frozenset(":.!?;")
# A pasted address. Scheme-anchored on purpose: a bare dotted host — `frontera.tacc.edu`
# with no scheme — is not matched, because the same shape is a filename (`sbatch.md`,
# `job.sh`, `python3.11`) and a rule that read those as names would refuse the
# `[[identifier]]` cases this classifier exists to keep answerable.
_ADDRESS = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def mentions(query: str, stemmer=None) -> list[Mention]:
    """Every word of the query in the order typed, with its shape.

    Deliberately over the raw string rather than the tokenizer's output: the tokenizer
    has already lowercased by the time anything can read a capital letter.
    """
    stem_of = stemmer or (lambda word: stem(word))
    # Decided once for the whole query: a sentence with no lower-case letter in it is
    # shouting, and every word in it is "capitalised" for reasons that say nothing about
    # which words are names.
    shouting = not any(character.islower() for character in query)
    addresses = [match.span() for match in _ADDRESS.finditer(query)]
    found: list[Mention] = []
    previous = ""
    for match in _MENTION.finditer(query):
        word = match.group(0)
        before = query[: match.start()].rstrip()
        shape = {
            "word": word,
            "capitalized": word[:1].isupper(),
            "shouting": shouting,
            "after_boundary": not before or before[-1] in _BOUNDARY,
            "previous": previous,
            "in_address": any(
                start <= match.start() < end for start, end in addresses
            ),
        }
        found.append(Mention(stem=stem_of(word.lower()), **shape))
        # `tokenize` also emits the split form of `Stampede3` — (`stampede`, `3`) — and it
        # is the split form that ends up in the unknown-term list, because the whole token
        # carries a digit. Without a mention under that stem too, the word arrived at the
        # classifier with no shape at all and a capitalised machine name read as a value.
        split = _ALNUM_SPLIT.match(word.lower())
        if split:
            found.append(Mention(stem=stem_of(split.group(1)), **shape))
        previous = word.lower()
    return found


# The one English word that is capitalised wherever it stands, so its capital says nothing
# about whether it names anything. A corpus whose prose never uses the pronoun — most
# machine-generated documentation — made `I` an unknown term, and a capital `I` away from a
# sentence boundary then read as the name of a system the documentation had never heard of,
# which refused every "how do I …" question outright. The RCC corpus contains it, in FAQ
# headings like "I accidentally deleted a file", which is exactly why this never showed here.
ALWAYS_CAPITAL = frozenset({"i"})

# Words that discriminate nothing: a corpus not containing "how" says nothing about what the
# corpus covers. `links._STOPWORDS` exists for the same reason and on the same grounds; an
# unseen *stopword* has never been why a question was unanswerable — "how do I submit to the
# turbo partition" is unanswerable because of `turbo`, not because of `how`.
STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "so", "as", "at", "by",
    "for", "from", "in", "into", "of", "on", "onto", "to", "with", "without", "up",
    "down", "out", "over", "under", "about", "is", "are", "was", "were", "be", "been",
    "being", "am", "do", "does", "did", "doing", "done", "have", "has", "had", "having",
    "can", "could", "will", "would", "shall", "should", "may", "might", "must",
    "i", "me", "my", "mine", "we", "our", "ours", "you", "your", "yours", "it", "its",
    "this", "that", "these", "those", "there", "here", "what", "which", "who", "whom",
    "whose", "when", "where", "why", "how", "not", "no", "any", "some", "all", "each",
    "get", "got", "use", "using", "used", "make", "made", "want", "need", "please",
})


# Prepositions that introduce the thing a question is about: "submit a job **with
# qsub**", "load modules **on Perlmutter**". Deliberately short, and deliberately
# without "by": "my job was killed **by slurmstepd**" reports what happened rather than
# naming a topic, and slurmstepd is exactly the kind of word this must not flag.
NAMING_PREPOSITIONS = frozenset({"with", "using", "on", "to", "from", "for"})


# Words that mark a query as a *report* of something that happened rather than a
# question about a topic. Inside one, an unfamiliar word is almost always incidental —
# a daemon in a message, a username, an error token — and refusing over it is what made
# the first version of the weak-retrieval idea unusable.
#
# Outside one, an unfamiliar content word is what the question is *about*: "how do I
# submit to the turbo partition", "what is the penalty for sharing my password". The
# documentation not containing that word is then the answer, not a detail.
REPORTING_WORDS = frozenset({
    "error", "errors", "failed", "fail", "fails", "failure", "denied", "refused",
    "exceeded", "killed", "kill", "crashed", "cannot", "can't", "couldn't", "won't",
    "says", "said", "saying", "warning", "timeout", "timed", "stuck", "hangs", "hung",
    "rejected", "invalid", "unable", "aborted", "oom",
})


def reads_like_a_report(query: str) -> bool:
    """Is the reader describing something that happened, rather than asking about a topic?

    Deliberately a word list and not a parser. What it has to get right is the eight
    `[[identifier]]` cases in `evals/negatives.toml` — every one of them a real question
    the documentation answers, each carrying a word the corpus has never seen — without
    licensing "how do I submit to the turbo partition", where the unseen word *is* the
    question. A colon counts too: a pasted log line is the most common shape of all.
    """
    if ":" in query:
        return True
    words = {word.lower() for word in _MENTION.findall(query)}
    return bool(words & REPORTING_WORDS)


def names_a_thing(mention: Mention, *, versioned: bool) -> bool:
    """Does this unfamiliar word name something, rather than carry a value?

    Three signals, any of which is enough. None of them is clever, and that is the
    point — each one is checkable against the eight `[[identifier]]` cases in
    `evals/negatives.toml`, every one of which was refused by the first version of the
    weak-retrieval idea and must never be refused again.

    * `versioned` — the corpus knows the name and not this version of it: `midway4`,
      `bigmem3`, `scratch2`. A job number has no name part, so it cannot qualify.
    * capitalised away from a sentence boundary — `Frontera`, `ANSYS`, `Perlmutter`.
      The boundary condition is what keeps `… failed: Unspecified error` out, and the
      shouting condition is what keeps a whole query in caps out: there, capitalisation
      distinguishes nothing.
    * introduced by a naming preposition — `with qsub`, `on Perlmutter`.
    * inside a URL the reader pasted — every label of a hostname is a name, and the two
      signals above are both blind there: the labels are lower case and no preposition
      introduces them.
    """
    if versioned:
        return True
    if mention.in_address:
        return True
    if mention.word.lower() in ALWAYS_CAPITAL:
        return False
    if mention.capitalized and not (mention.after_boundary or mention.shouting):
        return True
    return mention.previous in NAMING_PREPOSITIONS


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
