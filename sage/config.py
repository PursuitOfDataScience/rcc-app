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
        "mimo-v2.5",
        "nemotron-3-ultra",
        "north-mini-code",
    ),
)

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
WEB_CHUNK_CHARS = _env_int("SAGE_WEB_CHUNK_CHARS", 2400)
WEB_CHUNK_OVERLAP = _env_int("SAGE_WEB_CHUNK_OVERLAP", 240)

# --- search ----------------------------------------------------------------

SEARCH_RESULTS = _env_int("SAGE_SEARCH_RESULTS", 6)
SNIPPET_CHARS = _env_int("SAGE_SNIPPET_CHARS", 240)

BM25_K1 = _env_float("SAGE_BM25_K1", 1.5)
BM25_B = _env_float("SAGE_BM25_B", 0.75)
TITLE_BOOST = _env_float("SAGE_TITLE_BOOST", 2.5)
PATH_BOOST = _env_float("SAGE_PATH_BOOST", 1.2)
# 0.8 measured best on tests/test_retrieval_eval.py (recall@3 94%→97%, p@1 76%→79%)
# without raising scores for off-topic queries. Re-run that eval if you change it.
SYNONYM_WEIGHT = _env_float("SAGE_SYNONYM_WEIGHT", 0.8)

# --- conversation ----------------------------------------------------------

# Rough character budget for the history sent upstream. Trimming happens oldest
# first; the system prompt and the current question are never dropped.
HISTORY_CHAR_BUDGET = _env_int("SAGE_HISTORY_CHAR_BUDGET", 48000)
# Older attachments collapse to a stub so a PDF is not re-uploaded every turn.
ATTACHMENT_FULL_TEXT_TURNS = _env_int("SAGE_ATTACHMENT_FULL_TEXT_TURNS", 1)
MAX_PROMPT_CHARS = _env_int("SAGE_MAX_PROMPT_CHARS", 8000)

# --- uploads ---------------------------------------------------------------

MAX_UPLOAD_BYTES = _env_int("SAGE_MAX_UPLOAD_BYTES", 10 * 1024 * 1024)
MAX_FILE_TEXT_CHARS = _env_int("SAGE_MAX_FILE_TEXT_CHARS", 30000)

# What the file picker offers. Only PDF needs a parser; everything else here is text,
# and `files.process` decodes anything that is not a PDF rather than checking this
# list again — so an extension missing here is a gap in the picker's filter, not a
# refusal. It used to be eight entries, which meant the failing files were exactly
# the ones a cluster user has: a job script, the `.out`/`.err` it wrote, a Makefile,
# a `.toml`. Asking someone to rename `slurm-12345.out` to `.txt` to ask why their
# job died is a worse answer than reading it.
UPLOAD_EXTENSIONS = (
    "pdf",
    # prose and notes
    "txt", "md", "markdown", "rst", "tex", "log", "out", "err",
    # job scripts and shells
    "sh", "bash", "zsh", "sbatch", "slurm", "job", "pbs",
    # config and data
    "json", "csv", "tsv", "yml", "yaml", "toml", "ini", "cfg", "conf", "env",
    "xml", "html", "properties",
    # source
    "py", "ipynb", "r", "jl", "c", "h", "cpp", "cc", "hpp", "cu", "f", "f90",
    "java", "go", "rs", "m", "pl", "lua", "sql", "js", "ts", "make", "mk",
    "cmake", "dockerfile", "gitignore", "patch", "diff",
)

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
