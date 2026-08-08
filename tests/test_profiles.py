"""Profiles, and the HTML→markdown sync that feeds the `site` one.

The point of `sage/profile.py` is that pointing Sage at a different corpus stopped
being a nine-file edit that nothing checked. These tests are the "nothing checked"
half: they assert the two profiles really are independent, and that the corpus
built for one is not analysed, described or linked with the other's values.
"""

import pytest

from sage import corpus as corpus_mod
from sage import profiles, search, sitehtml, tools
from sage.profile import MARKDOWN, POST, SCRAPED, Profile, Source


class TestRegistry:
    def test_the_default_is_the_assistant_this_repo_already_shipped(self, monkeypatch):
        monkeypatch.delenv("SAGE_PROFILE", raising=False)
        assert profiles.active().key == "rcc"

    def test_the_environment_selects_a_profile(self, monkeypatch):
        monkeypatch.setenv("SAGE_PROFILE", "site")
        assert profiles.active().key == "site"

    def test_case_and_whitespace_do_not_matter(self, monkeypatch):
        monkeypatch.setenv("SAGE_PROFILE", "  SITE  ")
        assert profiles.active().key == "site"

    def test_a_typo_falls_back_loudly_rather_than_serving_the_wrong_assistant(
        self, monkeypatch
    ):
        """Silently ignoring it would deploy the RCC prompt against the blog and
        look like a prompt bug rather than a config one."""
        monkeypatch.setenv("SAGE_PROFILE", "blogg")
        assert profiles.active().key == "rcc"

    @pytest.mark.parametrize("key", ["rcc", "site"])
    def test_every_profile_is_fully_populated(self, key):
        """A missing prompt or tool description is not a crash — it is an
        assistant that quietly stops explaining itself to the model."""
        profile = profiles.get(key)
        assert profile.sources
        assert profile.system_prompt.strip()
        assert profile.search_description.strip()
        assert profile.read_description.strip()
        assert profile.no_results.strip()
        assert profile.grounding_instruction.strip()
        assert profile.examples
        assert all(len(example) == 3 for example in profile.examples)
        assert profile.home_url.startswith("http")


class TestIsolation:
    def test_the_two_profiles_share_no_vocabulary_by_accident(self):
        rcc = search.for_profile(profiles.get("rcc"))
        site = search.for_profile(profiles.get("site"))
        assert "preemptible" in rcc.expand_query("scavenge")
        assert "preemptible" not in site.expand_query("scavenge")
        assert "tokenizer" in site.expand_query("token")
        assert "tokenizer" not in rcc.expand_query("token")

    def test_about_is_not_expanded_by_the_site_profile(self):
        """It is a preposition in "posts about penguins", and expanding it to the
        author vocabulary put the biography above every topical query."""
        site = search.for_profile(profiles.get("site"))
        assert set(site.expand_query("about")) == {"about"}

    def test_the_model_is_told_which_corpus_it_is_searching(self):
        rcc, site = (
            tools.tool_schemas(profiles.get(key))[0]["function"]["description"]
            for key in ("rcc", "site")
        )
        assert "RCC" in rcc
        assert "RCC" not in site

    def test_a_corpus_carries_its_profile_to_the_index_and_the_runner(self):
        profile = profiles.get("site")
        corpus = corpus_mod.Corpus(chunks=[], documents={}, profile=profile)
        assert search.Index(corpus).corpus.profile is profile
        assert tools.ToolRunner(search.Index(corpus)).profile is profile

    def test_source_weights_come_from_the_profile(self):
        profile = profiles.get("rcc")
        assert profile.weight("docs") > profile.weight("web")
        assert profile.weight("nonexistent") == 1.0

    def test_brand_css_is_only_emitted_when_a_profile_has_one(self):
        assert profiles.get("rcc").brand_css == ""
        css = profiles.get("site").brand_css
        assert css.startswith(":root {") and "--brand: #2563eb;" in css

    def test_a_brand_that_overrides_a_colour_overrides_it_in_both_schemes(self):
        """A single unconditional `:root` block also beats the stylesheet's own
        dark-mode values. The first site palette did exactly that and put #1d4ed8
        inline code on a near-black page at 2.62:1."""
        for key in profiles.PROFILES:
            profile = profiles.get(key)
            if not profile.brand:
                continue
            css = profile.brand_css
            assert "@media (prefers-color-scheme: dark)" in css, key
            recoloured = {
                name for name in profile.brand
                if name.endswith(("-text", "-line", "-fg", "-start", "-end"))
            }
            missing = recoloured - set(profile.brand_dark)
            assert not missing, f"{key} recolours {sorted(missing)} in light only"


