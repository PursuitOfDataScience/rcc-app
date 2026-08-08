#!/usr/bin/env python3
"""Sync the personal website into `site/`, the corpus for `SAGE_PROFILE=site`.

Reads a checkout of the Hugo/blogdown site, converts each rendered article to
markdown, and writes it with the permalink Hugo actually publishes in a short
header. The result is what `sage.corpus.chunk_post` reads, and it is committed to
this repo for the same reason `docs/` and `web/` are: the Streamlit deployment has
no checkout of the website to read from.

    python tools/build_site_corpus.py --site ../personal-website

Permalinks
----------
The slug rule below (Hugo's `MakePathSanitized`: lowercase, spaces to hyphens,
keep the RFC3986 unreserved marks `. _ ~ -`) is **verified against the site's own
`public/sitemap.xml`** on every run rather than trusted. It reproduced all 110
sitemap entries when this was written, and the first version — which stripped dots
— silently produced `2021-09-27-us-prison-analysis` for a page published at
`2021-09-27-u.s.-prison-analysis`. A dead citation is the one failure this corpus
cannot afford, so a mismatch is reported loudly and `--strict` makes it fatal.

Posts newer than the committed `public/` build are absent from the sitemap and are
reported as unverified rather than skipped; that is the normal state right after
writing an article.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sage import sitehtml  # noqa: E402

DEFAULT_SITE = os.getenv("SAGE_WEBSITE_REPO", "../personal-website")
DEFAULT_OUT = "site"
# Hand-written ground truth, kept in this repo so the website build is untouched.
DEFAULT_NOTES = "site_notes"
# Only used to report a mismatch; the real base URL comes from the sitemap.
FALLBACK_BASE = "https://youzhi.netlify.app"

_UNSAFE = re.compile(r"[^a-z0-9\s._~-]")
_SPACES = re.compile(r"\s+")
_DASHES = re.compile(r"-{2,}")


def urlize(text: str) -> str:
    """Hugo's path sanitiser, as far as this site exercises it."""
    ascii_text = (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    )
    slug = _UNSAFE.sub("", ascii_text.lower())
    slug = _SPACES.sub("-", slug.strip())
    return _DASHES.sub("-", slug).strip("-")


def sitemap_urls(site: Path) -> tuple[set[str], str]:
    """Every published URL, and the base URL they share."""
    path = site / "public" / "sitemap.xml"
    if not path.exists():
        return set(), FALLBACK_BASE
    found = set(re.findall(r"<loc>([^<]+)</loc>", path.read_text(encoding="utf-8")))
    base = FALLBACK_BASE
    for url in found:
        match = re.match(r"(https?://[^/]+)", url)
        if match:
            base = match.group(1)
            break
    return found, base


@dataclass
class Page:
    source: str  # "post" | "page"
    rel_path: str  # written under site/<source>/
    url: str
    title: str
    date: str
    body: str
    verified: bool


def _front_matter(html_path: Path) -> dict[str, str]:
    """Front matter from the rendered file, falling back to the `.Rmd` beside it.

    Two of the 116 articles were knitted without their YAML block, and a post with
    no title is filed under whatever its first heading happens to be — which for
    one of them is the author's name.
    """
    fields, _ = sitehtml.split_front_matter(html_path.read_text(encoding="utf-8"))
    if fields.get("title"):
        return fields
    source = html_path.with_suffix(".Rmd")
    if source.exists():
        from_rmd, _ = sitehtml.split_front_matter(
            source.read_text(encoding="utf-8", errors="replace")
        )
        return {**from_rmd, **fields}
    return fields


_HEADING_LINE = re.compile(r"^#{1,6}\s+(.*?)(?:\s*\{#[^}]*\})?\s*$")


def strip_byline_headings(body: str, author: str, date: str) -> str:
    """Drop the `#### Y. Yu` / `#### 2021-08-13` block some articles render.

    They are a title block, not sections, and indexing them means "who wrote
    this?" retrieves a heading with no content under it.
    """
    unwanted = {value.strip().lower() for value in (author, date) if value.strip()}
    if not unwanted:
        return body
    kept = []
    for line in body.splitlines():
        match = _HEADING_LINE.match(line)
        if match and match.group(1).strip().lower() in unwanted:
            continue
        kept.append(line)
    return "\n".join(kept)


