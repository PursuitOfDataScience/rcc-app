"""Redact secrets and identifiers before anything is written down or sent on.

HPC users paste job scripts, `.out` files, `.bashrc` fragments and configs. Those
contain CNetIDs in filesystem paths, hostnames, and — reliably, eventually —
credentials. Anything that logs a question, exports a transcript or drafts a help
desk message runs through here first.

Two design rules, both load-bearing:

* **Replace, do not delete.** `<CNETID>` keeps the sentence's shape, so a redacted
  question can still be read, grouped and counted. Deleting the token would pay the
  privacy cost of collection and get nothing back.
* **Fail closed.** `scrub()` never raises; `contains_secret()` is checked *after*
  scrubbing by the caller, so a pattern this module misses drops the record rather
  than writing it.

The credential patterns are deliberately conservative and shape-based. This is not
a DLP product: it is the difference between a stored credential and a stored
placeholder, for the handful of shapes that actually turn up in a cluster paste.
"""

from __future__ import annotations

import re

# --- credentials -----------------------------------------------------------
#
# Ordered most specific first. Each is a shape that is a secret whatever the
# surrounding text says.
_SECRETS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("<PRIVATE_KEY>", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL)),
    ("<JWT>", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+")),
    ("<API_KEY>", re.compile(r"\bsk-(?:zen-|ant-|proj-)?[A-Za-z0-9_-]{16,}")),
    ("<API_KEY>", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("<API_KEY>", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("<API_KEY>", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("<API_KEY>", re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}\b")),
    # `export TOKEN=...`, `password: ...`, `--password=...`, `-p hunter2`
    ("<SECRET>", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|passwd|password|pwd)\b\s*[:=]\s*"
        r"['\"]?[^\s'\";,]{4,}")),
    ("<SECRET>", re.compile(r"(?i)--pass(?:word)?[=\s]+\S+")),
    ("<SECRET>", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{12,}")),
)

# --- RCC-specific identifiers ----------------------------------------------
#
# This is where the actual de-identification happens. Slurm job ids, node names,
# partition names, module names and error strings are deliberately *kept* — they are
# not identifying and they are most of the diagnostic value.
_IDENTIFIERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("/home/<CNETID>", re.compile(r"/home/[A-Za-z0-9._-]+")),
    (r"/project2/<PI>/<CNETID>", re.compile(
        r"/project2?/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")),
    (r"/project2/<PI>", re.compile(r"/project2?/[A-Za-z0-9._-]+")),
    ("/scratch/<CLUSTER>/<CNETID>", re.compile(
        r"/scratch/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")),
    ("<EMAIL>", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # `user@midway3.rcc.uchicago.edu`, `ssh cnetid@midway2`
    ("<CNETID>@", re.compile(r"\b[A-Za-z][A-Za-z0-9._-]{1,30}@(?=midway|beagle|skyway)")),
    ("<IP>", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
)

# Only used to *detect* a leak after scrubbing, never to redact.
_RESIDUAL = tuple(pattern for _label, pattern in _SECRETS)


def scrub(text: str) -> str:
    """Replace credentials and identifiers with placeholders. Never raises."""
    if not text:
        return ""
    try:
        out = str(text)
        for label, pattern in _SECRETS:
            out = pattern.sub(label, out)
        for label, pattern in _IDENTIFIERS:
            out = pattern.sub(label, out)
        return out
    except Exception:  # a redactor that crashes must not become a writer
        return "<REDACTION FAILED>"


def contains_secret(text: str) -> bool:
    """True if a credential shape survives — the caller should drop the record.

    Checked after `scrub`, so this is a canary on the patterns above rather than a
    second line of redaction. A record that trips it is discarded, which is the
    visible-failure choice: losing one log line beats storing one key.
    """
    if not text:
        return False
    return any(pattern.search(text) for pattern in _RESIDUAL)


def looks_like_secret(text: str) -> bool:
    """Whether the *user's own* input appears to contain a credential.

    Used to warn them. By the time this fires the text has already gone to the model
    provider, so the honest message is about rotating the key, not about having
    caught it in time.
    """
    if not text:
        return False
    return any(pattern.search(str(text)) for pattern in _RESIDUAL)