class TestCopyFits:
    """Cheap guards for what `tools/render_check.py` measures properly.

    The layout check takes four minutes and needs Chromium; these take
    milliseconds and catch the two mistakes that were actually made. They do not
    replace it — a label can fit the limit and still wrap at a width nothing here
    models — so the real check still runs in CI.
    """

    # The longest RCC label ("Set up a Python environment") is 27 characters and
    # renders on one line down to 500px. The first site labels were 32 and 33 and
    # wrapped from 966px down.
    MAX_LABEL = 27
    MAX_SUBTITLE = 70

    @pytest.mark.parametrize("key", ["rcc", "site"])
    def test_starter_card_labels_stay_on_one_line(self, key):
        for _icon, label, _question in profiles.get(key).examples:
            assert len(label) <= self.MAX_LABEL, f"{key}: {label!r} is {len(label)}"

    @pytest.mark.parametrize("key", ["rcc", "site"])
    def test_the_welcome_subtitle_stays_on_one_line(self, key):
        subtitle = " ".join(profiles.get(key).welcome_subtitle.split())
        assert len(subtitle) <= self.MAX_SUBTITLE, f"{key}: {len(subtitle)} chars"

    @pytest.mark.parametrize("key", ["rcc", "site"])
    def test_the_question_behind_a_card_is_a_real_question(self, key):
        for _icon, label, question in profiles.get(key).examples:
            assert question.endswith("?"), f"{key}: {label!r} sends {question!r}"


class TestPostChunking:
    POST_FILE = """URL: https://example.test/post/a-post/a-post/
Title: A Post About Things
Date: 2026-01-02
---

Some opening prose that is comfortably long enough to survive the minimum chunk
filter without any trouble at all, and then a second sentence so that the intro
chunk is exercised rather than silently dropped for being too short.

## First section {#first-section-id}

Body of the first section, also long enough to be indexed on its own merits.

## Second section {#second-section-id}

Body of the second section, likewise long enough to be kept by the chunker.
"""

    def build(self):
        return corpus_mod.chunk_post(
            "post", "a-post/a-post.md", self.POST_FILE, profiles.get("site")
        )

    def test_the_header_supplies_the_real_permalink(self):
        document, _chunks = self.build()
        assert document.url == "https://example.test/post/a-post/a-post/"

    def test_the_front_matter_title_beats_the_first_heading(self):
        """A post whose first heading is a section would otherwise be filed under
        it — one article on this site is filed under the author's name."""
        document, chunks = self.build()
        assert document.title == "A Post About Things"
        assert all(chunk.doc_title == "A Post About Things" for chunk in chunks)

    def test_citations_use_pandocs_anchor_not_a_reslugified_heading(self):
        _document, chunks = self.build()
        urls = {chunk.url for chunk in chunks}
        assert "https://example.test/post/a-post/a-post/#first-section-id" in urls
        assert "https://example.test/post/a-post/a-post/#second-section-id" in urls
        # The slugified form is what the old code would have produced.
        assert not any(url.endswith("#first-section") for url in urls)

    def test_a_heading_without_an_explicit_anchor_links_to_the_bare_page(self):
        """Slugifying it would be guessing at another renderer's id, and a guess
        that misses lands the reader at the top of the page with no sign that
        anything went wrong."""
        raw = self.POST_FILE.replace(" {#first-section-id}", "")
        _document, chunks = corpus_mod.chunk_post(
            "post", "a-post/a-post.md", raw, profiles.get("site")
        )
        first = next(chunk for chunk in chunks if chunk.heading == "First section")
        assert first.url == "https://example.test/post/a-post/a-post/"

    def test_breadcrumbs_are_built_from_the_real_title(self):
        """The inferred title here would be "First section" — the post opens with
        prose and a level-2 heading, never an H1 — so a breadcrumb built from the
        first heading files the whole article under one of its own sections."""
        _document, chunks = self.build()
        first = next(chunk for chunk in chunks if chunk.heading == "First section")
        assert first.breadcrumb == "A Post About Things › First section"
        intro = chunks[0]
        assert intro.breadcrumb == "A Post About Things"
        assert intro.heading == "A Post About Things"

    def test_the_rcc_corpus_still_slugifies_its_own_headings(self):
        """mkdocs generates those anchors, so computing them is correct there.
        The change above must not have taken them away."""
        _document, chunks = corpus_mod.chunk_markdown(
            "docs", "slurm/sbatch.md", "# Batch jobs\n\n## GPU jobs\n\n" + "x " * 100,
            profiles.get("rcc"),
        )
        assert any(chunk.url.endswith("#gpu-jobs") for chunk in chunks)


