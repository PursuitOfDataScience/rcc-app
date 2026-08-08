"""Golden-set retrieval eval for the `site` profile.

The RCC eval exists because every change to scoring, synonyms or chunking is
otherwise a guess; the site corpus deserves the same, and got it after two
synonym groups that seemed obviously helpful turned out to be actively harmful:

- `("article", "post", "blog", …)` — those words appear in nearly every question
  a reader asks *about* a blog, so expanding them made the biography page beat
  the articles for "which posts are about penguins".
- `"about"` inside the author group — it is a preposition, and with TITLE_BOOST
  on a page called "About this site and its author" it won every topical query
  on the site.

Neither was visible without cases to measure against. Add a case whenever a bad
answer turns up; a failure here means retrieval regressed, so fix the ranking
rather than loosening the case.
"""

import pytest

from sage import corpus as corpus_mod
from sage import profiles
from sage.search import Index

SITE = profiles.get("site")

# (question, paths any one of which is an acceptable hit)
CASES: list[tuple[str, tuple[str, ...]]] = [
    # --- the 2026 language-model and tooling articles ---
    ("how were the Argonne models pretrained from scratch",
     ("2026-07-23-pretraining-argonne/pretraining-argonne.md",)),
    ("what happened with Argonne 2.0",
     ("2026-07-23-pretraining-argonne/pretraining-argonne.md",)),
    ("how was a small language model taught to reason",
     ("2026-07-21-reasoning-model/reasoning-model.md",
      "2026-08-05-argonne35-think/argonne35-think.md")),
    ("what is rapiDU", ("2026-08-04-rapidu/rapidu.md",)),
    ("a faster alternative to du", ("2026-08-04-rapidu/rapidu.md",)),
    ("live telemetry for slurm jobs", ("2026-08-03-slurmwatch/slurmwatch.md",)),
    ("what is slurmwatch", ("2026-08-03-slurmwatch/slurmwatch.md",)),
    ("argonne 3.5 base model",
     ("2026-08-05-argonne35-base/argonne35-base.md",)),
    ("chain of thought fine tuning",
     ("2026-08-05-argonne35-think/argonne35-think.md",
      "2026-07-21-reasoning-model/reasoning-model.md")),
    # --- the R archive, by subject ---
    ("penguin data analysis", ("2022-01-23-penguins/penguins.md",
                               "2022-03-28-penguins/penguins.md")),
    ("ramen ratings", ("2021-08-17-ramen-ratings/ramen.md",
                       "2021-11-09-ramen/ramen.md")),
    ("netflix shows", ("2022-03-26-netflix/netflix.md",)),
    ("the simpsons", ("2021-11-22-the-simpsons/simpsons.md",)),
    ("water potability", ("2021-08-13-water-quality/water-quality.md",)),
    ("nobel prize winners", ("2021-10-31-nobel-prize-winners/nobel.md",)),
    ("bob ross paintings", ("2021-11-18-bob-ross/bob-ross.md",)),
    ("nyc squirrels", ("2021-12-02-squirrels/nyc-squirrels.md",)),
    ("himalayan climbing expeditions", ("2022-02-15-climbing/climbing.md",)),
    ("big mac price index", ("2022-03-02-big-mac/big-mac.md",)),
    ("deforestation", ("2022-03-23-forest/forest.md",)),
    ("beyonce and taylor swift lyrics",
     ("2022-02-19-taylor-beyonce/taylor-beyonce.md",)),
    ("bechdel test", ("2022-03-18-bechdel/bechdel.md",)),
    ("kenya census map", ("2022-03-08-kenya-census/kenya.md",)),
    ("broadband access", ("2022-04-04-broadband/broadband.md",)),
    ("tour de france", ("2021-12-13-tour-de-france/tour-de-france.md",)),
    # --- the R archive, by method ---
    ("random forest", ("2022-05-05-nfl/nfl.md", "2022-05-11-sf-trees/sf-trees.md",
                       "2022-05-07-food-aisa/food-asia.md",
                       "2022-05-08-total-minority/total-minority.md")),
    ("k nearest neighbours and decision trees", ("2022-05-06-hotels/hotels.md",)),
    ("principal component analysis on cocktails",
     ("2022-05-25-cocktail/cocktail.md", "2022-01-10-cocktails/cocktails.md")),
    ("survival analysis", ("2021-09-17-dolphins/dolphin-analysis.md",
                           "2021-09-20-golden-tv/tv-analysis.md",
                           "2021-12-13-tour-de-france/tour-de-france.md")),
    ("changepoint detection", ("2021-08-21-fb-stock/facebook-stock.md",)),
    ("hypergeometric test", ("2021-10-16-seattle-pets/seattle-pets.md",)),
    ("web scraping", ("2021-11-08-asa/asa-fellows.md",)),
    ("structural topic modeling",
     ("2021-12-22-animal-crossing/animal-crossing.md",)),
    ("using purrr with broom", ("2022-01-14-purrr-broom/purrr-broom.md",)),
    ("time series forecasting", ("2021-09-30-u.s.-dairy/us-dairy.md",)),
    ("lesser known tidyverse functions",
     ("2021-08-15-useful-tidyverse-functions/tidyverse_fun_on_rice.md",)),
    ("summarize versus summarise",
     ("2021-08-09-summarize-vs-summarize/summarize-vs-summarise.md",)),
    ("bootstrap resampling", ("2022-03-28-penguins/penguins.md",
                              "2021-10-25-chicago-birds/chicago-birds.md",
                              "2022-06-01-animal-crossing/animal-crossing.md")),
    # --- the site itself ---
    ("who writes this site", ("about-this-site.md", "about.md")),
    ("how do I get in touch with the author", ("about-this-site.md",)),
    ("what are the author's research interests",
     ("about-this-site.md", "about.md")),
]

