"""Turn source documents into clean text a model can read.

The corpus is written for mkdocs-material, so it is full of syntax that means
nothing outside that renderer. Left in place it actively degrades answers — the
worst offender being content tabs, which collapse cluster-specific command
variants into one undifferentiated blob:

    === "Midway2"
        sacctmgr list assoc account=$ACCOUNT ...
    ===+ "Midway3, Midway-AMD, MidwaySSD, Beagle3"
        scontrol show partition | grep ...

Read raw, nothing tells the model which command belongs to which cluster. Here
each tab becomes a labelled block, so the distinction survives.

Everything inside fenced code blocks is passed through untouched.
"""

from __future__ import annotations

import re

# kramdown attribute lists: {:target='_blank'}, {: class="responsive-img"}
_ATTR_LIST = re.compile(r"\{:[^}]*\}")

# Real HTML tags only — deliberately not `<[^>]+>`, which eats prose like "a < b".
_HTML_TAG = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^<>]*?)?/?>")
_IMG_TAG = re.compile(r"<img\b[^>]*?>", re.IGNORECASE)
_ALT_ATTR = re.compile(r"""\balt\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

# `!!! note "Title"`, `!!! Note: ...`, `??? tip`, `???+ example`
_ADMONITION = re.compile(r"^(?P<indent>[ \t]*)(?:!!!|\?\?\?)\+?[ \t]*(?P<rest>.*)$")

# `=== "Midway2"` / `===+ "Midway3"`. The trailing `\s+\S` guard means a setext
# heading underline (`=====`) is not mistaken for a tab.
_CONTENT_TAB = re.compile(r"^(?P<indent>[ \t]*)===\+?[ \t]+(?P<label>\S.*)$")

_FENCE = re.compile(r"^[ \t]*(?P<ticks>`{3,}|~{3,})")

_SCRAPE_RULE = re.compile(r"^=+$")


def _is_fence(line: str) -> str | None:
    match = _FENCE.match(line)
    return match.group("ticks")[0] if match else None


_TYPED_TITLE = re.compile(r"""^[A-Za-z]+\s+(["'])(?P<title>.*)\1\s*$""")


def _clean_label(raw: str) -> str:
    """Reduce an admonition or tab marker to the title a reader would see.

    mkdocs renders only the quoted title, so `tip "Advanced tip"` is `Advanced tip`.
    The corpus also contains loose forms (`Note: ...`, bare `Notes`) that mkdocs
    would reject; those are passed through rather than dropped.
    """
    label = raw.strip()

    typed = _TYPED_TITLE.match(label)
    if typed:
        title = typed.group("title").strip()
        if title:
            return title

    if len(label) >= 2 and label[0] == label[-1] and label[0] in "\"'":
        label = label[1:-1].strip()

    label = label.rstrip(":").strip()
    # Bare type words ("warning", "note") read better capitalised.
    if label.isalpha() and label.islower():
        return label.capitalize()
    return label


def _replace_img(match: re.Match[str]) -> str:
    alt = _ALT_ATTR.search(match.group(0))
    text = ""
    if alt:
        text = (alt.group(1) or alt.group(2) or "").strip()
    return f"[figure: {text}]" if text else "[figure]"


def _clean_prose(line: str) -> str:
    line = _ATTR_LIST.sub("", line)
    line = _IMG_TAG.sub(_replace_img, line)
    line = _HTML_TAG.sub("", line)
    return line.rstrip()


def _block_extent(lines: list[str], start: int, indent: int) -> int:
    """Index one past the last line belonging to an indented block opened at `start`."""
    end = start
    for idx in range(start, len(lines)):
        line = lines[idx]
        if not line.strip():
            end = idx + 1
            continue
        if len(line) - len(line.lstrip()) > indent:
            end = idx + 1
            continue
        break
    return end


def _dedent(block: list[str]) -> list[str]:
    widths = [
        len(line) - len(line.lstrip()) for line in block if line.strip()
    ]
    if not widths:
        return block
    trim = min(widths)
    return [line[trim:] if line.strip() else "" for line in block]


def normalize_markdown(text: str) -> str:
    """Flatten mkdocs-material syntax into plain markdown."""
    text = _HTML_COMMENT.sub("", text)
    lines = text.splitlines()
    out: list[str] = []
    idx = 0
    fence: str | None = None

    while idx < len(lines):
        line = lines[idx]

        if fence:
            out.append(line)
            if _is_fence(line) == fence:
                fence = None
            idx += 1
            continue

        opened = _is_fence(line)
        if opened:
            fence = opened
            out.append(line)
            idx += 1
            continue

        tab = _CONTENT_TAB.match(line)
        admonition = _ADMONITION.match(line) if not tab else None

        if tab or admonition:
            match = tab or admonition
            indent = len(match.group("indent").expandtabs(4))
            if tab:
                label = _clean_label(match.group("label"))
            else:
                label = _clean_label(match.group("rest")) or "Note"
            end = _block_extent(lines, idx + 1, indent)
            body = _dedent(lines[idx + 1 : end])

            if out and out[-1].strip():
                out.append("")
            out.append(f"**{label}**")
            out.append("")
            # Recurse: tabs nest inside admonitions in a few pages.
            nested = normalize_markdown("\n".join(body))
            out.extend(nested.splitlines())
            out.append("")
            idx = end
            continue

        out.append(_clean_prose(line))
        idx += 1

    return collapse_blank_lines("\n".join(out))


def collapse_blank_lines(text: str) -> str:
    """At most one blank line in a row, no leading/trailing blank lines."""
    lines = [line.rstrip() for line in text.splitlines()]
    result: list[str] = []
    for line in lines:
        if not line and (not result or not result[-1]):
            continue
        result.append(line)
    while result and not result[-1]:
        result.pop()
    return "\n".join(result)


def parse_scraped(text: str) -> tuple[str, str, str]:
    """Split a scraped `web/*.txt` page into (url, title, body).

    Every scraped file carries its real source URL on line 1, which is what makes
    per-page citations possible:

        URL: https://cloud-skyway.rcc.uchicago.edu/faqs
        Title: FAQs | Skyway - RCC Cloud Solution
        ================================================================
    """
    url = ""
    title = ""
    lines = text.splitlines()
    cursor = 0

    for idx, line in enumerate(lines[:6]):
        stripped = line.strip()
        if stripped.startswith("URL:"):
            claimed = stripped[4:].strip()
            # Only a web address, because this string becomes the `href` of every
            # citation to the page. Whatever followed `URL:` was taken verbatim, so a
            # scrape that wrote a relative path, or nothing useful, produced citations
            # pointing somewhere that is not a page — and `javascript:` would have gone
            # into a markdown link in an answer. Anything else is treated as absent,
            # which falls back to the source's `base_url`: a link to the site root is a
            # worse citation than a deep one and a better one than a broken href.
            #
            # All 55 bundled scrapes carry an `https://` URL, so nothing here changes
            # today; this is about the day the scraper's output shifts.
            url = claimed if claimed.startswith(("http://", "https://")) else ""
            cursor = idx + 1
        elif stripped.startswith("Title:"):
            # Drop the site suffix: "FAQs | Skyway - RCC Cloud Solution".
            title = stripped[6:].strip().split("|")[0].strip()
            cursor = idx + 1
        elif _SCRAPE_RULE.match(stripped) and len(stripped) > 8:
            cursor = idx + 1
            break

    body = "\n".join(lines[cursor:])
    return url, title, collapse_blank_lines(body)


_INLINE_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# A markdown backslash escape, which is a backslash and one ASCII punctuation mark.
# Restricted to punctuation on purpose: `\.` is an escape and mkdocs renders a bare
# `.`, while `\n` in a heading about escape sequences is two literal characters.
_ESCAPE = re.compile(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])")


# An answer that opens by announcing its own deliberation. Anchored to the start and kept
# to markers whose only job is that announcement, because the cost of a false positive is a
# good answer replaced by an error card.
#
# Measured over 554 recorded answers: one match. That one was 34,645 characters — eight
# times the next-longest answer in the set — of a model reasoning about its own
# instructions, quoting them line by line, running into the token ceiling mid-sentence
# without ever answering, and shipping under a Sources strip of six real sections. No
# recorded answer contains a `<think>` tag, so the tag form is here for the shape rather
# than from evidence.
_DELIBERATION = re.compile(
    r"(?i)^\s*(?:<think>"
    r"|(?:here(?:'s| is)|this is) (?:a|my) thinking process"
    r"|thinking process\s*:"
    r"|chain[- ]of[- ]thought"
    r"|let me (?:think|reason)(?: this| it)? through)"
)


def opens_with_deliberation(text: str) -> bool:
    """Is this text a model thinking out loud rather than answering?

    Used twice and defined once: `ui.turn` will not ship one to a reader, and
    `evals.checks` counts it — two copies of this pattern would drift the day one is
    widened.
    """
    return bool(_DELIBERATION.match(text or ""))


# A model handed no tools that writes the call out as prose anyway. Every marker here is
# an envelope a provider strips when it parses a real tool call — so text still carrying
# one is text the provider did *not* read as a call, which is exactly the case where it
# reaches a reader as the answer.
#
# Anchored to the start, like `_DELIBERATION` above and for the same reason: an answer that
# *mentions* a function, or fences a `bash` block, must not be mistaken for one that is
# nothing but a call. Nothing legitimate opens with these.
#
# Observed, not guessed. Withdrawing the tools for the last request of a turn — see
# `ui.turn` — took one free model from the round-limit sentence to a full cited answer and
# the other to this, verbatim and complete:
#
#     <tool_call>
#     <function=search>
#     <parameter=query>
#     add member to pi account collaborator RCC account
#     </parameter>
#     </function>
#     </tool_call>
#
# 136 characters of XML, under a Sources strip of two real sections. The `[TOOL_CALLS]`,
# `<|...|>` and bare-JSON forms are the other envelopes on this lineup; `grounded()` has
# always been able to produce all of them, and its docstring counted eight in fourteen
# turns naming a tool with three of them nothing but the call.
_WRITTEN_OUT_CALL = re.compile(
    r"(?i)^\s*(?:</?tool[_▁ ]?calls?>"
    r"|\[/?tool_calls?\]"
    r"|<\|?/?(?:tool_call|tool_calls|python_tag|function_call)\|?>"
    r"|</?function(?:[ =_]|>)"
    r"|\{\s*\"(?:name|function|tool_name|recipient_name)\"\s*:)"
)


def is_written_out_tool_call(text: str) -> bool:
    """Is this text a tool call the model typed instead of made?

    Sibling of `opens_with_deliberation`, and it goes the same two places: `ui.turn`
    raises rather than shipping one, and `evals.checks` counts it. Both outcomes are the
    model saying what it was about to do instead of doing it, so both take the route to
    the error card, which offers Try again and another model — recoverable, in a way that
    a screenful of angle brackets presented as an answer is not.
    """
    return bool(_WRITTEN_OUT_CALL.match(text or ""))


def plain_heading(text: str) -> str:
    r"""Heading text as a reader sees it: links unwrapped, emphasis dropped.

    Backticks and asterisks are markdown. An underscore in this corpus is almost
    never emphasis — it is inside an identifier, and deleting it turned
    `EVP_KDF_ctrl` into `EVPKDFctrl` and `<job_id>` into `<jobid>` in the citation
    the reader sees, on precisely the FAQ headings people find by pasting an error
    message.

    A backslash escape is markdown too, and this used to keep it. `## 1\. Formatting
    Data` escapes the period so mkdocs does not read the line as an ordered list; the
    page shows `1.` and the citation strip showed `1\.` — on every heading of the
    geocoding tutorial, which numbers all four. `slugify` is built on this function and
    is unaffected: it strips the backslash anyway as punctuation.
    """
    cleaned = _INLINE_LINK.sub(r"\1", text.strip())
    cleaned = re.sub(r"[`*]+", "", cleaned)
    cleaned = _ESCAPE.sub(r"\1", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def slugify(text: str) -> str:
    """Heading anchor matching mkdocs-material, so citations can deep-link.

    mkdocs slugifies *rendered* text, so `[GM4](https://gm4...)` becomes `gm4` —
    unwrapping the link first is what keeps generated anchors valid.

    Underscores survive as themselves. mkdocs' slugify replaces whitespace and its
    separator, and `_` is neither — it is a `\\w` character, so the published id for
    `EVP_KDF_ctrl` is `evp_kdf_ctrl`. Mapping it to `-` here is the same lost anchor
    as deleting it, one character further on.
    """
    slug = plain_heading(text).lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def pretty_title(rel_path: str) -> str:
    """Readable title from a path, for documents with no usable heading.

    An index page is named after the directory it indexes, which is the same mapping
    the mkdocs URL scheme makes when it publishes `software/index.md` at `software/`. "Index"
    names no page a reader could place in a citation, and that is what the software
    index would otherwise be called now that a page with no H1 falls back to here.
    """
    slug = re.sub(r"\.(md|txt)$", "", rel_path, flags=re.IGNORECASE).strip("/")
    if "/" in slug and slug.rsplit("/", 1)[-1].lower() == "index":
        slug = slug.rsplit("/", 1)[0]
    name = slug.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").strip()
    return name[:1].upper() + name[1:] if name else rel_path