class TestSiteHtml:
    def test_pandoc_section_ids_survive_the_conversion(self):
        html = (
            '<div id="what-it-entails" class="section level2">'
            "<h2>What it entails</h2><p>Prose.</p></div>"
        )
        assert "## What it entails {#what-it-entails}" in sitehtml.to_markdown(html)

    def test_a_heading_with_its_own_id_uses_that_one(self):
        html = '<h2 id="own-id">Titled</h2>'
        assert "## Titled {#own-id}" in sitehtml.to_markdown(html)

    def test_code_blocks_keep_their_language(self):
        html = '<pre class="r"><code>library(dplyr)</code></pre>'
        assert "```r\nlibrary(dplyr)\n```" in sitehtml.to_markdown(html)

    def test_r_output_is_fenced_so_its_hashes_are_not_read_as_headings(self):
        """knitr prefixes output with `##`, which is a level-2 heading in markdown.
        One post produced 146 of them."""
        html = "<pre><code>## # A tibble: 7,787 x 14\n## show_id type</code></pre>"
        markdown = sitehtml.to_markdown(html)
        sections = [
            section
            for section in corpus_mod._split_sections(markdown)
            if section.heading
        ]
        assert sections == []

    def test_links_are_kept_and_in_page_anchors_are_unwrapped(self):
        html = '<p>See <a href="https://x.test/a">this</a> and <a href="#top">that</a>.</p>'
        markdown = sitehtml.to_markdown(html)
        assert "[this](https://x.test/a)" in markdown
        assert "that" in markdown and "(#top)" not in markdown

    def test_figures_contribute_their_alt_text(self):
        """A chat answer cannot show the plot, but the alt text is searchable."""
        html = '<p><img src="a.png" alt="Loss curve by step"/></p>'
        assert "[figure: Loss curve by step]" in sitehtml.to_markdown(html)

    def test_scripts_and_styles_are_dropped(self):
        html = "<script>var x = 1;</script><style>p{}</style><p>Kept.</p>"
        markdown = sitehtml.to_markdown(html)
        assert "var x" not in markdown and "p{}" not in markdown
        assert "Kept." in markdown

    def test_adjacent_inline_tags_do_not_run_together(self):
        html = "<p><em>one</em> <em>two</em></p>"
        assert "one* *two" in sitehtml.to_markdown(html)

    def test_lists_become_markdown_lists(self):
        html = "<ul><li>first</li><li>second</li></ul>"
        markdown = sitehtml.to_markdown(html)
        assert "- first" in markdown and "- second" in markdown

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ('---\ntitle: "Quoted"\n---\nbody', "Quoted"),
            ("---\ntitle: 'Single'\n---\nbody", "Single"),
            ("---\ntitle: Bare\n---\nbody", "Bare"),
        ],
    )
    def test_front_matter_quoting_styles_are_all_stripped(self, raw, expected):
        """Both styles appear across five years of posts, and a `date:
        '2021-08-15'` read with only the double-quote form stripped keeps its
        apostrophes and sorts apart from every other date."""
        fields, body = sitehtml.split_front_matter(raw)
        assert fields["title"] == expected
        assert body.strip() == "body"

    def test_a_file_without_front_matter_is_returned_whole(self):
        fields, body = sitehtml.split_front_matter("<p>No front matter.</p>")
        assert fields == {}
        assert body == "<p>No front matter.</p>"


class TestProfileShape:
    def test_kinds_are_reported_per_source(self):
        profile = Profile(
            key="t",
            sources=(
                Source("a", "/a", (".md",), MARKDOWN),
                Source("b", "/b", (".txt",), SCRAPED),
                Source("c", "/c", (".md",), POST, weight=2.0),
            ),
        )
        assert profile.kind("b") == SCRAPED
        assert profile.kind("c") == POST
        assert profile.weight("c") == 2.0
        # An unknown source must not raise: a stray directory should be inert.
        assert profile.kind("zz") == MARKDOWN
        assert profile.paths == {"a": "/a", "b": "/b", "c": "/c"}
