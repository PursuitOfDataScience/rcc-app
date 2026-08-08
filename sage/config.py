"""Runtime configuration.

Every value can be overridden by an environment variable so a deployment can be
retuned without touching code. This module must stay importable without Streamlit.
"""

from __future__ import annotations

import json
import os

# --- helpers ---------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Comma-separated env override. `NAME=` (empty) explicitly clears the list."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


# --- model -----------------------------------------------------------------

# --- providers -------------------------------------------------------------
# Which provider/model a fresh session starts on, as "provider:model-id".
DEFAULT_MODEL = os.getenv("SAGE_DEFAULT_MODEL", "mistral:mistral-small-latest")

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
        "hy3-free",
        "laguna-s-2.1-free",
        "ling-3.0-tiny-free",
        "longcat-2.0-free",
    ),
)

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
MAX_TOKENS = _env_int("SAGE_MAX_TOKENS", 8000)
TEMPERATURE = _env_float("SAGE_TEMPERATURE", 0.2)
MAX_TOOL_ROUNDS = _env_int("SAGE_MAX_TOOL_ROUNDS", 6)
REQUEST_RETRIES = _env_int("SAGE_REQUEST_RETRIES", 2)

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

MAX_CHUNK_CHARS = _env_int("SAGE_MAX_CHUNK_CHARS", 6000)
MIN_CHUNK_CHARS = _env_int("SAGE_MIN_CHUNK_CHARS", 120)
# Cap for reading a whole page. Pages above it return an outline plus their
# opening, so the model asks for the section it actually needs.
MAX_DOC_CHARS = _env_int("SAGE_MAX_DOC_CHARS", 20000)
# A section read below this length gets its page outline appended; above it, the
# outline is not worth the tokens. It was appended unconditionally, which on
# docs/slurm/sbatch.md meant 222 tokens of navigation on a 409-token section — and
# because every tool round resends the whole conversation, again in each later round.
OUTLINE_BELOW_CHARS = _env_int("SAGE_OUTLINE_BELOW_CHARS", 1200)
WEB_CHUNK_CHARS = _env_int("SAGE_WEB_CHUNK_CHARS", 2400)
WEB_CHUNK_OVERLAP = _env_int("SAGE_WEB_CHUNK_OVERLAP", 240)

# --- search ----------------------------------------------------------------

SEARCH_RESULTS = _env_int("SAGE_SEARCH_RESULTS", 6)
SNIPPET_CHARS = _env_int("SAGE_SNIPPET_CHARS", 240)

# At most this many sections from one page in a single set of results. Measured
# before it existed: 53% of the six slots went to a page already in the list, so a
# search asking for six sections effectively asked for two or three.
MAX_PER_PAGE = _env_int("SAGE_MAX_PER_PAGE", 2)

# Below this top score — or with any query word absent from the whole corpus —
# retrieval reports itself as weak so the model can decline instead of answering
# from whatever happened to match. 12.0 sits under every passing case in
# tests/test_retrieval_eval.py and above the off-topic queries it checks; re-run
# that eval if you change it.
MIN_CONFIDENT_SCORE = _env_float("SAGE_MIN_CONFIDENT_SCORE", 12.0)

BM25_K1 = _env_float("SAGE_BM25_K1", 1.5)
# 0.95, not the conventional 0.75. Once `_stem` collapsed verb inflections, common
# HPC verbs (run/running, cancel/cancelled, request/requested) became high-frequency
# terms, and long FAQ pages that repeat them started beating the focused page that
# actually answers — nine of ten precision@1 misses had the right page at rank 2.
# Stronger length normalization is what fixed it, and it took recall@3 from 94% to
# 100%. Re-run tests/test_retrieval_eval.py if you change it.
BM25_B = _env_float("SAGE_BM25_B", 0.95)
TITLE_BOOST = _env_float("SAGE_TITLE_BOOST", 2.5)
# 2.0, up from 1.2: with the stronger length normalization above, the path is a
# more reliable topic signal than raw term frequency. Worth +3pp recall@3.
PATH_BOOST = _env_float("SAGE_PATH_BOOST", 2.0)
# 0.5, down from 0.8. Synonyms are what let "my job got killed" reach the OOM docs,
# but at 0.8 they also let `cuda` pull software/compilers.md above slurm/sbatch.md
# for "how do I request a GPU". Measured across 0.3–0.8 on the eval: 0.5 is where
# recall@3 reaches 100% without giving up precision@1.
SYNONYM_WEIGHT = _env_float("SAGE_SYNONYM_WEIGHT", 0.5)

# --- conversation ----------------------------------------------------------

# Rough character budget for the history sent upstream. Trimming happens oldest
# first; the system prompt and the current question are never dropped.
HISTORY_CHAR_BUDGET = _env_int("SAGE_HISTORY_CHAR_BUDGET", 48000)
# Older attachments collapse to a stub so a PDF is not re-uploaded every turn.
ATTACHMENT_FULL_TEXT_TURNS = _env_int("SAGE_ATTACHMENT_FULL_TEXT_TURNS", 1)
MAX_PROMPT_CHARS = _env_int("SAGE_MAX_PROMPT_CHARS", 8000)

# --- uploads ---------------------------------------------------------------

MAX_UPLOAD_BYTES = _env_int("SAGE_MAX_UPLOAD_BYTES", 10 * 1024 * 1024)
# Across all files on one turn, which the per-file limit above does not bound: four
# 9 MB screenshots are four legal uploads and one 50 MB request, and the only thing
# that stopped it was the provider's own 413 — surfaced to the reader as "this
# conversation got too long. Clear the chat", about a conversation of one question.
MAX_ATTACHED_BYTES = _env_int("SAGE_MAX_ATTACHED_BYTES", 20 * 1024 * 1024)
MAX_FILE_TEXT_CHARS = _env_int("SAGE_MAX_FILE_TEXT_CHARS", 30000)


# --- links -----------------------------------------------------------------

DOCS_BASE_URL = os.getenv(
    "RCC_DOCS_BASE_URL", "https://rcc-uchicago.github.io/user-guide/"
)
# The email, not a page: it is what the system prompt hands a user whose question the
# documentation cannot answer, and it goes into the answer text. There was a
# HELP_DESK_URL beside this for the caveat line under the input; that line is gone and
# nothing else linked it, so it went too rather than sitting here unused.
HELP_DESK_EMAIL = os.getenv("RCC_HELP_EMAIL", "help@rcc.uchicago.edu")

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
