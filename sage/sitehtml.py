"""Turn a rendered blogdown/pandoc article into markdown the chunker understands.

The website's posts are `.Rmd` knitted to `.html`, and it is the HTML that Hugo
publishes, so the HTML is what a citation has to line up with. Pandoc wraps every
section as

    <div id="what-pretraining-entails" class="section level2"><h2>What …</h2>

and that `id` is the anchor a reader can actually scroll to. Converting to markdown
and re-slugifying the heading would produce an anchor that is *usually* the same and
occasionally not — a dead link nothing in this repo could detect. So the id is
carried through verbatim as `## Heading {#id}`, and `corpus.chunk_markdown` honours
it.

Standard library only, deliberately: this runs in CI and in `refresh-site.sh`, and
adding a parser dependency to a repo whose test job installs four packages is not
worth the twenty lines it would save.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

# Blocks whose content is never prose.
_DROP = {"script", "style", "noscript", "head"}
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_BLOCK_ENDS = {
    "p", "div", "section", "article", "ul", "ol", "table", "tr",
    "blockquote", "figure", "figcaption", "header", "footer",
}
_LANGUAGE = re.compile(r"\b(?:sourceCode\s+)?(r|python|bash|sh|sql|cpp|c|yaml|json)\b")


class _Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._drop_depth = 0
        self._heading: int | None = None
        self._heading_text: list[str] = []
        # Ids of enclosing `<div class="section …">`, innermost last. Pandoc puts
        # the anchor on the wrapper rather than on the <h2> itself.
        self._section_ids: list[str] = []
        self._div_stack: list[str | None] = []
        self._pre: str | None = None
        self._pre_text: list[str] = []
        self._list_stack: list[str] = []
        self._item_index: list[int] = []
        self._link: str | None = None
        self._link_text: list[str] = []
        self._in_code = False
        self._in_quote = 0
        self._in_cell = False

    # --- helpers ---

    def _emit(self, text: str) -> None:
        if self._heading is not None:
            self._heading_text.append(text)
        elif self._link is not None:
            self._link_text.append(text)
        else:
            self.out.append(text)

    def _newline(self, count: int = 1) -> None:
        if self._heading is not None or self._link is not None:
            return
        self.out.append("\n" * count)

    # --- tags ---

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in _DROP:
            self._drop_depth += 1
            return
        if self._drop_depth:
            return

        if tag == "div":
            classes = (attributes.get("class") or "").split()
            identifier = attributes.get("id")
            self._div_stack.append(identifier if "section" in classes else None)
            if "section" in classes and identifier:
                self._section_ids.append(identifier)
            return

        if tag in _HEADINGS:
            self._heading = _HEADINGS[tag]
            self._heading_text = []
            # A heading may carry its own id instead of relying on the wrapper.
            self._heading_id = attributes.get("id") or ""
            return

        if tag == "pre":
            classes = (attributes.get("class") or "").lower()
            found = _LANGUAGE.search(classes)
            self._pre = found.group(1) if found else ""
            self._pre_text = []
            return

        if tag == "code" and self._pre is None:
            self._in_code = True
            self._emit("`")
            return

        if tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "a":
            self._link = attributes.get("href") or ""
            self._link_text = []
        elif tag == "img":
            # The figures are the point of several of these posts, but a chat
            # answer cannot show one. The alt text is what is searchable.
            alt = (attributes.get("alt") or "").strip()
            if alt:
                self._emit(f"[figure: {alt}]")
        elif tag in ("ul", "ol"):
            self._list_stack.append(tag)
            self._item_index.append(0)
            self._newline()
        elif tag == "li":
            depth = max(len(self._list_stack) - 1, 0)
            indent = "  " * depth
            if self._list_stack and self._list_stack[-1] == "ol":
                self._item_index[-1] += 1
                self._emit(f"\n{indent}{self._item_index[-1]}. ")
            else:
                self._emit(f"\n{indent}- ")
        elif tag == "blockquote":
            self._in_quote += 1
            self._newline(2)
        elif tag in ("td", "th"):
            self._in_cell = True
            self._emit(" | ")
        elif tag == "br":
            self._newline()

    def handle_endtag(self, tag):
        if tag in _DROP:
            self._drop_depth = max(self._drop_depth - 1, 0)
            return
        if self._drop_depth:
            return

        if tag == "div":
            identifier = self._div_stack.pop() if self._div_stack else None
            if identifier and self._section_ids and self._section_ids[-1] == identifier:
                self._section_ids.pop()
            self._newline(2)
            return

        if tag in _HEADINGS and self._heading is not None:
            text = re.sub(r"\s+", " ", "".join(self._heading_text)).strip()
            anchor = self._heading_id or (
                self._section_ids[-1] if self._section_ids else ""
            )
            level = self._heading
            self._heading = None
            self._heading_id = ""
            if text:
                suffix = f" {{#{anchor}}}" if anchor else ""
                self.out.append(f"\n\n{'#' * level} {text}{suffix}\n\n")
            return

        if tag == "pre" and self._pre is not None:
            body = "".join(self._pre_text).strip("\n")
            language = self._pre
            self._pre = None
            self._pre_text = []
            if body.strip():
                self.out.append(f"\n\n```{language}\n{body}\n```\n\n")
            return

        if tag == "code" and self._in_code:
            self._in_code = False
            self._emit("`")
            return

        if tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "a" and self._link is not None:
            text = "".join(self._link_text).strip()
            href = self._link
            self._link = None
            if not text:
                return
            # An in-page anchor has nowhere to go once the text is in a chat
            # transcript, and a relative link would resolve against the wrong host.
            if href.startswith("#") or not href:
                self._emit(text)
            else:
                self._emit(f"[{text}]({href})")
        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
                self._item_index.pop()
            self._newline(2)
        elif tag == "blockquote":
            self._in_quote = max(self._in_quote - 1, 0)
            self._newline(2)
        elif tag in ("td", "th"):
            self._in_cell = False
        elif tag in _BLOCK_ENDS:
            self._newline(2)

    def handle_data(self, data):
        if self._drop_depth:
            return
        if self._pre is not None:
            self._pre_text.append(data)
            return
        if self._in_code or self._heading is not None or self._link is not None:
            self._emit(data)
            return
        text = re.sub(r"[ \t]*\n[ \t]*", " ", data)
        if not text.strip():
            # Collapse inter-tag whitespace to one space rather than dropping it,
            # or `<em>one</em> <em>two</em>` becomes "onetwo".
            if self.out and not self.out[-1].endswith((" ", "\n")):
                self.out.append(" ")
            return
        self._emit(text)

    def result(self) -> str:
        text = "".join(self.out)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r" +\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        # A quote marker per line, applied last so nesting does not have to be
        # tracked through every emit.
        return text.strip()


_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
# Both quote styles appear across five years of posts, and a `date: '2021-08-15'`
# read with only the double-quote form stripped keeps its apostrophes and sorts
# apart from every other date.
_FIELD = re.compile(r"""^(\w+):[ \t]*(.*?)[ \t]*$""", re.MULTILINE)
_QUOTED = re.compile(r"""\A(["'])(.*)\1\Z""", re.DOTALL)


def split_front_matter(raw: str) -> tuple[dict[str, str], str]:
    """Pull the YAML block blogdown leaves at the top of the rendered HTML."""
    match = _FRONT_MATTER.match(raw)
    if not match:
        return {}, raw
    fields = {}
    for key, value in _FIELD.findall(match.group(1)):
        quoted = _QUOTED.match(value.strip())
        cleaned = (quoted.group(2) if quoted else value).strip()
        if cleaned:
            fields[key.lower()] = cleaned
    return fields, raw[match.end():]


def to_markdown(html: str) -> str:
    """Rendered article HTML to markdown, keeping pandoc's heading anchors."""
    converter = _Converter()
    converter.feed(html)
    converter.close()
    return converter.result()


def convert(raw: str) -> tuple[dict[str, str], str]:
    """`(front matter, markdown)` for one rendered post."""
    fields, body = split_front_matter(raw)
    return fields, to_markdown(body)
