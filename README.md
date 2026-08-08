# 🌱 Sage — RCC User Guide Assistant

A chat assistant for the University of Chicago's [Research Computing Center](https://rcc.uchicago.edu/). Ask about accounts, SSH, Slurm jobs, storage and software; every answer is retrieved from the **official RCC User Guide** and website, and links the sections it used.

Built with [Streamlit](https://streamlit.io/), answered by [Mistral](https://mistral.ai/) or the free models on [OpenCode Zen](https://opencode.ai/docs/zen/). **Read-only and RAG-only** — it reads documentation and never touches the cluster.

## Features

- 🔀 **Model picker** — the button in the corner of the composer switches model mid-conversation, and sets answer style (Concise / Explanatory). A spent quota fails over on its own.
- 🔎 **Grounded answers** — no invented commands, partitions or quotas. Retrieval reports when it has *not* found anything, so "the documentation does not cover this" is a reachable answer rather than six weak matches formatted like six good ones.
- 🔗 **Real citations** — a Sources strip deep-links to the exact section, plus Related sections from the same page. A citation that cannot be resolved is left unlinked rather than pointed at the guide's front page.
- 🧭 **"I can't see your account" is a route, not a dead end** — the docs record a command for nearly every piece of state Sage cannot see, so it hands you `rcchelp quota` or `squeue --user=…` and offers to read the output you paste back.
- 🪧 **Says what it did** — a collapsed trace of what was searched and read, including the searches that missed; suggested follow-up questions drawn from real sibling sections; and a visible marker when a long conversation stops being sent to the model in full.
- 💬 **Streaming replies** with memory for follow-ups.
- ⭳ **Export** — download the conversation as Markdown with citations resolved and the docs snapshot stamped, or open a pre-drafted Help Desk mail carrying the question and the searches already tried.
- 📎 **Attachments** — several at once. A PDF, an image pasted straight from the clipboard, or anything that reads as text: a job script, the `.out` it wrote, a config, source. Judged on the bytes, not the extension.
- 🗂️ **Self-updating docs** — one command refreshes the bundled guide.
- ♿ **Light and dark themes**, keyboard focus, reduced motion, forced-colors, print stylesheet, live regions for screen readers, and 24×24 pointer targets.
- 🔒 **Nothing is logged in the clear** — credentials and identifiers (CNetIDs, home and project paths, emails, IPs) are replaced with placeholders before anything is written or exported, and a record whose scrub leaves a credential shape behind is dropped rather than stored.

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
- **OpenCode Zen** — the OpenAI-compatible endpoint at `https://opencode.ai/zen/v1`. Its model list comes from `GET /models` at runtime, because a free tier's lineup changes without notice; `SAGE_OPENCODE_MODELS` is only the fallback. Zen serves its paid lineup from the same endpoint, so the picker keeps only the free ones — matched by naming convention (`-free`, plus stealth codenames) rather than a hardcoded list, since the lineup moves. `SAGE_ZEN_FREE_ONLY=0` shows everything, for a deployment with a balance.

Models that cannot call tools answer from a **single retrieval pass** instead of the search/read loop — searched up front, matching sections in the prompt, still cited. Set `SAGE_TOOLLESS_MODELS`, or let the app detect it: a provider that rejects tools is retried that way.

## How it works

The model gets two tools: `search_docs(query)`, BM25 with IDF, length normalization, a title/path boost and RCC-specific synonym expansion (so "my job got killed" reaches the OOM docs); and `read_doc(path)`, one section in full.

Retrieval is measured, not assumed. [`tests/test_retrieval_eval.py`](tests/test_retrieval_eval.py) is a golden set of real questions paired with the pages that should answer them, with ratcheted floors that may be raised and never lowered: **recall@3 100%, recall@5 100%, precision@1 79%, MRR 0.889** over 34 cases, on 572 chunks from 115 pages. Stemming covers verb inflections as well as plurals (`preempted` → `preempt`, so the synonym group written for it can fire); a query stoplist keeps "how do I install" from scoring on its own; no single page may take more than `SAGE_MAX_PER_PAGE` of a result set; and `Index.assess` reports the top score, the margin and any query word absent from the whole corpus. That last one is the useful signal — a question about software the guide never mentions is unanswerable however well the remaining words match — and it is what makes an honest refusal possible. No percentages: BM25 scores are not comparable across queries, so a "confidence" figure would be theatre.

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
| `SAGE_VISION_MODELS` | `pixtral,claude` | Substrings of models that can be shown an image |
| `SAGE_ZEN_FREE_ONLY` | `1` | Offer only Zen's free models. `0` for a paid balance |
| `SAGE_ZEN_FREE_MARKS` | `-free,big-pickle` | How a free Zen model is recognised |
| `SAGE_MAX_TOKENS` | `8000` | Response cap. Generous: 1600 cut answers off mid-sentence |
| `SAGE_TEMPERATURE` | `0.2` | Sampling temperature |
| `RCC_DOCS_PATH` | `./docs` | User Guide markdown source |
| `RCC_WEB_PATH` | `./web` | Scraped website text source |
| `SAGE_EXCLUDE_HOSTS` | radiology + vislab hosts | Scraped hosts to keep out of the index (`SAGE_EXCLUDE_HOSTS=` indexes everything) |
| `SAGE_EXCLUDE_FILES` | publication lists | Files to keep out of the index |
| `SAGE_SEARCH_RESULTS` | `6` | Results per search |
| `SAGE_MAX_PER_PAGE` | `2` | Most sections one page may take of a result set |
| `SAGE_MIN_CONFIDENT_SCORE` | `12.0` | Below this, retrieval reports itself as weak |
| `SAGE_SYNONYM_WEIGHT` | `0.5` | Weight of expanded synonym terms |
| `SAGE_OUTLINE_BELOW_CHARS` | `1200` | Append a page outline only to sections shorter than this |
| `RCC_DOCS_ISSUE_URL` | user-guide issues | Where "the docs are missing this" files a pre-filled issue. Empty hides the button |
| `SAGE_HISTORY_CHAR_BUDGET` | `48000` | History size before oldest turns are trimmed |
| `SAGE_MAX_UPLOAD_BYTES` | `10485760` | Upload size limit, per file |
| `SAGE_MAX_ATTACHED_BYTES` | `20971520` | Upload size limit, across one turn |
| `SAGE_FEEDBACK_LOG` | *(unset)* | JSONL sink for ratings, retrieval misses and per-turn events. Unset = nothing recorded, but the 👍/👎 controls still render |
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
  feedback.py           # 👍/👎 with reasons, retrieval misses, per-turn events
  scrub.py              # redact credentials and identifiers before anything is stored
  export.py             # Markdown transcripts, help-desk drafts, docs-gap issues
static/app.css          # all styling
static/app.js           # DOM touch-ups Streamlit cannot express
tests/                  # unit tests, app smoke tests, retrieval eval
tools/render_check.py   # renders app.css in headless Chromium and measures it
refresh-docs.sh         # pull upstream docs -> docs/ + web/
docs/                   # RCC User Guide (markdown)
web/                    # scraped RCC website (text)
docs_snapshot.json      # source commit + sync date
```
