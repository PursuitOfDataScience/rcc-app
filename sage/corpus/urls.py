"""Where a document is published — the one thing a citation cannot get wrong.

A URL scheme answers "given this file in this tree, what should the reader's browser
open?", and the answer depends entirely on what published the tree. mkdocs with
`use_directory_urls` publishes `slurm/sbatch.md` at `slurm/sbatch/`; a scraped mirror
carries the original URL inside each file; a plain static host serves the path as it
stands; a private corpus has no public URL at all.

Registered by name so a source declares which one it uses (`links = "mkdocs"`) and a
deployment with a fifth arrangement adds a function rather than an `if`. The previous
version of this file had the mkdocs rule inline in the chunker behind
`if source == "docs"`, which meant every new corpus was an edit to the chunker.
"""

from __future__ import annotations

import re

from ..profile import Source
from ..registry import Registry

# (source, rel_path, anchor, page_url) -> url. `page_url` is whatever the reader
# found inside the file itself, which only the embedded scheme has any use for.
schemes: Registry = Registry("url scheme")


def _base(source: Source) -> str:
    return source.base_url.rstrip("/")


def mkdocs(source: Source, rel_path: str, anchor: str = "", page_url: str = "") -> str:
    """Map `slurm/sbatch.md` to its published mkdocs URL.

    An `index.md` is the directory it sits in, at every depth, not just the top one.
    mkdocs runs with `use_directory_urls` (the default), which publishes
    `software/index.md` at `software/` — so citing it to `software/index/` is a 404,
    and it was: 16 indexed sections across `software/index.md` and
    `tutorials/gis/index.md` pointed at a dead page.

    With no `base_url` there is no URL, which is what `direct` below has always said
    and this did not: it returned `/slurm/sbatch/#gpu-jobs`, a root-relative href that
    the reader's browser resolves against *this app's* host. Every citation in such a
    deployment then pointed at a page Streamlit does not serve — a link that looks
    right, leaves the app, and 404s, which is precisely the confident wrong citation
    the `none` scheme's docstring says this module exists to prevent. An empty
    `base_url` is not a deployment's decision to serve links from its own origin; it
    is a profile that has not said where its documents are published, and the honest
    answer to "what should the browser open?" is nothing. A base URL that *is* set
    stays honoured however it is written, so a genuinely same-origin `/docs/` keeps
    working.
    """
    if not source.base_url:
        return ""
    slug = re.sub(r"\.md$", "", rel_path, flags=re.IGNORECASE).strip("/")
    slug = re.sub(r"(?:^|/)index$", "", slug).strip("/")
    url = source.base_url if not slug else f"{_base(source)}/{slug}/"
    return f"{url}#{anchor}" if anchor else url


def embedded(
    source: Source, rel_path: str, anchor: str = "", page_url: str = ""
) -> str:
    """The URL the file records for itself, which is what a scraped mirror has.

    The anchor is dropped rather than appended: a scraped page has no heading
    structure to have anchors *for*, so one would be a link to a fragment that does
    not exist on the page it points at. Falling back to the site root keeps a citation
    pointing somewhere real when a file arrived without its header.
    """
    return page_url or source.base_url


def direct(source: Source, rel_path: str, anchor: str = "", page_url: str = "") -> str:
    """The path as it stands under the base URL, for a plainly-served tree."""
    if not source.base_url:
        return ""
    url = f"{_base(source)}/{rel_path.lstrip('/')}"
    return f"{url}#{anchor}" if anchor else url


def none(source: Source, rel_path: str, anchor: str = "", page_url: str = "") -> str:
    """A corpus with nowhere to send the reader.

    An empty string rather than a fabricated one. The Sources strip skips a chunk
    with no URL; a link to a host that does not serve this document is a confident
    wrong citation, which is the failure this whole module exists to prevent.
    """
    return ""


schemes.register("mkdocs", mkdocs)
schemes.register("embedded", embedded)
schemes.register("direct", direct)
schemes.register("none", none)


def build(source: Source, rel_path: str, anchor: str = "", page_url: str = "") -> str:
    """The URL for one document, under whichever scheme its source declares."""
    return schemes.get(source.links)(source, rel_path, anchor, page_url)
