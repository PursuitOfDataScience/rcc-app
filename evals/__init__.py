"""The evaluation sets, loaded from TOML.

Data lives in TOML rather than in a Python list because both `pytest` and the
command-line tools read it, and because a case is data: adding one should not mean
editing a module anybody imports. `tests/test_retrieval_eval.py` keeps its own
golden set in Python and `tools/metrics.py` reads it back with `ast` — that pairing
predates this package and is left exactly as it is. Nothing here duplicates it;
`tools/scorecard.py` calls that tool for the retrieval numbers.

Three loaders, one per shape:

    questions()   -> answerable, each with the page(s) that should be retrieved
    negatives()   -> unanswerable, each with the tokens that make it unanswerable
    identifiers() -> answerable, each carrying a word the corpus has never seen
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

QUESTIONS_FILE = os.path.join(HERE, "questions.toml")
NEGATIVES_FILE = os.path.join(HERE, "negatives.toml")
CONVERSATIONS_FILE = os.path.join(HERE, "conversations.toml")
INJECTIONS_FILE = os.path.join(HERE, "injections.toml")


@dataclass(frozen=True)
class Question:
    """An answerable question and what a right answer to it looks like.

    `known_gap` marks a case retrieval cannot reach today. Kept visible rather than
    deleted or relabelled, the way `KNOWN_GAPS` is in `tests/test_retrieval_eval.py`:
    it is reported on every run and left out of the ratchet, so the slack is stated
    instead of hidden and the day it starts passing is a day something improved.
    """

    text: str
    pages: tuple[str, ...] = ()
    must_mention: tuple[str, ...] = ()
    kind: str = "asked"
    known_gap: bool = False

    @property
    def id(self) -> str:
        return self.text


@dataclass(frozen=True)
class Negative:
    """A question the documentation cannot answer, and why.

    `absent` is the claim that makes the label true, and it is checkable: those words
    must appear nowhere in the corpus. `suspect` is set by the audit when one of them
    turns out to be in the documentation after all, and a suspect case is reported and
    excluded from scoring rather than deleted — see README.md.
    """

    text: str
    absent: tuple[str, ...] = ()
    why: str = ""
    kind: str = "out-of-domain"
    found: tuple[str, ...] = field(default=(), compare=False)

    @property
    def suspect(self) -> bool:
        return bool(self.found)

    @property
    def id(self) -> str:
        return self.text


@dataclass(frozen=True)
class Identifier:
    """Answerable, but carrying a word the corpus has never seen.

    The other side of the trap. Every one of these was refused by the first version of
    the weak-retrieval idea, which is what made it unusable; they are scored as
    over-refusals so a fix aimed at the leaks cannot bring that back.
    """

    text: str
    why: str = ""

    @property
    def id(self) -> str:
        return self.text


def _load(path: str) -> dict:
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def _tuple(value) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def questions(kind: str = "") -> list[Question]:
    """Every answerable case, or only those of one `kind` (`asked` / `faq`)."""
    found = [
        Question(
            text=str(row["text"]),
            pages=_tuple(row.get("pages")),
            must_mention=_tuple(row.get("must_mention")),
            kind=str(row.get("kind", "asked")),
            known_gap=bool(row.get("known_gap", False)),
        )
        for row in _load(QUESTIONS_FILE).get("question", [])
    ]
    return [case for case in found if not kind or case.kind == kind]


#: The class with no absent token to audit: every word is in the corpus and the fact
#: simply is not recorded. Labelled by judgement, kept in its own table so that is
#: visible, and scored alongside the rest — it is the quadrant the score floor exists
#: for, and the sweep looked like a free win until it was covered.
UNRECORDED = "unrecorded"


def negatives(kind: str = "") -> list[Negative]:
    """Every question the documentation cannot answer, both tables.

    `[[unrecorded]]` rows arrive with `absent=()`, which the audit passes over — there is
    nothing to check — and which `tests/test_eval_datasets.py` exempts from the
    names-what-makes-it-one rule by kind rather than by silence.
    """
    data = _load(NEGATIVES_FILE)
    found = [
        Negative(
            text=str(row["text"]),
            absent=_tuple(row.get("absent")),
            why=str(row.get("why", "")),
            kind=str(row.get("kind", "out-of-domain")),
        )
        for row in data.get("negative", [])
    ]
    found += [
        Negative(text=str(row["text"]), why=str(row.get("why", "")), kind=UNRECORDED)
        for row in data.get(UNRECORDED, [])
    ]
    return [case for case in found if not kind or case.kind == kind]


def identifiers() -> list[Identifier]:
    return [
        Identifier(text=str(row["text"]), why=str(row.get("why", "")))
        for row in _load(NEGATIVES_FILE).get("identifier", [])
    ]


@dataclass(frozen=True)
class Conversation:
    """Several turns in one session — the axis a single question cannot see."""

    name: str
    why: str
    turns: tuple[dict, ...]

    @property
    def id(self) -> str:
        return self.name


@dataclass(frozen=True)
class Injection:
    """An instruction hidden in an uploaded file, which the app promises to ignore.

    `canary` is a string with no reason to appear in an answer about documentation, so
    its presence is compliance rather than coincidence. `leaks` are phrases from the
    system prompt.
    """

    name: str
    filename: str
    content: str
    question: str
    canary: str
    leaks: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return self.name


def conversations() -> list[Conversation]:
    return [
        Conversation(
            name=str(row.get("name", "")),
            why=str(row.get("why", "")),
            turns=tuple(row.get("turn", [])),
        )
        for row in _load(CONVERSATIONS_FILE).get("conversation", [])
    ]


def injections() -> list[Injection]:
    return [
        Injection(
            name=str(row.get("name", "")),
            filename=str(row["filename"]),
            content=str(row["content"]),
            question=str(row["question"]),
            canary=str(row["canary"]),
            leaks=_tuple(row.get("leaks")),
        )
        for row in _load(INJECTIONS_FILE).get("injection", [])
    ]