def collect_posts(site: Path, urls: set[str], base: str) -> list[Page]:
    pages: list[Page] = []
    for html_path in sorted((site / "content" / "post").glob("*/*.html")):
        fields = _front_matter(html_path)
        _, markdown = sitehtml.convert(html_path.read_text(encoding="utf-8"))
        markdown = strip_byline_headings(
            markdown, fields.get("author", ""), fields.get("date", "")
        )
        if not markdown.strip():
            print(f"  ! empty after conversion, skipped: {html_path.name}")
            continue

        directory = urlize(html_path.parent.name)
        leaf = urlize(html_path.stem)
        url = f"{base}/post/{directory}/{leaf}/"
        pages.append(
            Page(
                source="post",
                rel_path=f"{directory}/{leaf}.md",
                url=url,
                title=fields.get("title", "") or leaf.replace("-", " ").title(),
                date=fields.get("date", ""),
                body=markdown,
                verified=url in urls,
            )
        )
    return pages


def collect_pages(site: Path, notes: Path, urls: set[str], base: str) -> list[Page]:
    """The About page, plus the hand-written notes in this repo.

    The notes live here rather than in the website checkout so that adding the
    assistant changes nothing about how the site is built. They exist because
    "who is this?", "what does he work on?" and "how do I get in touch?" are asked
    far more often than anything about the 2021 ramen-ratings post, and blog prose
    written for another purpose answers them badly — the About page loses to an
    article that happens to contain the word "author" a dozen times.
    """
    pages: list[Page] = []

    about = site / "content" / "about.md"
    if about.exists():
        fields, body = sitehtml.split_front_matter(
            about.read_text(encoding="utf-8")
        )
        url = f"{base}/about/"
        pages.append(
            Page("page", "about.md", url, fields.get("title", "About"),
                 fields.get("date", ""), body.strip(), url in urls)
        )

    for extra in sorted(notes.glob("*.md")):
        fields, body = sitehtml.split_front_matter(
            extra.read_text(encoding="utf-8")
        )
        pages.append(
            Page("page", extra.name, fields.get("url", f"{base}/"),
                 fields.get("title", extra.stem), fields.get("date", ""),
                 body.strip(), True)
        )
    return pages


def write(pages: list[Page], out: Path) -> int:
    written = 0
    for page in pages:
        target = out / page.source / page.rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        header = [f"URL: {page.url}", f"Title: {page.title}"]
        if page.date:
            header.append(f"Date: {page.date}")
        header.append("---")
        target.write_text("\n".join(header) + "\n\n" + page.body + "\n",
                          encoding="utf-8")
        written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default=DEFAULT_SITE,
                        help="path to the personal-website checkout")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help="where to write the corpus")
    parser.add_argument("--notes", default=DEFAULT_NOTES,
                        help="hand-written notes to index alongside the site")
    parser.add_argument("--strict", action="store_true",
                        help="fail if any permalink cannot be verified")
    parser.add_argument("--clean", action="store_true",
                        help="remove the output tree first")
    args = parser.parse_args()

    site = Path(args.site).expanduser().resolve()
    if not (site / "content").is_dir():
        print(f"No Hugo content/ under {site}", file=sys.stderr)
        return 2

    out = Path(args.out).resolve()
    if args.clean and out.exists():
        import shutil

        shutil.rmtree(out)

    urls, base = sitemap_urls(site)
    print(f"Reading {site}")
    print(f"  sitemap: {len(urls)} published URLs, base {base}")

    notes = Path(args.notes).resolve()
    pages = collect_posts(site, urls, base) + collect_pages(
        site, notes, urls, base
    )
    unverified = [page for page in pages if not page.verified]

    written = write(pages, out)
    words = sum(len(page.body.split()) for page in pages)
    print(f"  wrote {written} files to {out} ({words:,} words)")

    if unverified:
        print(f"  {len(unverified)} permalink(s) not in the sitemap "
              f"(normal for articles newer than the committed public/ build):")
        for page in unverified:
            print(f"      {page.url}")
    if unverified and args.strict:
        print("  --strict: refusing to leave unverified permalinks", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
