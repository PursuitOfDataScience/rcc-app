# 🌱 Sage — RCC User Guide Assistant

A chat assistant for the University of Chicago's [Research Computing Center](https://rcc.uchicago.edu/). Ask about accounts, SSH, Slurm jobs, storage and software; every answer is retrieved from the **official RCC User Guide** and website, and links the sections it used.

Built with [Streamlit](https://streamlit.io/), answered by [Mistral](https://mistral.ai/) or the free models on [OpenCode Zen](https://opencode.ai/docs/zen/). **Read-only and RAG-only** — it reads documentation and never touches the cluster.

## Features

- 🔀 **Model picker** — the button in the corner of the composer switches model mid-conversation. A spent quota fails over on its own.
- 🔎 **Grounded answers** — no invented commands, partitions or quotas.
- 🔗 **Real citations** — a Sources strip deep-links to the exact section, plus Related sections from the same page.
- 💬 **Streaming replies** with memory for follow-ups.
- 📎 **Attachments** — several at once, from the paperclip, dragged onto the page from anywhere, or pasted straight from the clipboard. A PDF, a screenshot, or anything that reads as text: a job script, the `.out` it wrote, a config, source. Judged on the bytes, not the extension.
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
- **OpenCode Zen** — the OpenAI-compatible endpoint at `https://opencode.ai/zen/v1`. Its model list comes from `GET /models` at runtime, because a free tier's lineup changes without notice; `SAGE_OPENCODE_MODELS` is only the fallback. Zen serves its paid lineup from the same endpoint, so the picker keeps only the free ones — matched by naming convention (`-free`, plus stealth codenames) rather than a hardcoded list, since the lineup moves. `SAGE_ZEN_FREE_ONLY=0` shows everything, for a deployment with a balance. The tier marker is part of the id sent upstream and of the filter that reads it, but not of the name in the picker: `Model.label` drops it as a whole segment, since it is billing plumbing rather than something to pick between models on.

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
| `SAGE_DEFAULT_MODEL` | `opencode:deepseek-v4-flash-free` | Model a fresh session starts on, `provider:model-id` |
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
| `SAGE_SYNONYM_WEIGHT` | `0.8` | Weight of expanded synonym terms |
| `SAGE_HISTORY_CHAR_BUDGET` | `48000` | History size before oldest turns are trimmed |
| `SAGE_MAX_UPLOAD_BYTES` | `10485760` | Upload size limit, per file |
| `SAGE_MAX_ATTACHED_BYTES` | `20971520` | Upload size limit, across one turn |
| `SAGE_FEEDBACK_LOG` | *(unset)* | JSONL sink for 👍/👎 and zero-result queries. Unset = nothing recorded |
| `SAGE_IMAGE_MAX_EDGE` | `1568` | Longest edge an image is downscaled to before it is sent |
| `LOG_LEVEL` | `WARNING` | Python log level |

Server settings live in [`.streamlit/config.toml`](.streamlit/config.toml). The theme is stated **twice**, under `[theme.light]` and `[theme.dark]`, so Streamlit keeps following the browser's colour scheme: setting any `[theme]` value at all makes the theme a custom one, whose `base` defaults to light, and `static/app.css` would then go dark on a dark-mode device while Streamlit painted a white page underneath it. `server.maxUploadSize` is deliberately larger than `SAGE_MAX_UPLOAD_BYTES` for a related reason — Streamlit renders its own "file is too large" inside the uploader widget, which this app hides, so the app has to be the one that refuses.

## Sharing a deployment

One key, one public URL, and a turn that costs up to `SAGE_MAX_TOOL_ROUNDS + 1` provider calls. A spent key does not make the app slower, it ends it for everyone until a human notices — so there are two limits, protecting two different things.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SAGE_RATE_BURST` | `5` | Questions one person may ask back-to-back before the sustained rate applies |
| `SAGE_RATE_REFILL_SECONDS` | `15` | One question back per this many seconds (≈4/min sustained, ≈20 per 5 min) |
| `SAGE_DAILY_TURNS` | `100` | Questions per person per day. A backstop against a loop, not a quota |
| `SAGE_CALL_BUDGET` | `0` (off) | **Provider calls for the whole deployment** per window. See below |
| `SAGE_BUDGET_WINDOW_SECONDS` | `86400` | The window the budget resets over |
| `SAGE_TOOL_RESULT_CHAR_BUDGET` | `60000` | Total tool output one turn may accumulate across all rounds |

Set any of them to `0` to switch that limit off.

**The per-person limits are a token bucket, not a fixed window**, because a window is worse at both ends: it lets someone spend a whole allowance at 11:59 and another at 12:00, and it refuses a legitimate quick follow-up that lands just inside a boundary. The defaults are invisible to normal use — an answer takes 20–60s to read, so sustained demand is well under the refill rate.

**`SAGE_CALL_BUDGET` is the one that protects the key, and it is off by default** only because the right number depends on a plan this repo cannot see. Set it from real spend: `daily budget ÷ measured cost per call`. Note it counts *calls*, not questions — one question is one to `MAX_TOOL_ROUNDS + 1` requests, so a limit counted in messages says nothing about what the key is charged. Until it is set, nothing bounds a day's spend.

Counters live in memory, shared across sessions in the one process Streamlit runs. They reset when the app restarts — which on a platform that hibernates idle apps is roughly daily. A deployment that needs the budget to survive a restart needs external storage.

### Requiring a login

Off unless configured, and the highest-leverage control here by some distance: it turns "anyone with the URL" into "people with an account you named".

| Variable | Default | Meaning |
| --- | --- | --- |
| `SAGE_REQUIRE_LOGIN` | `0` | Require a signed-in account |
| `SAGE_ALLOWED_EMAIL_DOMAINS` | *(empty = any)* | Comma-separated domains allowed past the gate |

Needs an OIDC provider in `.streamlit/secrets.toml` ([Streamlit's guide](https://docs.streamlit.io/develop/concepts/connections/authentication)):

```toml
[auth]
redirect_uri = "https://your-app.example/oauth2callback"
cookie_secret = "a long random string"
client_id = "…"
client_secret = "…"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

Then `SAGE_REQUIRE_LOGIN=1` and `SAGE_ALLOWED_EMAIL_DOMAINS=uchicago.edu`. **Leave the domain list empty and a Google client authenticates the entire internet**, so set it. Setting the flag *without* an `[auth]` block does not lock the app — it runs open and logs an error, because the alternative is a sign-in button that cannot work, locking out whoever set the flag.

Signing in also makes the limits enforceable rather than advisory: anonymous readers are keyed by session, and a new private window is a new session. Identity is never keyed on IP address — campus NAT and the VPN put hundreds of people behind one, so a per-IP cap either does nothing or locks out a whole building.

One consequence worth deciding on deliberately: with a login, the feedback log becomes attributable to named people, and readers paste job scripts into this app.

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
