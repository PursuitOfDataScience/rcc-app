# 🌱 Sage — RCC User Guide Assistant

A chat assistant for the University of Chicago's [Research Computing Center](https://rcc.uchicago.edu/). Ask about accounts, SSH, Slurm jobs, storage, and software — answers are retrieved from the **official RCC User Guide** and RCC website, and every answer links the exact sections it used.

Built with [Streamlit](https://streamlit.io/). Answers come from [Mistral](https://mistral.ai/) or from the free models on [OpenCode Zen](https://opencode.ai/docs/zen/), switchable from a picker in the app. **Read-only and RAG-only** — it reads documentation and never runs commands on the cluster.

## Features

- 🔀 **Model picker** — the button under the chat input names the model in use; open it to switch between Mistral and OpenCode Zen's free models mid-conversation. A spent quota also fails over on its own, and the error card offers the switch in one click.
- 🔎 **Grounded answers** — retrieves real RCC documentation; no invented commands, partitions or quotas.
- 🔗 **Real citations** — a Sources strip under each answer deep-links to the section it came from, plus Related sections from the same page.
- 💬 **Streaming replies** with conversation memory for follow-ups.
- 📎 **File uploads** — drop in a PDF or text file and ask about it.
- 🗂️ **Self-updating docs** — one command refreshes the bundled guide.
- ♿ **Light and dark themes**, keyboard focus, reduced-motion support, and a print stylesheet.

## Quickstart

```bash
pip install -r requirements.txt
export MISTRAL_API_KEY=...        # and/or OPENCODE_API_KEY=sk-zen-...
streamlit run app.py              # → http://localhost:8501
```

At least one key is needed; set both and a picker appears under the chat input.
[OpenCode Zen](https://opencode.ai/docs/zen/) keys are free and start with
`sk-zen-`, which is a way to keep working once a paid quota runs out.

Or put them in `.streamlit/secrets.toml` (gitignored):

```toml
MISTRAL_API_KEY = "..."
OPENCODE_API_KEY = "sk-zen-..."
```

## Providers

Both providers sit behind one interface in [`sage/providers.py`](sage/providers.py) and
normalise onto the same streaming chunk, so nothing downstream knows which is in use.

- **Mistral** — the official SDK.
- **OpenCode Zen** — the OpenAI-compatible endpoint at `https://opencode.ai/zen/v1`.
  Its model list is discovered from `GET /models` at runtime rather than hardcoded,
  because a free tier's lineup changes without notice; `SAGE_OPENCODE_MODELS` is only
  the fallback when discovery fails.

Not every free model can call tools. Those answer from a **single retrieval pass**
instead of the search/read loop: the question is searched up front and the matching
sections are put in the prompt, so answers stay grounded and still get a Sources
strip. List such models in `SAGE_TOOLLESS_MODELS`, or let the app detect it — a
provider that rejects a request because of tools is retried that way automatically.

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

It renders five screens (landing, answer, short answer, long chat, error) in both
colour schemes at five widths, in five states — the first frame, before
`static/app.js` has measured how much room the input bar needs; at rest; scrolled;
mid-generation; and just-finished, the last three with the real `static/app.js`
driving the page — 220 renders. It fails on clipping, content hidden behind the
input bar, horizontal overflow, unwanted wrapping, a control something else is
painted on top of, the gap between a question and its answer, dead space above the
input bar, or contrast below WCAG AA. CI runs it too.

It catches what reading the CSS does not. So far: the newest answer sitting 131px
underneath the chat input, the hero subtitle and all six starter cards wrapping to
two lines, a focus ring at 1.73:1 on the dark background, the question being
scrolled off the top of the screen while its answer streamed in, and the controls
under the input being painted over by Streamlit's own pinned bar.

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
  providers.py          # Mistral + OpenAI-compatible (OpenCode Zen) adapters
  llm.py                # turn assembly, streaming, typed errors
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
