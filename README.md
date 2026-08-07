# 🌱 Sage — RCC User Guide Assistant

A chat assistant for the University of Chicago's [Research Computing Center](https://rcc.uchicago.edu/). Ask about accounts, SSH, Slurm jobs, storage and software; every answer is retrieved from the **official RCC User Guide** and website, and links the sections it used.

Built with [Streamlit](https://streamlit.io/), answered by [Mistral](https://mistral.ai/) or the free models on [OpenCode Zen](https://opencode.ai/docs/zen/). **Read-only and RAG-only** — it reads documentation and never touches the cluster.

## Features

- 🔀 **Model picker** — the button in the corner of the composer switches model mid-conversation. A spent quota fails over on its own.
- 🔎 **Grounded answers** — no invented commands, partitions or quotas.
- 🔗 **Real citations** — a Sources strip deep-links to the exact section, plus Related sections from the same page.
- 💬 **Streaming replies** with memory for follow-ups.
- 📎 **File uploads** — drop in a PDF or text file and ask about it.
- 🗂️ **Self-updating docs** — one command refreshes the bundled guide.
- ♿ **Light and dark themes**, keyboard focus, reduced motion, print stylesheet.

## Quickstart

```bash
pip install -r requirements.txt
export MISTRAL_API_KEY=...        # and/or OPENCODE_API_KEY=sk-zen-...
streamlit run app.py              # → http://localhost:8501
```

At least one key is needed; set both and the picker offers both. OpenCode Zen keys
are free, which is a way to keep working once a paid quota runs out. Either can go
in `.streamlit/secrets.toml` (gitignored) instead of the environment.

## Providers

Both sit behind one interface in [`sage/providers.py`](sage/providers.py) and normalise onto the same streaming chunk, so nothing downstream knows which is in use.

- **Mistral** — the official SDK.
- **OpenCode Zen** — the OpenAI-compatible endpoint at `https://opencode.ai/zen/v1`. Its model list comes from `GET /models` at runtime, because a free tier's lineup changes without notice; `SAGE_OPENCODE_MODELS` is only the fallback.

Models that cannot call tools answer from a **single retrieval pass** instead of the search/read loop — searched up front, matching sections in the prompt, still cited. Set `SAGE_TOOLLESS_MODELS`, or let the app detect it: a provider that rejects tools is retried that way.

## How it works

The model gets two tools: `search_docs(query)`, BM25 with IDF, length normalization, a title/path boost and RCC-specific synonym expansion (so "my job got killed" reaches the OOM docs); and `read_doc(path)`, one section in full.

The corpus is indexed at **heading-sized chunks**, so a citation can deep-link to `…/slurm/sbatch/#gpu-jobs` and nothing has to be truncated. mkdocs-material syntax is normalized away at index time — most importantly content tabs, where cluster-specific command variants otherwise collapse into one blob. Reads resolve against the in-memory index, not the filesystem, so only indexed documents can be reached.

## Configuration

Environment-driven; defaults in [`sage/config.py`](sage/config.py).

| Variable | Default | Purpose |
|---|---|---|
| `MISTRAL_API_KEY` | *(one required)* | Mistral API key |
| `OPENCODE_API_KEY` | *(one required)* | OpenCode Zen key (`sk-zen-…`), free tier |
| `SAGE_DEFAULT_MODEL` | `mistral:mistral-small-latest` | Model a fresh session starts on, `provider:model-id` |
| `SAGE_MISTRAL_MODELS` | small/medium/large | Mistral models offered in the picker |
| `SAGE_OPENCODE_MODELS` | deepseek-v4-flash-free, … | Fallback list if `GET /models` fails |
| `OPENCODE_BASE_URL` | `https://opencode.ai/zen/v1` | OpenAI-compatible endpoint |
| `SAGE_TOOLLESS_MODELS` | *(empty)* | Substrings of models that cannot call tools |
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
| `SAGE_FEEDBACK_LOG` | *(unset)* | JSONL sink for 👍/👎 and zero-result queries. Unset = nothing recorded |
| `LOG_LEVEL` | `WARNING` | Python log level |

Server settings live in [`.streamlit/config.toml`](.streamlit/config.toml). `base` is deliberately unset so Streamlit follows the browser's colour scheme and stays in sync with the stylesheet.

## Keeping docs fresh

The bundled `docs/`/`web/` snapshot comes from the upstream [`user-guide`](https://github.com/rcc-uchicago/user-guide) repo. Run from an internet-connected host:

```bash
./refresh-docs.sh            # sync docs + web, stamp docs_snapshot.json
./refresh-docs.sh --scrape   # also re-scrape the RCC website
```

Paths are repo-relative and overridable with `RCC_USER_GUIDE_REPO`, `RCC_WEB_MIRROR` and `RCC_WEB_SCRAPER`. The website scraper is **not** vendored here, so `--scrape` needs `RCC_WEB_SCRAPER` pointed at it. The sync date and upstream commit land in `docs_snapshot.json`.

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
  providers.py          # Mistral + OpenAI-compatible (OpenCode Zen) adapters
  llm.py                # turn assembly, streaming, typed errors
  prompts.py            # system prompt
  feedback.py           # optional 👍/👎 sink
static/app.css          # all styling
static/app.js           # DOM touch-ups Streamlit cannot express
tests/                  # unit tests, app smoke tests, retrieval eval
tools/render_check.py   # renders app.css in headless Chromium and measures it
refresh-docs.sh         # pull upstream docs -> docs/ + web/
docs/                   # RCC User Guide (markdown)
web/                    # scraped RCC website (text)
docs_snapshot.json      # source commit + sync date
```

## Known gaps

- **Semantic search.** Retrieval is lexical. `mistral-embed` vectors fused with BM25 would close cases like "which queue should I submit to" (`slurm/partitions.md` never says "queue").
- **No auth or rate limiting.** Deployed publicly, the API key is exposed to unlimited use. Put it behind CNetID SSO or Cloudflare Access first.
- **Figures are not rendered.** The Globus and ThinLinc walkthroughs are mostly screenshots; `docs/img/` is ~41 MB the text pipeline cannot use.
- **`docs/data_transfer/cloud/rclone.md` is empty upstream**, so rclone questions cannot be answered. Indexing warns for any page with no content.
- **Cancelling a generation** uses Streamlit's own run indicator; there is no in-page Stop button.
