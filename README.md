# 🌱 Sage — RCC User Guide Assistant

A grounded, citation-first chat assistant. It ships as two deployments from one
codebase: the University of Chicago [Research Computing Center](https://rcc.uchicago.edu/)
User Guide assistant, and an assistant for a personal blog. This README leads with
the first; see [Two assistants, one codebase](#two-assistants-one-codebase).

The RCC assistant answers questions for the [Research Computing Center](https://rcc.uchicago.edu/). Ask about accounts, SSH, Slurm jobs, storage and software; every answer is retrieved from the **official RCC User Guide** and website, and links the sections it used.

Built with [Streamlit](https://streamlit.io/), answered by [Mistral](https://mistral.ai/) or the free models on [OpenCode Zen](https://opencode.ai/docs/zen/). **Read-only and RAG-only** — it reads documentation and never touches the cluster.

## Features

- 🔀 **Model picker** — the button in the corner of the composer switches model mid-conversation. A spent quota fails over on its own.
- 🔎 **Grounded answers** — no invented commands, partitions or quotas.
- 🔗 **Real citations** — a Sources strip deep-links to the exact section, plus Related sections from the same page.
- 💬 **Streaming replies** with memory for follow-ups.
- 📎 **Attachments** — several at once. A PDF, an image pasted straight from the clipboard, or anything that reads as text: a job script, the `.out` it wrote, a config, source. Judged on the bytes, not the extension.
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

## Two assistants, one codebase

Sage runs against more than one corpus. `SAGE_PROFILE` picks which:

| Profile | Corpus | What it answers |
|---|---|---|
| `rcc` *(default)* | `docs/` + `web/` — the RCC User Guide and website | HPC, Slurm, storage, software |
| `site` | `site/` — a synced snapshot of [youzhi.netlify.app](https://youzhi.netlify.app/) | the blog: its articles, methods and author |

```bash
SAGE_PROFILE=site streamlit run app.py
```

A [`Profile`](sage/profile.py) carries everything that differs — source trees and
their weights, the URL rule for citations, the search synonyms, the system prompt,
the tool descriptions, the starter cards and a brand palette. Nothing else in the
package names a particular deployment, so a third corpus is one file in
[`sage/profiles/`](sage/profiles/) rather than an edit to nine.

### Refreshing the website corpus

`site/` is committed, for the same reason `docs/` and `web/` are: a Streamlit
deployment has no checkout of the website to read from.

```bash
python tools/build_site_corpus.py --site ../personal-website
```

It converts each rendered article to markdown, keeping **pandoc's own heading ids**
so a citation deep-links to the section a reader can actually scroll to, and records
the permalink Hugo published. The slug rule is verified against the site's own
`public/sitemap.xml` on every run rather than trusted — an earlier version stripped
the dots from `2021-09-27-u.s.-prison-analysis` and produced a dead link that nothing
would have noticed. Articles newer than the committed `public/` build are reported as
unverified; `--strict` makes that fatal.

Hand-written ground truth about the author lives in [`site_notes/`](site_notes/) and
is indexed alongside the articles. It is in this repo rather than the website's so
that adding the assistant changes nothing about how the site is built.

### Deploying the website assistant

The app is one Streamlit script, so the second deployment is the same repo with one
setting changed. On [Streamlit Community Cloud](https://share.streamlit.io/):

1. **New app** → this repo, branch of your choice, main file `app.py`.
2. **Advanced settings → Secrets** — this is where the keys go. They are never
   committed, and `app.py` reads `st.secrets` when the environment has nothing:

   ```toml
   MISTRAL_API_KEY = "..."
   OPENCODE_API_KEY = "sk-zen-..."   # optional; free tier, and the failover target

   SAGE_PROFILE = "site"
   ```

   One key is enough. With both, the model picker offers both and a spent quota
   fails over on its own instead of ending the conversation.
3. Deploy. The corpus is committed, so there is nothing to fetch at boot: the index
   builds from `site/` in a few seconds and is cached for the life of the process.

Both deployments can run at once from the same repo and branch — they differ only by
`SAGE_PROFILE`, so the RCC app keeps working unchanged while the website one runs
beside it.

Two things worth knowing before pointing readers at it:

- **Community Cloud apps sleep after about 12 hours without traffic**, and a sleeping
  app shows an interstitial before it will answer. That is survivable for a link
  people click deliberately; it is the reason this is not yet embedded in the site.
- `SAGE_MAX_TOKENS` defaults to 8000, which is sized for long HPC walkthroughs. Blog
  answers want far less — set it to about 1500 in the site deployment's secrets.

## Providers

Both sit behind one interface in [`sage/providers.py`](sage/providers.py) and normalise onto the same streaming chunk, so nothing downstream knows which is in use.

- **Mistral** — the official SDK.
- **OpenCode Zen** — the OpenAI-compatible endpoint at `https://opencode.ai/zen/v1`. Its model list comes from `GET /models` at runtime, because a free tier's lineup changes without notice; `SAGE_OPENCODE_MODELS` is only the fallback. Zen serves its paid lineup from the same endpoint, so the picker keeps only the free ones — matched by naming convention (`-free`, plus stealth codenames) rather than a hardcoded list, since the lineup moves. `SAGE_ZEN_FREE_ONLY=0` shows everything, for a deployment with a balance.

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
| `SAGE_VISION_MODELS` | `pixtral,claude` | Substrings of models that can be shown an image |
| `SAGE_ZEN_FREE_ONLY` | `1` | Offer only Zen's free models. `0` for a paid balance |
| `SAGE_ZEN_FREE_MARKS` | `-free,big-pickle` | How a free Zen model is recognised |
| `SAGE_MAX_TOKENS` | `8000` | Response cap. Generous: 1600 cut answers off mid-sentence |
| `SAGE_TEMPERATURE` | `0.2` | Sampling temperature |
| `SAGE_PROFILE` | `rcc` | Which assistant to be: `rcc` or `site` |
| `RCC_DOCS_PATH` | `./docs` | User Guide markdown source |
| `RCC_WEB_PATH` | `./web` | Scraped website text source |
| `SAGE_EXCLUDE_HOSTS` | radiology + vislab hosts | Scraped hosts to keep out of the index (`SAGE_EXCLUDE_HOSTS=` indexes everything) |
| `SAGE_EXCLUDE_FILES` | publication lists | Files to keep out of the index |
| `SAGE_SEARCH_RESULTS` | `6` | Results per search |
| `SAGE_SYNONYM_WEIGHT` | `0.8` | Weight of expanded synonym terms |
| `SAGE_HISTORY_CHAR_BUDGET` | `48000` | History size before oldest turns are trimmed |
| `SAGE_MAX_UPLOAD_BYTES` | `10485760` | Upload size limit, per file |
| `SAGE_MAX_ATTACHED_BYTES` | `20971520` | Upload size limit, across one turn |
| `SAGE_SITE_PATH` | `./site` | Website snapshot, for `SAGE_PROFILE=site` |
| `SAGE_SITE_BASE_URL` | `https://youzhi.netlify.app/` | Base URL for website citations |
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
app.py                  # Streamlit UI: layout, session state, event rendering
sage/
  engine.py             # the agent loop, as an event stream — no Streamlit
  profile.py            # what makes one deployment differ from another
  profiles/             # rcc.py, site.py — the instances
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
  sitehtml.py           # rendered blog HTML -> markdown, keeping pandoc anchors
static/app.css          # all styling
static/app.js           # DOM touch-ups Streamlit cannot express
tests/                  # unit tests, app smoke tests, retrieval eval
tools/render_check.py   # renders app.css in headless Chromium and measures it
tools/build_site_corpus.py  # personal website -> site/
refresh-docs.sh         # pull upstream docs -> docs/ + web/
docs/                   # RCC User Guide (markdown)
web/                    # scraped RCC website (text)
site/                   # website snapshot (markdown)  [SAGE_PROFILE=site]
site_notes/             # hand-written notes indexed with the website
docs_snapshot.json      # source commit + sync date
```
