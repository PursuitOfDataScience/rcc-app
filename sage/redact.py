"""Names from the machinery, taken out of an answer before the reader gets it.

`prompts.SELF_DISCLOSURE` asks the model not to name the tools it calls. Asking is not
enough, and the number is on the card: over the sixteen probes in `evals/meta.toml` the
default free model named them in eight answers with no rule in the prompt and in four with
one. A rule is a request, and the tool names are in every request as schemas — the
provider API has nowhere else to put them — so no wording can make them unquotable.

So this is the half that does not depend on the model. It swaps each tool's internal name
for the reader-facing one the tool carries:

    I run a `search_docs` query, then read the section with `read_doc`.
    I run a `search` query, then read the section with `read`.

A swap rather than a deletion, because deleting leaves "* **** – finds relevant sections"
where an answer had a bulleted list of tool names, and a broken sentence is worse than the
name was. What is left is true, is what the app actually does, and is what the welcome
line under the title has always said.

Two things it deliberately is not:

* **Not a security boundary.** A model determined to describe its own architecture in
  prose still can, and `evals/checks.narrated_machinery` is what measures that. This
  removes identifiers — the strings a reader cannot use, cannot check, and was never
  offered.
* **Not silent.** `turn.run` logs every name it removes and stores the list on the turn,
  so `tools/agent_bench.py` still scores the model on what it *tried* to say. A fix that
  blinded the instrument measuring it would be the worst of the available outcomes.

Measured on the 173 recorded answers in `report/transcripts.jsonl`: zero substitutions.
Nothing about an ordinary documentation answer goes near this.
"""

from __future__ import annotations

import re
from collections.abc import Mapping


def pattern(names) -> re.Pattern | None:
    """One case-insensitive alternation over `names`, longest first, or None if empty.

    Longest first because `re` takes the first alternative that matches at a position,
    and a name that is another name's prefix would otherwise never be seen whole.
    Bounded by `(?<![\\w-])…\\b` rather than `\\b…\\b`: a leading `\\b` would match inside
    `my-search_docs`, and the identifiers being looked for are whole words in prose —
    inside backticks, inside `**bold**`, or bare, all of which leave the surrounding
    punctuation untouched by a substitution.
    """
    kept = sorted((name for name in names if name), key=len, reverse=True)
    if not kept:
        return None
    return re.compile(
        r"(?<![\w-])(?:" + "|".join(re.escape(name) for name in kept) + r")\b",
        re.IGNORECASE,
    )


def apply(text: str, names: Mapping[str, str]) -> tuple[str, list[str]]:
    """The text with each internal name replaced by its public one, and which ones went.

    `names` maps internal name to reader-facing name — `sage.tools.Toolset.public_names`
    for this app. A name with no public form is left alone rather than deleted, because
    the caller has then said "keep this out of answers" without saying what to put in its
    place, and guessing is how a sentence gets broken.
    """
    found = pattern(names)
    if not found or not text:
        return text, []
    removed: list[str] = []

    def swap(match: re.Match) -> str:
        original = match.group(0)
        public = names.get(original) or names.get(original.lower()) or ""
        if not public:
            return original
        removed.append(original)
        return public

    return found.sub(swap, text), removed
