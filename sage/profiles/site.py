"""The personal-website assistant — answers about Y. Yu's blog posts.

The corpus is a synced snapshot of https://youzhi.netlify.app/ under `site/`,
written by `tools/build_site_corpus.py` from a checkout of the website repo. Each
file is markdown carrying the page's real permalink in a short header and pandoc's
own `{#anchor}` on every heading, so a citation deep-links to the exact section a
reader can scroll to. Permalinks are read out of Hugo's build output rather than
recomputed from the slug rule, because a guess at someone else's slugifier is a
dead link that nothing checks.

Two deliberate differences from the RCC profile:

- **Third person.** The assistant talks *about* the author rather than *as* them.
  Answering "are you available for consulting?" in the first person puts words in
  a real person's mouth, and no phrasing of the prompt makes that safe.
- **Strict grounding, stated plainly.** The site has no tags and no search, so the
  failure mode that matters is a confident answer about a post that does not exist.
"""

from __future__ import annotations

from .. import config
from ..profile import POST, Profile, Source


def url_for(source: str, rel_path: str, anchor: str = "") -> str:
    # Every synced post carries its permalink in its own header, so this is only
    # the fallback for a file that somehow lost it.
    return config.SITE_BASE_URL


SYSTEM_PROMPT = """You are the assistant for Y. Yu's personal website — a \
data-science and machine-learning blog with over a hundred articles. You answer \
questions about what is on the site, and you answer strictly from it, using two \
tools:

- search_docs(query): find relevant sections of the articles
- read_doc(path): read one section in full, using an exact `path` from a search result

WORKFLOW
1. Call search_docs first, with focused keywords from the question.
2. Read the most promising result with read_doc before answering. Read more than one
   when a question spans articles (for example a model's pretraining *and* its
   reasoning fine-tune).
3. If the first search misses, rephrase the keywords and search again — the corpus
   spans 2021 to 2026 and the vocabulary changed a lot over that time.
4. Answer only from what you retrieved.

VOICE
- Write about the author in the third person: "Y. Yu trained…", never "I trained…".
  You are not the author and must not speak as him.
- Accessible but formal, matching the articles themselves. Define terms in plain
  language; avoid colloquialisms and exclamation marks.

CITATIONS
- Link every article you relied on as [Section title](path), using the exact `path`
  string from the search result. Those paths are turned into real URLs for the reader.
- Cite inline, where the claim is. Never close with a "Sources", "References" or
  "Citations" list: the app prints the sections you retrieved underneath your answer,
  so a list of your own lands directly above an identical one.
- Give the article's date when it matters. Methods from a 2021 post are not
  necessarily what the author would do today, and several topics were revisited.
- Quote figures, model sizes and measurements exactly as the article gives them.
  Never estimate, round or interpolate a number that is not written down.

WHEN THE SITE DOES NOT COVER IT
Say so in one sentence and suggest the closest article that does exist, or point the
reader at the contact links in the sidebar. Never invent an article, a title, a date,
a result or a number. "That is not something the site covers" is a good answer.

STYLE
- Lead with the answer, then the detail. Keep it short and conversational.
- Use ## or ### for headings, never #.
- Put code in fenced blocks with a language tag (```r, ```python, ```bash).
- You cannot browse the live web, run code, or see anything the reader is doing.
  Say so if you are asked to.

TOPICS: language-model pretraining and fine-tuning, reasoning models, HPC and GPU
training, R and the tidyverse, data visualisation, TidyTuesday analyses, statistics,
and the author's background and research interests."""


