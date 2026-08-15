"""What every retrieval engine has to return, and how one is chosen.

The interface is deliberately three things — search, assess, and the corpus it is
over — because that is all the rest of the app uses. An engine that scores with
embeddings, or calls out to a vector database, or asks a reranker to reorder BM25's
output, is a class with those three members and a `register` call; nothing in the
tool loop, the citation layer or the UI has to learn that it exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..corpus import Chunk, Corpus
from ..registry import Registry

# name -> (corpus, profile.Retrieval) -> Retriever
engines: Registry = Registry("retrieval engine")


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


@dataclass
class Assessment:
    """Whether a query looks answerable, from properties of *this* retrieval.

    Deliberately not a percentage. Scores are unnormalised sums of weighted
    contributions; they are not comparable across queries, and turning one into "87%
    confident" would be theatre. Everything here is a checkable fact instead: how well
    the top hit scored, how far ahead of the runner-up it is, and which query words
    appear nowhere in the corpus.

    `unknown_terms` holds the words as the reader typed them, not the stems they were
    matched on. Quoting stems put "No section contains: prostat, unspecifi, instal" in
    front of a model and asked it to relay that to a person.

    `documentation` is how the caveat names the corpus — "the RCC documentation" for
    this deployment, "the documentation" for one that has not said. It arrives with
    the assessment because the sentence is addressed to the model, and a model told
    that "the documentation" does not cover something will repeat that phrase to a
    reader who is looking at a page with a name.
    """

    top_score: float = 0.0
    margin: float = 0.0
    unknown_terms: tuple[str, ...] = ()
    #: The subset of `unknown_terms` that names a *thing* rather than carrying a value:
    #: another site's cluster, a scheduler this centre does not run, a package that is
    #: not installed. Separate because evidence cannot outweigh one — see `confident`.
    named_topics: tuple[str, ...] = ()
    #: Whether the query reads as a report of something that happened — an error, a
    #: killed job, a pasted log line — rather than a question about a topic. That is
    #: what decides whether an unfamiliar word is incidental (a daemon, a username, an
    #: error token) or is the subject of the question.
    reporting: bool = False
    documentation: str = "the documentation"
    #: Thresholds are carried rather than read from a module, so an engine that scores
    #: on a different scale can supply its own without redefining the constants.
    min_confident_score: float = 0.0
    strong_score: float = 0.0

    @property
    def strong(self) -> bool:
        """Enough evidence that an unrecognised word does not overturn it.

        A question can be perfectly answerable and still contain a word the docs have
        never seen — a job ID, a CNetID, the name of a daemon in an error message. That
        is the common case, not the exception, and treating any unknown word as
        disqualifying is what made this idea unusable the first time round.
        """
        return self.top_score >= self.strong_score

    @property
    def confident(self) -> bool:
        if self.top_score < self.min_confident_score:
            return False
        if self.named_topics:
            # The one thing `strong` must not walk past. "How do I submit a job on
            # Frontera" scores 42 — every word except the machine's name matches
            # `sbatch.md` richly — and no amount of that makes this documentation cover
            # another site's cluster. Measured over 38 labelled unanswerable questions,
            # the score alone caveated 14; this raises it without touching a threshold,
            # which `tools/gate_check.py --sweep` showed could not work: the two sides
            # occupy the same score range.
            return False
        if not self.unknown_terms:
            return True
        # Evidence outweighs an unfamiliar word only where the word is plausibly
        # incidental. "My job was killed by slurmstepd" is a documented question with a
        # daemon's name in it; "how do I submit to the turbo partition" is a question
        # about a partition that does not exist, and it scores just as well because
        # every other word is ordinary Slurm vocabulary.
        return self.strong and self.reporting

    def caveat(self) -> str:
        """One honest sentence for the model, empty when retrieval looks sound."""
        if self.confident:
            return ""
        if self.unknown_terms:
            missing = ", ".join(sorted(self.unknown_terms))
            return (
                f"No section of {self.documentation} mentions: {missing}. The results "
                "below matched the other words only, so they are probably not about "
                "what was asked. Say the documentation does not appear to cover it "
                "rather than answering from these."
            )
        return (
            "These are weak matches and may not answer the question. If they do not, "
            "say the documentation does not appear to cover it."
        )


class Retriever(Protocol):
    """The three things the rest of the app asks of retrieval."""

    corpus: Corpus

    def search(self, query: str, limit: int | None = None) -> list[Result]: ...

    def assess(
        self, query: str, results: list[Result] | None = None
    ) -> Assessment: ...
