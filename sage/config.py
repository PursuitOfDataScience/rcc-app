"""Runtime configuration.

Every value can be overridden by an environment variable so a deployment can be
retuned without touching code. This module must stay importable without Streamlit.
"""

from __future__ import annotations

import json
import os

# --- helpers ---------------------------------------------------------------


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    """An integer setting, falling back to `default` on anything unusable.

    `minimum` is for the settings where a non-positive value is not a choice but a
    typo: `SAGE_MAX_TOKENS=-1` used to be handed straight to the provider, which
    fails the request with a message about the model rather than about the setting.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return default if minimum is not None and value < minimum else value


def _env_float(name: str, default: float, minimum: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return default if minimum is not None and value < minimum else value


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Comma-separated env override. `NAME=` (empty) explicitly clears the list."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


# --- model -----------------------------------------------------------------

# --- providers -------------------------------------------------------------
# Which provider/model a fresh session starts on, as "provider:model-id".
DEFAULT_MODEL = os.getenv("SAGE_DEFAULT_MODEL", "opencode:deepseek-v4-flash-free")

MISTRAL_MODELS = _env_list(
    "SAGE_MISTRAL_MODELS",
    ("mistral-small-latest", "mistral-medium-latest", "mistral-large-latest"),
)

# OpenCode Zen is an OpenAI-compatible endpoint fronting a set of free models —
# a way to keep working once a paid key is out of credit. The live list is
# discovered from GET /models at runtime; this is only the fallback, since a free
# tier's lineup changes without notice.
OPENCODE_BASE_URL = os.getenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/v1")
OPENCODE_MODELS = _env_list(
    "SAGE_OPENCODE_MODELS",
    (
        "deepseek-v4-flash-free",
        "big-pickle",
        "mimo-v2.5-free",
        "nemotron-3-ultra-free",
        "north-mini-code-free",
        "laguna-s-2.1-free",
        "ling-3.0-tiny-free",
        "longcat-2.0-free",
        # Both are served and both answer; they were missing from this list, so they
        # were only ever reachable through discovery and sorted to the end of the
        # picker. Added in the order they already appeared in, so today's picker is
        # unchanged and the fallback list is no longer a shorter lineup than the real
        # one.
        "ling-3.0-flash-free",
        "nemotron-3.5-lightning-free",
    ),
)
# `hy3-free` was on the list above and is gone: Zen answers a request for it with
# `401 {"message": "Model hy3-free is not supported"}`. It has not been in the served
# catalogue for as long as anyone has looked, so it only ever reached the picker on a
# run where discovery itself failed — and then it was a row that could not answer.
#
# Nothing else has been removed, and deliberately. Two models in the live lineup are
# broken today (`north-mini-code-free` returns 401 from Zen's own upstream, and
# `ling-3.0-tiny-free` returns 503 "Endpoint is unavailable"), and a hardcoded
# blocklist for those is exactly what the comment below argues against: a free tier's
# lineup moves, an endpoint that is down this week is back the next, and a list that
# quietly outlives the outage it was written for is worse than no list. What the app
# does with them is already right — a 401 fails over, a 503 offers Try again and a
# different model.

# Zen serves paid models from the same endpoint as the free ones — the discovery call
# came back with the whole Claude and GPT lineup, none of which this deployment has a
# balance for, and every one of which was offered in the picker as if it worked.
#
# Filtered by a RULE rather than a list, because Zen's free lineup changes without
# notice and a hardcoded set goes stale silently: every free model it serves is named
# with a `-free` suffix, the exception being the stealth models it publishes under a
# codename while they are free. Naming the convention keeps working when the list
# changes; naming the list does not.
ZEN_FREE_MARKS = _env_list("SAGE_ZEN_FREE_MARKS", ("-free", "big-pickle"))
# Off for a deployment with a paid Zen balance, which should see everything it can use.
ZEN_FREE_ONLY = os.getenv("SAGE_ZEN_FREE_ONLY", "1").strip().lower() not in (
    "0", "false", "no", ""
)


def is_free_zen_model(model: str) -> bool:
    lowered = (model or "").lower()
    return any(mark and mark.lower() in lowered for mark in ZEN_FREE_MARKS)

# Substrings marking models that cannot call tools. Those answer from a single
# retrieval pass instead of the search/read loop. The app also falls back
# automatically if a provider rejects a request because of tools.
TOOLLESS_MODELS = _env_list("SAGE_TOOLLESS_MODELS", ())

# Substrings marking models that can be handed a picture. Deliberately short and
# conservative: an image sent to a text-only model is a 4xx, not a graceful refusal,
# so anything not listed here gets told the file is attached and left unread rather
# than gambling with the request. Extend it as a deployment learns its own lineup.
VISION_MODELS = _env_list("SAGE_VISION_MODELS", ("pixtral", "claude"))


def sees_images(model: str) -> bool:
    lowered = (model or "").lower()
    return any(mark and mark.lower() in lowered for mark in VISION_MODELS)

# Retained for compatibility; the UI picker overrides it per session.
MODEL = os.getenv("SAGE_MODEL", "mistral-small-latest")
# Generous on purpose. 1600 was the old value and it cut answers off mid-sentence —
# "Per the RCC docs," and then nothing — which is worse than a long answer in every
# way: the reader cannot tell a finished thought from a severed one, and asking again
# costs another full request. A walkthrough with two code blocks and a Sources strip
# runs well past 1600, and no answer this app gives is improved by being truncated.
MAX_TOKENS = _env_int("SAGE_MAX_TOKENS", 8000, minimum=1)
TEMPERATURE = _env_float("SAGE_TEMPERATURE", 0.2, minimum=0.0)
# Four, not six. Every round is another provider call carrying everything read so
# far, so the cost of a turn grows faster than the round count: the tail rounds were
# the most expensive and the least productive. The retrieval eval answers its golden
# set at a mean depth of 2.1 reads, so four leaves headroom over twice what a real
# question needs, and caps the worst case at five calls instead of seven.
MAX_TOOL_ROUNDS = _env_int("SAGE_MAX_TOOL_ROUNDS", 4, minimum=1)
# Total characters of tool output one turn may accumulate, across every round.
# `history.build()` trims to HISTORY_CHAR_BUDGET once, *before* the loop, and the
# loop then appended up to MAX_TOOL_ROUNDS reads of MAX_DOC_CHARS each with nothing
# checking again — six 20k reads put 120k on top of a 48k budget, and the reader was
# told "this conversation got too long" about a conversation of one question.
TOOL_RESULT_CHAR_BUDGET = _env_int("SAGE_TOOL_RESULT_CHAR_BUDGET", 60000, minimum=1)
REQUEST_RETRIES = _env_int("SAGE_REQUEST_RETRIES", 2, minimum=0)

# --- corpus ----------------------------------------------------------------

DOCS_PATH = os.getenv("RCC_DOCS_PATH", "./docs")
WEB_PATH = os.getenv("RCC_WEB_PATH", "./web")

SOURCES = {"docs": DOCS_PATH, "web": WEB_PATH}
SOURCE_EXTENSIONS = {"docs": (".md",), "web": (".txt",)}

# The user guide is canonical and maintained; the scraped site is marketing copy.
# A mild prior keeps the guide on top when both match equally well.
SOURCE_WEIGHT = {"docs": 1.15, "web": 1.0}

# Scraped hosts that are not RCC computing documentation. `learn-radiology` is
# radiology teaching material (PI-RADS, mpMRI) and `vislab` is project showcase
# content; neither can answer an HPC how-to, and both add false-positive matches.
# Clear with `SAGE_EXCLUDE_HOSTS=` to index everything again.
EXCLUDED_HOSTS = _env_list(
    "SAGE_EXCLUDE_HOSTS",
    ("learn-radiology.rcc.uchicago.edu", "vislab.rcc.uchicago.edu"),
)

# Bare citation dumps: thousands of paper titles that answer no how-to question
# but match a lot of keywords. Matched against the path suffix.
EXCLUDED_FILES = _env_list(
    "SAGE_EXCLUDE_FILES",
    (
        "grants-publications_list-of-publications.txt",
        "grants-publications_publications.txt",
        "publications.txt",
    ),
)

# --- chunking --------------------------------------------------------------
#
# Whole-file reads used to be truncated at 15k chars, which silently cut 62% of
# docs/slurm/sbatch.md — the single most important page in the corpus. Indexing
# heading-sized chunks removes the need to truncate at all.

MAX_CHUNK_CHARS = _env_int("SAGE_MAX_CHUNK_CHARS", 6000, minimum=1)
MIN_CHUNK_CHARS = _env_int("SAGE_MIN_CHUNK_CHARS", 120, minimum=1)
# Cap for reading a whole page. Pages above it return an outline plus their
# opening, so the model asks for the section it actually needs.
MAX_DOC_CHARS = _env_int("SAGE_MAX_DOC_CHARS", 20000, minimum=1)
WEB_CHUNK_CHARS = _env_int("SAGE_WEB_CHUNK_CHARS", 2400, minimum=1)
WEB_CHUNK_OVERLAP = _env_int("SAGE_WEB_CHUNK_OVERLAP", 240, minimum=0)

# --- search ----------------------------------------------------------------

SEARCH_RESULTS = _env_int("SAGE_SEARCH_RESULTS", 6, minimum=1)
# Sections of a single page allowed in one result set. A third of the golden-set
# questions used to come back with all of the top three from one page, so a search
# asking for six sections really returned two pages and the model saw one page's view.
#
# 2 rather than "off", and rather than 1, from the numbers. Measured on the 34 golden
# cases, changing nothing else (depth = sections of the *right* page among the six the
# model is handed, which page-level recall cannot see):
#
#     cap    recall@5  recall@3   p@1    MRR    depth
#      1       100%      100%    82.4%  0.897   1.18
#      2       100%     97.1%    82.4%  0.893   2.15
#      3      97.1%     97.1%    82.4%  0.892   2.88
#     off     97.1%     97.1%    82.4%  0.887   3.56
#
# 2 is where "which queue should I submit to" — the repository's one recorded lexical
# gap — first reaches the top five, against its strict two-page expectation. It costs
# 1.4 sections of depth on average to get there. 1 buys recall@3 as well and takes
# depth down to almost nothing, which is too much to pay: a model handed one section
# per page has pointers, not evidence.
MAX_PER_PAGE = _env_int("SAGE_MAX_PER_PAGE", 2, minimum=1)
SNIPPET_CHARS = _env_int("SAGE_SNIPPET_CHARS", 240, minimum=1)

# When retrieval should admit it is weak, so the model can decline instead of
# answering from whatever happened to match. Two thresholds, because one cannot do it:
# measured over the 34 golden-set questions and a set of labelled out-of-scope probes,
# answerable questions run down to a top score of 22.8 and out-of-scope ones run up to
# 23.9, so the score alone overlaps.
#
# What separates them is the score *together with* whether the query contains a word
# the corpus has never seen. Below MIN_CONFIDENT_SCORE retrieval is weak whatever the
# words; between the two, an unseen word decides it; above STRONG_SCORE the evidence
# outweighs the unseen word, which is what stops "my CNetID is jsmith and I cannot log
# in" (40.0) and "why did job 41235567 fail" (28.3) from being told the documentation
# does not cover them.
#
# Both are pinned by tests/test_search.py::TestAssessment, on the labelled queries the
# numbers came from. Moving either constant fails them, which is the point: the last
# version of this idea shipped a threshold that no test constrained at all.
MIN_CONFIDENT_SCORE = _env_float("SAGE_MIN_CONFIDENT_SCORE", 20.0, minimum=0.0)
STRONG_SCORE = _env_float("SAGE_STRONG_SCORE", 26.0, minimum=0.0)

BM25_K1 = _env_float("SAGE_BM25_K1", 1.5, minimum=0.0)
BM25_B = _env_float("SAGE_BM25_B", 0.75, minimum=0.0)
TITLE_BOOST = _env_float("SAGE_TITLE_BOOST", 2.5, minimum=0.0)
PATH_BOOST = _env_float("SAGE_PATH_BOOST", 1.2, minimum=0.0)
# 0.8 measured best on tests/test_retrieval_eval.py (recall@3 94%→97%, p@1 76%→79%)
# without raising scores for off-topic queries. Re-run that eval if you change it.
SYNONYM_WEIGHT = _env_float("SAGE_SYNONYM_WEIGHT", 0.8, minimum=0.0)

# --- conversation ----------------------------------------------------------

# Rough character budget for the history sent upstream. Trimming happens oldest
# first; the system prompt and the current question are never dropped.
HISTORY_CHAR_BUDGET = _env_int("SAGE_HISTORY_CHAR_BUDGET", 48000, minimum=1)
# Older attachments collapse to a stub so a PDF is not re-uploaded every turn.
ATTACHMENT_FULL_TEXT_TURNS = _env_int("SAGE_ATTACHMENT_FULL_TEXT_TURNS", 1, minimum=0)
MAX_PROMPT_CHARS = _env_int("SAGE_MAX_PROMPT_CHARS", 8000, minimum=1)

# --- uploads ---------------------------------------------------------------

MAX_UPLOAD_BYTES = _env_int("SAGE_MAX_UPLOAD_BYTES", 10 * 1024 * 1024, minimum=1)
# What an image is shrunk to before it is sent, not what may be uploaded. 1568px is
# the longest edge the major vision APIs downscale to on receipt, so anything above
# it is paid for twice — once in upload and once in the request — and discarded.
IMAGE_MAX_EDGE = _env_int("SAGE_IMAGE_MAX_EDGE", 1568, minimum=64)
# Below this an image is left alone whatever its dimensions: re-encoding a small
# sharp PNG as JPEG to save a few KB is a bad trade for a screenshot of text.
IMAGE_MAX_BYTES = _env_int("SAGE_IMAGE_MAX_BYTES", 256 * 1024, minimum=1)
# Across all files on one turn, which the per-file limit above does not bound: four
# 9 MB screenshots are four legal uploads and one 50 MB request, and the only thing
# that stopped it was the provider's own 413 — surfaced to the reader as "this
# conversation got too long. Clear the chat", about a conversation of one question.
MAX_ATTACHED_BYTES = _env_int("SAGE_MAX_ATTACHED_BYTES", 20 * 1024 * 1024, minimum=1)
MAX_FILE_TEXT_CHARS = _env_int("SAGE_MAX_FILE_TEXT_CHARS", 30000, minimum=1)


# --- links -----------------------------------------------------------------

# The canonical host, which is what `docs/CNAME` in this repository publishes. The
# github.io address that used to be here still works, but only as a 301 to this one:
# every citation cost a redirect, showed the reader a github.io hostname on hover for
# a University service, and would break the day GitHub Pages stopped forwarding.
DOCS_BASE_URL = os.getenv("RCC_DOCS_BASE_URL", "https://docs.rcc.uchicago.edu/")
# The email, not a page: it is what the system prompt hands a user whose question the
# documentation cannot answer, and it goes into the answer text. There was a
# HELP_DESK_URL beside this for the caveat line under the input; that line is gone and
# nothing else linked it, so it went too rather than sitting here unused.
HELP_DESK_EMAIL = os.getenv("RCC_HELP_EMAIL", "help@rcc.uchicago.edu")

# --- limits ----------------------------------------------------------------
#
# On by default, and deliberately so. The failure this guards against is not abuse
# but arithmetic: one shared key, one public URL, and a turn that costs up to
# MAX_TOOL_ROUNDS + 1 provider calls. A key spent at lunchtime does not slow the app
# down, it ends it for everyone until a human notices.
#
# The defaults are set to be invisible to a reader using this as intended. An answer
# takes 20–60s to read, so sustained demand is well under the refill rate, and the
# burst covers the real case of already knowing your next two questions.

# Questions a reader may fire back-to-back before the sustained rate applies.
RATE_BURST = _env_int("SAGE_RATE_BURST", 5, minimum=0)
# One token back per this many seconds: 15s ≈ 4/min sustained, ≈ 20 per 5 minutes.
RATE_REFILL_SECONDS = _env_float("SAGE_RATE_REFILL_SECONDS", 15.0, minimum=0.0)
# Per person per day. Generous: it is a backstop against a loop, not a quota.
DAILY_TURNS = _env_int("SAGE_DAILY_TURNS", 100, minimum=0)
DAILY_WINDOW_SECONDS = _env_float("SAGE_DAILY_WINDOW_SECONDS", 86_400.0, minimum=1.0)
# Provider calls for the WHOLE deployment per window. 0 = no budget, which is the
# default only because the right number depends on a plan this repo cannot see.
# Set it from real spend: daily budget ÷ measured cost per call. Until it is set,
# nothing bounds what the shared key can be charged in a day.
CALL_BUDGET = _env_int("SAGE_CALL_BUDGET", 0, minimum=0)
BUDGET_WINDOW_SECONDS = _env_float("SAGE_BUDGET_WINDOW_SECONDS", 86_400.0, minimum=1.0)

# --- access ----------------------------------------------------------------
#
# Off unless configured, because turning it on without an OIDC provider in
# `.streamlit/secrets.toml` would lock everyone out of a working app, including
# whoever set the variable. `require_login()` checks both.
REQUIRE_LOGIN = os.getenv("SAGE_REQUIRE_LOGIN", "0").strip().lower() in (
    "1", "true", "yes", "on"
)
# Email domains allowed past the login gate. Empty = any account the provider
# authenticates, which for a Google client means the whole internet — so set it.
ALLOWED_EMAIL_DOMAINS = _env_list("SAGE_ALLOWED_EMAIL_DOMAINS", ())


def email_allowed(email: str) -> bool:
    """Is this address inside one of the allowed domains? Empty list allows all."""
    if not ALLOWED_EMAIL_DOMAINS:
        return True
    lowered = (email or "").strip().lower()
    return any(
        lowered.endswith("@" + domain.strip().lower().lstrip("@"))
        for domain in ALLOWED_EMAIL_DOMAINS
        if domain.strip()
    )


# --- ops -------------------------------------------------------------------

LOG_LEVEL = os.getenv("LOG_LEVEL", "WARNING").upper()
# Set to a writable path to collect thumbs-up/down as JSON lines. Unset = no sink.
FEEDBACK_LOG = os.getenv("SAGE_FEEDBACK_LOG", "")
SNAPSHOT_FILE = os.getenv("SAGE_SNAPSHOT_FILE", "./docs_snapshot.json")


API_KEY_VARS = {"mistral": "MISTRAL_API_KEY", "opencode": "OPENCODE_API_KEY"}


def api_key(provider: str = "mistral") -> str:
    """Provider key from the environment. The UI adds an `st.secrets` fallback."""
    return os.getenv(API_KEY_VARS.get(provider, "MISTRAL_API_KEY"), "")


def snapshot() -> dict:
    """Docs freshness stamp written by refresh-docs.sh. Never raises."""
    try:
        with open(SNAPSHOT_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}