PROFILE = Profile(
    key="site",
    sources=(
        Source("post", f"{config.SITE_PATH}/post", (".md",), POST, weight=1.0),
        # The About page and `site_notes/`. Weighted above the articles because
        # "who is this?" and "how do I get in touch?" are asked constantly and are
        # answered badly by prose written for another purpose.
        Source("page", f"{config.SITE_PATH}/page", (".md",), POST, weight=1.25),
    ),
    url_for=url_for,
    home_url=config.SITE_BASE_URL,
    synonyms=(
        ("pretraining", "pretrain", "scratch", "base"),
        ("finetune", "finetuning", "sft", "instruction", "posttraining"),
        ("reasoning", "think", "thinking", "chain", "cot"),
        ("argonne", "model", "llm"),
        ("token", "tokenizer", "tokenization", "vocabulary", "bpe"),
        ("parameter", "size", "billion", "million", "scale"),
        ("gpu", "cuda", "a100", "h100", "node", "cluster"),
        ("dataset", "corpus", "data", "training"),
        ("visualization", "visualisation", "plot", "chart", "figure", "ggplot"),
        ("tidyverse", "dplyr", "tidyr", "purrr", "r"),
        ("tidytuesday", "tidy"),
        ("regression", "model", "fit", "lasso", "glm"),
        ("classification", "classifier", "logistic", "svm"),
        ("cluster", "clustering", "kmeans", "pca"),
        ("slurm", "hpc", "job", "scheduler"),
        # "about" is deliberately absent: it is a preposition in most questions
        # ("posts about penguins"), and expanding it to the author vocabulary put
        # the biography page — whose title matches, at TITLE_BOOST — on top of
        # every topical query on the site.
        ("author", "yu", "youzhi", "biography", "bio"),
        ("contact", "email", "reach", "touch", "hire", "consulting", "message"),
        # No ("article", "post", "blog", …) group: those words appear in almost
        # every question a reader asks *about* the site, so expanding them made
        # the meta-page outrank the articles for "which posts are about penguins".
    ),
    protected_terms=frozenset(
        {
            "ggplot",
            "dplyr",
            "tidyr",
            "purrr",
            "knitr",
            "https",
            "cuda",
            "slurm",
            "lasso",
            "keras",
        }
    ),
    system_prompt=SYSTEM_PROMPT,
    corpus_description="Y. Yu's blog articles",
    search_description=(
        "Search Y. Yu's blog articles for sections relevant to the reader's "
        "question. Returns ranked results, each with a `path`, an article and "
        "section title, and a snippet. Call this FIRST for any question about the "
        "site's writing, the author's projects and models, or the methods and data "
        "used in an analysis, then read the most promising result with read_doc."
    ),
    read_description=(
        "Read one section of an article in full. Pass the exact `path` from a "
        "search_docs result (for example "
        "'post/2026-07-23-pretraining-argonne.md#what-pretraining-from-scratch-entails'). "
        "Dropping the '#section' part returns the whole article, or its outline if "
        "the article is very long."
    ),
    no_results=(
        "No matching article was found on the site. Try different or broader "
        "keywords. If the topic genuinely is not written about here, say so plainly "
        "rather than guessing — suggest the closest article that does exist, or "
        "point the reader at the contact links in the sidebar."
    ),
    grounding_instruction=(
        "Answer only from these sections of Y. Yu's articles. Write about the author "
        "in the third person. Cite them inline as [Title](path) using the exact path "
        "in each header, and do not end with a Sources list — one is printed for you. "
        "If they do not cover the question, say so."
    ),
    searching_noun="the articles",
    page_title="Ask about Y. Yu's writing",
    page_icon="💬",
    welcome_title="Ask about anything I've written",
    # Kept short enough to sit on one line down to 500px: tools/render_check.py
    # measures it, and the first draft wrapped from 966px down.
    welcome_subtitle="Answers drawn from the articles on this site, with citations.",
    index_spinner="Indexing the articles…",
    # Labels stay under ~26 characters so each card is one line at every width the
    # layout check renders; the questions behind them stay conversational.
    examples=(
        ("🧠", "Pretraining from scratch",
         "How were the Argonne language models pretrained from scratch?"),
        ("💭", "Making a model reason",
         "How was a small language model taught to reason?"),
        ("📊", "ggplot2 techniques",
         "What ggplot2 techniques show up most often in these analyses?"),
        ("⚡", "The HPC tools",
         "What are rapiDU and slurmwatch, and what problems do they solve?"),
        ("📚", "Where to start with R",
         "Which articles are the best introduction to the tidyverse?"),
        ("👤", "About the author",
         "Who writes this site and what do they work on?"),
    ),
    # The site is Inter on white with a blue accent (`--link-color: #2563eb` in the
    # website's own custom.css); Sage's maroon is UChicago RCC's identity and would
    # look borrowed here. These override static/app.css.
    brand={
        "--brand": "#2563eb",
        "--brand-deep": "#1d4ed8",
        "--gradient": "linear-gradient(135deg, #2563eb, #1d4ed8)",
        "--gradient-text-start": "#2563eb",
        "--gradient-text-end": "#1d4ed8",
        "--brand-text": "#1d4ed8",
        "--brand-line": "#2563eb",
        "--card-bg-hover": "linear-gradient(145deg, #eff6ff 0%, #dbeafe 100%)",
        "--card-border-hover": "#93c5fd",
        "--code-inline-bg": "rgba(37, 99, 235, 0.1)",
        "--code-inline-fg": "#1d4ed8",
    },
    # A #2563eb-family blue on a near-black page is unreadable for the same reason
    # maroon is — #1d4ed8 inline code measured 2.62:1. These are the lighter tints
    # that keep the accent recognisable at AA, mirroring what app.css already does
    # for maroon.
    brand_dark={
        "--gradient-text-start": "#bfd7fe",
        "--gradient-text-end": "#93b8fc",
        "--brand-text": "#bfd7fe",
        "--brand-line": "#93b8fc",
        "--card-bg-hover": (
            "linear-gradient(145deg, rgba(37, 99, 235, 0.32) 0%, "
            "rgba(29, 78, 216, 0.32) 100%)"
        ),
        "--card-border-hover": "rgba(147, 184, 252, 0.7)",
        "--code-inline-bg": "rgba(191, 215, 254, 0.14)",
        "--code-inline-fg": "#bfd7fe",
    },
)
