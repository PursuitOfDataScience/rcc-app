# Profiles — pointing this app at your documentation

A profile is what makes this deployment the RCC one. Nothing in `sage/` names the
RCC; `rcc.toml` and `rcc.prompt.md` do, and they are the whole of it.

```bash
cp profiles/rcc.toml profiles/mine.toml
cp profiles/rcc.prompt.md profiles/mine.prompt.md
SAGE_PROFILE=profiles/mine.toml streamlit run app.py
```

If the file is missing or does not parse, the app runs with unbranded defaults and
says so in the log. That is deliberate: it is the proof that no subject is hiding in
the code.

## What goes in it

| Section | What it decides |
| --- | --- |
| `[assistant]` | The name, the icon, the page title, the subject the prompt introduces, the address given when the docs cannot answer, and who to tell when a key is rejected |
| `[copy]` | The welcome heading, the input placeholders, the sign-in screen |
| `[[examples]]` | The starter cards: an icon, a short label, and the question actually sent |
| `[prompt]` | `file = "…prompt.md"` beside the profile, or `system = """…"""` inline |
| `[[sources]]` | Each tree of documents: where it is, what to read it with, and how its URLs are built |
| `[retrieval]` | The engine, the terms the stemmer must not touch, and the synonym groups that bridge how users ask to how the docs answer |
| `[[providers]]` | Where models come from, in preference order |

Placeholders in a prompt — `{name}`, `{subject}`, `{topic}`, `{documentation}`,
`{contact}`, `{contact_label}` — are filled from `[assistant]`. Anything else is left
alone, so a `${SLURM_JOB_ID}` in your prompt survives.

## Sources

```toml
[[sources]]
name = "guide"          # the prefix in a citation path: guide/install.md#linux
path = "./guide"
path_env = "MY_DOCS_PATH"   # optional: an env var that overrides `path`
extensions = [".md"]
reader = "markdown"     # markdown | scraped  (sage/corpus/readers.py)
links = "mkdocs"        # mkdocs | direct | embedded | none  (sage/corpus/urls.py)
base_url = "https://docs.example.org/"
weight = 1.0            # scoring prior: >1 favours this tree on a tie
exclude_files = ["changelog.md"]
exclude_hosts = []      # scraped trees only, matched on the URL in the file
```

**Readers** turn a file into a document and its chunks. `markdown` cuts on headings,
so a citation can deep-link to a section; `scraped` windows a page that has no
headings, reading the source URL from a `URL:` line at the top of the file.

**Link schemes** decide where a citation points. `mkdocs` publishes `a/b.md` at
`a/b/` with the heading as an anchor (mkdocs' `use_directory_urls` default);
`direct` serves the path as it stands; `embedded` uses the URL inside the file;
`none` is for a corpus with no public URL — the answer still cites the section, it
just does not pretend to link it.

A format neither reader handles is a function and a `register` call:

```python
# myreader.py — imported before the corpus is built
from sage.corpus import readers

def read_rst(source, rel_path, raw):
    ...                      # -> (Document, [Chunk])

readers.register("rst", read_rst)
```

## Providers

```toml
[[providers]]
name = "local"
kind = "openai"                  # anything speaking /chat/completions
key_env = "LOCAL_API_KEY"
base_url = "http://127.0.0.1:8000/v1"
models = ["qwen3-30b"]           # fallback if GET /models fails
```

`kind = "openai"` covers Together, Groq, Fireworks, vLLM, llama.cpp and Ollama —
they differ only in a base URL and a key. `kind = "mistral"` uses that SDK. A
provider with its own protocol is one module and one `adapters.register(...)`.

Order is preference order: it decides which provider a fresh session starts on when
`SAGE_DEFAULT_MODEL` names nothing available, and which one an automatic failover
reaches for. A provider whose `key_env` is unset is skipped entirely.

`free_marks` / `free_only` are for an endpoint that serves a paid lineup alongside a
free one: only ids containing one of the marks are offered, so the picker cannot
offer a model there is no balance for.

## Retrieval

`engine = "bm25"` is what ships. `synonyms` is the piece that is genuinely about your
subject — users describe symptoms and documentation describes mechanisms, and which
words bridge that gap is not something a scorer can know. `protected` are terms the
stemmer must leave whole.

Another engine is a factory and a name:

```python
from sage.retrieval import engines
engines.register("embeddings", lambda corpus, retrieval, documentation="": MyIndex(...))
```

It needs `corpus`, `search(query, limit)` and `assess(query, results)`. Nothing else
in the app has to change.

## Checking a new profile

```bash
python -c "from sage import runtime; r = runtime.build(); print(r.summary())"
python tools/metrics.py          # retrieval quality against tests/test_retrieval_eval.py
python tools/anchor_check.py     # every citation anchor resolves on the live site
```
