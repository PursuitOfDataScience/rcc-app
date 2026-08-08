"""The citations a model emits: point them at real URLs, drop the duplicate list.

The previous version sent *every* `web/` citation to the user-guide root on the
stated grounds that "website pages have no stable per-page docs URL". They do —
each scraped file records it on line 1 — and they span five different hosts, so a
Skyway or Beagle3 answer was being cited to the Midway user guide.
"""

from __future__ import annotations

import re

from .corpus import Corpus, docs_url

_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_ATTR_LIST = re.compile(r"\{:[^}]*\}")
_EXTERNAL = ("http://", "https://", "mailto:", "tel:", "#")


def resolve(target: str, corpus: Corpus) -> str | None:
    """Best URL for an internal doc reference, or None if it cannot be resolved."""
    target = target.strip()
    if not target:
        return None

    chunk = corpus.chunk(target)
    if chunk is not None:
        return chunk.url

    base, _, anchor = target.partition("#")
    base = base.strip().lstrip("./")

    document = corpus.document(base)
    if document is None:
        for source in ("docs", "web"):
            document = corpus.document(f"{source}/{base}")
            if document is not None:
                break

    if document is None:
        # A bare or relative filename: match on path suffix.
        candidates = [
            item
            for item in corpus.documents.values()
            if item.path == base or item.path.endswith(f"/{base}")
        ]
        document = candidates[0] if len(candidates) == 1 else None

    if document is None:
        return None
    if document.source == "web":
        return document.url
    return docs_url(document.path, anchor)


def unresolved(text: str, corpus: Corpus) -> list[str]:
    """Internal link targets in `text` that resolve to nothing.

    Worth counting rather than only hiding: a model inventing a path is a generation
    defect, and a turn that produces one should be visible in the log rather than
    silently tidied away by the renderer.
    """
    missing = []
    for match in _MARKDOWN_LINK.finditer(_ATTR_LIST.sub("", text)):
        target = match.group(2)
        if target.startswith(_EXTERNAL):
            continue
        if resolve(target, corpus) is None:
            missing.append(target)
    return missing


