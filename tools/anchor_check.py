#!/usr/bin/env python3
"""Check every citation anchor this app generates against the published site.

A citation that opens the right page at the wrong place is invisible from inside
the repository: the URL is well-formed, the page is real, and the only way to know
the `#fragment` misses is to ask the published HTML what ids it actually has.

Two bugs shipped for want of this check, both silent:

* `plain_heading()` deleted underscores, so the three corpus headings that contain
  an identifier — `EVP_KDF_ctrl`, `ssh_exchange_identification`, `<job_id>` —
  generated anchors mkdocs has never published. Those are exactly the FAQ entries a
  reader reaches by pasting an error message.
* the mkdocs URL scheme special-cased only a top-level `index`, so `software/index.md` was
  cited to `software/index/`, which is a 404. mkdocs with `use_directory_urls`
  publishes `<dir>/index.md` at `<dir>/`.

Network-bound and therefore not part of the test suite: run it after touching
`slugify`, `plain_heading` or a URL scheme, and when the corpus is refreshed.

    python tools/anchor_check.py            # every cited page
    python tools/anchor_check.py --limit 20 # a quick sample

Exit status is 1 if any anchor or page is unreachable, so CI can gate on it.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sage import corpus as corpus_mod  # noqa: E402
from sage import profile  # noqa: E402

# `id="..."` on any element. mkdocs-material puts the heading id on the <h_> itself,
# but permalink anchors and admonitions carry ids too and a match against any of them
# is still a working deep link.
_ID = re.compile(r'\sid="([^"]+)"')


def _fetch(url: str, timeout: float):
    """(ids, status) for one page; ids is None when it could not be read."""
    import httpx

    try:
        # Redirects are followed so a base-URL change is a *warning* here rather than
        # a wall of failures: what this tool is asking is "does the anchor exist".
        response = httpx.get(url, follow_redirects=True, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — any network failure reads the same
        return None, repr(exc)[:80]
    if response.status_code != 200:
        return None, str(response.status_code)
    return set(_ID.findall(response.text)), "200"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0,
                        help="check only the first N pages (0 = all)")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()

    try:
        import httpx  # noqa: F401
    except ImportError:
        print("httpx is not installed; skipping the anchor check.")
        return 0

    built = corpus_mod.build()
    # Only trees whose URL scheme places an anchor have anchors worth checking: a
    # scraped mirror cites whole pages, and a private corpus cites nothing. Read from
    # the profile rather than from one hardcoded base URL, so a deployment that adds a
    # third documentation site gets it checked without editing this file.
    bases = tuple(
        source.base_url
        for source in profile.active().sources
        if source.base_url and source.links in ("mkdocs", "direct")
    )
    wanted: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for chunk in built.chunks:
        if not bases or not chunk.url.startswith(bases) or "#" not in chunk.url:
            continue
        if not chunk.heading:
            continue
        base, anchor = chunk.url.split("#", 1)
        wanted[base].append((chunk.path, chunk.heading, anchor))

    pages = sorted(wanted)
    if args.limit:
        pages = pages[: args.limit]
    print(f"{len(pages)} pages, {sum(len(wanted[p]) for p in pages)} anchors")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        fetched = dict(
            zip(pages, pool.map(lambda u: _fetch(u, args.timeout), pages), strict=True)
        )

    unreachable, broken, checked = [], [], 0
    for base in pages:
        ids, status = fetched[base]
        if ids is None:
            unreachable.append((base, status))
            continue
        for path, heading, anchor in wanted[base]:
            checked += 1
            if anchor not in ids:
                broken.append((path, heading, anchor))

    for base, status in unreachable:
        print(f"  UNREACHABLE ({status})  {base}")
    for path, heading, anchor in broken:
        print(f"  BROKEN  {path}\n     heading: {heading[:80]}\n     anchor : #{anchor}")

    print(
        f"\nchecked {checked} anchors on {len(pages) - len(unreachable)} pages: "
        f"{len(broken)} broken, {len(unreachable)} pages unreachable"
    )
    return 1 if broken or unreachable else 0


if __name__ == "__main__":
    raise SystemExit(main())
