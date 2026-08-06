# 🌱 Sage — RCC User Guide Assistant

A chat assistant for the University of Chicago's [Research Computing Center](https://rcc.uchicago.edu/). Ask about accounts, SSH, Slurm jobs, storage, and software — answers are retrieved from the **official RCC User Guide** and RCC website, and every answer links the exact sections it used.

Built with [Streamlit](https://streamlit.io/) and the [Mistral](https://mistral.ai/) API. **Read-only and RAG-only** — it reads documentation and never runs commands on the cluster.

## Features

- 🔎 **Grounded answers** — retrieves real RCC documentation; no invented commands, partitions or quotas.
- 🔗 **Real citations** — a Sources strip under each answer deep-links to the section it came from, plus Related sections from the same page.
- 💬 **Streaming replies** with conversation memory for follow-ups.
- 📎 **File uploads** — drop in a PDF or text file and ask about it.
- 🗂️ **Self-updating docs** — one command refreshes the bundled guide.
- ♿ **Light and dark themes**, keyboard focus, reduced-motion support, and a print stylesheet.

## Quickstart

```bash
pip install -r requirements.txt
export MISTRAL_API_KEY=...
streamlit run app.py            # → http://localhost:8501
```

Or put the key in `.streamlit/secrets.toml` (gitignored):

```toml
MISTRAL_API_KEY = "..."
```

## How it works

The model gets two tools:

- `search_docs(query)` — BM25 over the documentation, ranked with IDF, length normalization, a title/path boost and RCC-specific synonym expansion (so "my job got killed" reaches the OOM docs).
- `read_doc(path)` — read one section in full.

The corpus is indexed at **heading-sized chunks**, not whole files, so a citation can deep-link to `…/slurm/sbatch/#gpu-jobs` and nothing has to be truncated. mkdocs-material syntax (content tabs, admonitions, kramdown attribute lists, raw HTML) is normalized away at index time, which matters most for content tabs: read raw, cluster-specific command variants collapse into one undifferentiated blob.

Reads resolve against the in-memory index rather than the filesystem, so only indexed documents can be reached.

## Configuration

Everything is environment-driven. The defaults are in [`sage/config.py`](sage/config.py).

| Variable | Default | Purpose |
|---|---|---|
| `MISTRAL_API_KEY` | *(required)* | Mistral API key (or `.streamlit/secrets.toml`) |
| `SAGE_MODEL` | `mistral-small-latest` | Chat model |
| `SAGE_MAX_TOKENS` | `1600` | Response cap |
| `SAGE_TEMPERATURE` | `0.2` | Sampling temperature |
| `RCC_DOCS_PATH` | `./docs` | User Guide markdown source |
| `RCC_WEB_PATH` | `./web` | Scraped website text source |
| `SAGE_EXCLUDE_HOSTS` | radiology + vislab hosts | Scraped hosts to keep out of the index (`SAGE_EXCLUDE_HOSTS=` indexes everything) |
| `SAGE_EXCLUDE_FILES` | publication lists | Files to keep out of the index |
| `SAGE_SEARCH_RESULTS` | `6` | Results per search |
| `SAGE_SYNONYM_WEIGHT` | `0.8` | Weight of expanded synonym terms |
| `SAGE_HISTORY_CHAR_BUDGET` | `48000` | History size before oldest turns are trimmed |
| `SAGE_MAX_UPLOAD_BYTES` | `10485760` | Upload size limit |
| `SAGE_FEEDBACK_LOG` | *(unset)* | Path to a JSONL file for 👍/👎 and zero-result queries. Unset = nothing is recorded |
| `LOG_LEVEL` | `WARNING` | Python log level |

Server settings (theme, upload limit, XSRF) live in [`.streamlit/config.toml`](.streamlit/config.toml). `base` is deliberately unset there so Streamlit follows the browser's colour scheme and stays in sync with the stylesheet.

## Development

```bash
pip install -r requirements-dev.txt
pytest          # unit tests + retrieval eval
ruff check .    # lint
```

### Checking the layout without Streamlit

Streamlit often cannot be installed where this repo is worked on, and every UI bug
that has actually shipped here was pure CSS. `tools/render_check.py` renders
`static/app.css` against a replica of Streamlit's DOM in headless Chromium and
measures whether anything is clipped, hidden under the fixed input bar, or wrapping
onto an extra line:

```bash
python tools/render_check.py                 # measure and report
python tools/render_check.py "New subtitle"  # try alternative hero copy
```

Run it after touching `static/app.css`. It catches what reading the CSS does not —
it found the newest answer sitting 131px underneath the chat input, and the hero
subtitle wrapping to two lines.

### The retrieval eval

[`tests/test_retrieval_eval.py`](tests/test_retrieval_eval.py) is a golden set of real RCC questions paired with the page that should answer them. It is the safety net for any change to chunking, ranking or synonyms — without it, every tuning decision is a guess.

Current: **recall@5 97%, recall@3 94%, precision@1 79%** over 33 cases.

Add a case whenever someone reports a bad answer. If a case fails, fix the ranking rather than loosening the case. Questions lexical search genuinely cannot reach are listed in `KNOWN_GAPS` and marked `xfail` so they stay visible.

## Keeping docs fresh

The bundled `docs/`/`web/` snapshot comes from the upstream [`user-guide`](https://github.com/rcc-uchicago/user-guide) repo. Run from an internet-connected host:

```bash
./refresh-docs.sh            # sync docs + web, stamp docs_snapshot.json
./refresh-docs.sh --scrape   # also re-scrape the RCC website
```

Paths default to repo-relative locations and can be overridden with `RCC_USER_GUIDE_REPO`, `RCC_WEB_MIRROR` and `RCC_WEB_SCRAPER`. The website scraper is **not** vendored here, so `--scrape` needs `RCC_WEB_SCRAPER` pointed at it.

The sync date and upstream commit are recorded in `docs_snapshot.json` and shown in the app's ℹ️ panel.

## Layout

```
app.py                  # Streamlit UI: layout, session state, the tool loop
sage/
  config.py             # environment-driven settings
  normalize.py          # mkdocs/kramdown -> clean text
  corpus.py             # discovery, heading-level chunking, citation URLs
  search.py             # BM25 + stemming + synonym expansion
  tools.py              # the two model-facing tools
  links.py              # rewrite internal paths to published URLs
  files.py              # upload handling
  history.py            # message building, attachment stubbing, trimming
  llm.py                # Mistral client, streaming, typed errors
  prompts.py            # system prompt
  feedback.py           # optional 👍/👎 sink
static/app.css          # all styling
static/app.js           # DOM touch-ups Streamlit cannot express
tests/                  # unit tests, app smoke tests, retrieval eval
refresh-docs.sh         # pull upstream docs -> docs/ + web/
docs/                   # RCC User Guide (markdown)
web/                    # scraped RCC website (text)
docs_snapshot.json      # source commit + sync date
```

## Known gaps

- **Semantic search.** Retrieval is lexical. Adding `mistral-embed` vectors fused with BM25 would close cases like "which queue should I submit to" (`slurm/partitions.md` never uses the word "queue").
- **No auth or rate limiting.** Deployed publicly, the API key is exposed to unlimited use. Put it behind CNetID SSO or Cloudflare Access first.
- **Figures are not rendered.** The Globus and ThinLinc walkthroughs are mostly screenshots; `docs/img/` is ~41 MB of images the text pipeline cannot use.
- **`docs/data_transfer/cloud/rclone.md` is empty upstream**, so rclone questions cannot be answered. Indexing logs a warning for any page with no content.
- **Cancelling a generation** uses Streamlit's own run indicator; there is no in-page Stop button.