def fix_links(text: str, corpus: Corpus) -> str:
    """Point internal links at published URLs; unlink what cannot be resolved.

    That second clause is what this docstring promised while the code did the
    opposite: an unresolvable target became a live link to `DOCS_BASE_URL`, so a
    reader clicking a citation landed on the front page of the user guide believing
    they had reached the cited section. A confident wrong citation is worse than no
    citation — it spends the trust the Sources strip exists to earn, and nothing about
    it looks different from a citation that works.

    The label now survives as plain text: a section named but not linked, which is
    honest about exactly what happened.
    """
    text = _ATTR_LIST.sub("", text)

    def replace(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        if target.startswith(_EXTERNAL):
            # A bare in-page anchor has nowhere to go in a chat transcript.
            return label if target.startswith("#") else match.group(0)
        url = resolve(target, corpus)
        return f"[{label}]({url})" if url else label

    return _MARKDOWN_LINK.sub(replace, text)


# `Sources:`, `**References:**`, `**Citations**:`, `## Sources` — every decoration a
# model puts round the word, matched by treating `*_#` and space as noise either side
# of it. Both spellings of the bold form turn up, which is why the colon is allowed to
# fall on either side of the markup rather than in one fixed place.
_LABEL = r"(?:sources?|references?|citations?)"
_MARKUP = r"[*_#\s]*"
_LABEL_LINE = re.compile(
    rf"^\s{{0,3}}{_MARKUP}{_LABEL}{_MARKUP}(?P<colon>:?){_MARKUP}(?P<rest>.*)$",
    re.IGNORECASE,
)
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_FENCE = re.compile(r"^\s*(?:`{3,}|~{3,})")
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")

# Links and nothing else: no words outside the brackets, separators only between them.
# This is the shape a model falls back on when told not to write the word "Sources" —
# it drops the label and leaves the list. Prose that happens to contain a link ("see
# [Batch jobs](docs/slurm/sbatch.md) for flags") has words outside the brackets and
# does not match, which is the whole distinction.
_LINK_PART = r"\[[^\]]+\]\(\s*[^)\s]+(?:\s+\"[^\"]*\")?\s*\)"
_ONLY_LINKS = re.compile(
    rf"^\s*(?:[-*+]\s+|\d+[.)]\s+)?{_LINK_PART}(?:[\s,;·|]*{_LINK_PART})*[\s,;.·]*$"
)


def _footer_label(line: str) -> str | None:
    """The text after a `Sources:`-style label, `None` if this is not such a line.

    A payload without a colon is prose — "Sources of variation include …" opens with
    the word and is a sentence, not a footer — so the colon is what licenses cutting
    anything that sits on the same line.
    """
    match = _LABEL_LINE.match(line)
    if not match:
        return None
    rest = match.group("rest").strip()
    if rest and not match.group("colon"):
        return None
    return rest


def _is_citation_line(line: str) -> bool:
    """A line that could only be part of a citation list, never of an answer.

    Deliberately narrow. `- Run \\`sbatch job.sh\\`` is a step, not a citation, so a
    code span disqualifies a line; so does the length of a real paragraph. What is
    left is bullets of titles and bare links, which is what the footer is made of.
    """
    if _FENCE.match(line) or "`" in line:
        return False
    stripped = line.strip()
    if stripped.startswith("#"):
        return False
    if _ONLY_LINKS.match(line) or _LIST_ITEM.match(line):
        return True
    return len(stripped) <= 120


def _pages(line: str, corpus: Corpus) -> set[str] | None:
    """The published pages every link on this line points at, or None if any is a
    reference this repository cannot resolve — in which case it is not provably a
    duplicate of anything and must be left where it is.

    Compared at page granularity, not per anchor: a strip chip linking
    `…/faq/#how-do-i-review` already gives the reader that page, whatever section of
    it the model chose to point at.
    """
    found = _MARKDOWN_LINK.findall(line)
    if not found:
        return None
    pages = set()
    for _label, target in found:
        if target.startswith(_EXTERNAL):
            return None
        url = resolve(target, corpus)
        if not url:
            return None
        pages.add(url.split("#", 1)[0])
    return pages


def strip_source_footer(
    text: str, corpus: Corpus | None = None, sources: list[dict] | None = None
) -> str:
    """Remove a trailing citation list the model wrote for itself.

    Every answer already gets a Sources strip built from the chunks that were
    actually retrieved, so a model that also signs off with `Sources: A, B` prints
    the same citations twice, three lines apart. The system prompt asks for inline
    links and no footer; across nine models that holds on most turns and not all of
    them, so the footer comes off here too.

    Two shapes, deliberately judged by different evidence:

    * **Labelled** — `Sources:`, `**References:**`, `## Citations`. The label is the
      model declaring what the block is, so the shape is evidence enough.
    * **Unlabelled** — a bare paragraph of nothing but links. This is what asking for
      no "Sources" list actually produced: the label went and the links stayed, which
      is the same duplication with no word to match on. Shape alone is too thin here —
      an answer could legitimately end on a list of links — so this one comes off only
      when `sources` proves every link is a page the strip below already shows.

    Passing no `corpus`/`sources` leaves the unlabelled shape alone, since nothing can
    be proven about it. Passing an empty `sources` list means the app is drawing no
    strip at all, and then the footer is the only citation there is and stays put.
    """
    if not text or not text.strip():
        return text
    if sources is not None and not sources:
        return text

    lines = text.splitlines()
    last = len(lines) - 1
    while last >= 0 and not lines[last].strip():
        last -= 1

    cut = None
    if _footer_label(lines[last]):
        # The whole list sits on the label's own line: that one line is the footer.
        cut = last
    else:
        # Otherwise the list is underneath a label of its own. Only the last such
        # label is considered — scanning further back to find a block that happens
        # to look like citations is how a strip like this eats half an answer.
        for idx in range(last, -1, -1):
            if _footer_label(lines[idx]) is None:
                continue
            if all(_is_citation_line(line) for line in lines[idx + 1 : last + 1]):
                cut = idx
            break

    if cut is None and corpus is not None and sources:
        shown = {
            str(item.get("url", "")).split("#", 1)[0]
            for item in sources
            if item.get("url")
        }

        def duplicate(line: str) -> bool:
            """Nothing but links, all of them pages the strip is already showing."""
            if not _ONLY_LINKS.match(line):
                return False
            pages = _pages(line, corpus)
            return bool(pages) and pages <= shown

        # The whole run, not just the last line of it. Taking one line off the end of
        # a bulleted list leaves a half-eaten list, which is worse than the duplicate.
        begin = last + 1
        while begin - 1 >= 0 and duplicate(lines[begin - 1]):
            begin -= 1
        if begin <= last and begin > 0:
            # Unless a sentence introduces it. "Here is what the docs cover:" followed
            # by links is an answer *made* of links, and cutting them leaves the colon
            # pointing at nothing; a footer is never introduced, it is just appended.
            above = next(
                (line for line in reversed(lines[:begin]) if line.strip()), ""
            )
            if not above.rstrip().endswith(":"):
                cut = begin

    if cut is None:
        return text

    kept = lines[:cut] + lines[last + 1 :]
    # Models fence the footer off with a rule; without the footer it leads nowhere.
    while kept and (not kept[-1].strip() or _RULE.match(kept[-1])):
        kept.pop()
    # An answer that was *only* a footer is a failure of the model, not something to
    # blank out: a duplicate Sources strip beats an empty bubble.
    if not any(line.strip() for line in kept):
        return text
    return "\n".join(kept)
