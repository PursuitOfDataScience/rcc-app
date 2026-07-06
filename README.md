# 🌱 Sage — RCC User Guide Assistant

A chat assistant for the University of Chicago's [Research Computing Center](https://rcc.uchicago.edu/). Ask about accounts, SSH, Slurm jobs, storage, and software — answers are retrieved from the **official RCC User Guide**, with citations.

Built with [Streamlit](https://streamlit.io/) and the [Mistral](https://mistral.ai/) API. **Read-only and RAG-only** — it reads documentation, never runs commands on the cluster.

## Features

- 🔎 **Grounded answers** — retrieves and cites real RCC docs; no hallucinated commands.
- 📎 **File uploads** — drop in a PDF or text file and ask about it.
- 💬 **Streaming replies** with conversation memory for follow-ups.
- 🗂️ **Self-updating docs** — a one-command refresh keeps the bundled guide current.

## Quickstart

```bash
pip install -r requirements.txt
export MISTRAL_API_KEY=sk-...
streamlit run app.py            # → http://localhost:8501
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `MISTRAL_API_KEY` | *(required)* | Mistral API key |
| `RCC_DOCS_PATH` | `./docs` | User Guide markdown source |
| `RCC_WEB_PATH` | `./web` | Scraped website text source |
| `LOG_LEVEL` | `WARNING` | Python log level |

## How it works

The model is given two tools — `search_docs(query)` to rank the documentation tree and `read_doc(path)` to read a page — so every file under `docs/` and `web/` is reachable, and answers stay tied to the source. Reads are confined to those directories.

## Keeping docs fresh

The bundled `docs/`/`web/` snapshot is refreshed from the upstream [`user-guide`](https://github.com/rcc-uchicago/user-guide) repo. Run from an internet-connected host:

```bash
./refresh-docs.sh            # sync docs + web, stamp docs_snapshot.json
./refresh-docs.sh --scrape   # also re-scrape the RCC website
```

## Layout

```
app.py             # the Streamlit app (UI + RAG loop)
refresh-docs.sh    # pull upstream docs → docs/ + web/
docs/              # RCC User Guide (markdown)
web/               # scraped RCC website (text)
docs_snapshot.json # source commit + sync date
```