RECALL_AT = 5
MINIMUM_RECALL_AT_5 = 0.90
MINIMUM_RECALL_AT_3 = 0.85
MINIMUM_PRECISION_AT_1 = 0.65


@pytest.fixture(scope="session")
def site_index():
    built = corpus_mod.build(profile=SITE)
    if not built.chunks:
        pytest.skip("no site/ corpus; run tools/build_site_corpus.py")
    return Index(built)


def pages(index, question: str, limit: int) -> set[str]:
    return {
        result.chunk.path for result in index.search(question, limit=limit)
    }


def hit(index, question: str, expected: tuple[str, ...], limit: int) -> bool:
    return bool(set(expected) & pages(index, question, limit))


@pytest.mark.parametrize(
    ("question", "expected"), CASES, ids=[case[0] for case in CASES]
)
def test_each_question_finds_its_article(site_index, question, expected):
    found = pages(site_index, question, RECALL_AT)
    assert set(expected) & found, f"wanted one of {expected}, got {sorted(found)}"


def test_recall_at_5(site_index):
    score = sum(hit(site_index, q, e, 5) for q, e in CASES) / len(CASES)
    assert score >= MINIMUM_RECALL_AT_5, f"recall@5 fell to {score:.0%}"


def test_recall_at_3(site_index):
    score = sum(hit(site_index, q, e, 3) for q, e in CASES) / len(CASES)
    assert score >= MINIMUM_RECALL_AT_3, f"recall@3 fell to {score:.0%}"


def test_precision_at_1(site_index):
    """Matters most: the model usually reads the first result."""
    score = sum(hit(site_index, q, e, 1) for q, e in CASES) / len(CASES)
    assert score >= MINIMUM_PRECISION_AT_1, f"precision@1 fell to {score:.0%}"


def test_the_biography_does_not_outrank_the_articles(site_index):
    """The regression that motivated this file. `site_notes/` is weighted above the
    posts so that "who is this?" works; that must not make it the answer to
    everything else."""
    for question in ("penguin data analysis", "netflix shows", "random forest",
                     "deforestation", "what is rapiDU"):
        top = site_index.search(question, limit=1)
        assert top, question
        assert top[0].chunk.source == "post", (
            f"{question!r} was answered by {top[0].chunk.path}"
        )


def test_every_citation_points_at_an_anchor_the_page_really_has(site_index):
    """A dead citation is the one failure this corpus cannot afford.

    The anchors are pandoc's own, carried through the sync as `{#id}`, so the
    check is that every URL fragment is one of the ids written in the file — not
    something `slugify` invented from the heading text. A section too long for one
    chunk yields several chunks sharing the page's single anchor, which is why the
    chunk id (`…#data-visualization-1`) and the URL fragment
    (`#data-visualization`) are allowed to differ.
    """
    import re
    from pathlib import Path

    from sage import config

    root = Path(config.SITE_PATH)
    declared: dict[str, set[str]] = {}
    for chunk in site_index.corpus.chunks:
        key = f"{chunk.source}/{chunk.path}"
        if key not in declared:
            body = (root / chunk.source / chunk.path).read_text(encoding="utf-8")
            declared[key] = set(re.findall(r"\{#([^}\s]+)\}", body))

        assert chunk.url.startswith("https://"), chunk.id
        _, _, fragment = chunk.url.partition("#")
        if not fragment:
            continue
        assert fragment in declared[key], (
            f"{chunk.id} cites #{fragment}, which {chunk.path} does not declare"
        )

    anchored = sum(
        1 for chunk in site_index.corpus.chunks if "#" in chunk.url
    )
    assert anchored > 200, f"only {anchored} deep-linked chunks — corpus looks wrong"


def test_every_advertised_path_can_be_read_back(site_index):
    from sage.tools import READ_DOC, ToolRunner

    runner = ToolRunner(site_index)
    for question, _expected in CASES[:15]:
        for result in site_index.search(question, limit=3):
            out = runner.run(READ_DOC, {"path": result.id})
            assert not out.startswith("Error:"), f"{result.id} -> {out[:80]}"
