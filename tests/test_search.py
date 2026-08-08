from sage import config, search
from sage.corpus import Chunk, Corpus


def make_corpus(*bodies: tuple[str, str, str]) -> Corpus:
    chunks = [
        Chunk(
            id=f"docs/{path}#{index}",
            source="docs",
            path=path,
            doc_title=title,
            heading=title,
            breadcrumb=title,
            text=text,
            url=f"https://example.test/{path}",
        )
        for index, (path, title, text) in enumerate(bodies)
    ]
    return Corpus(chunks=chunks, documents={})


class TestTokenize:
    def test_stems_plurals_consistently(self):
        assert search.tokenize("quotas") == search.tokenize("quota")
        assert search.tokenize("nodes") == search.tokenize("node")
        assert search.tokenize("processes") == search.tokenize("process")
        assert search.tokenize("directories") == search.tokenize("directory")

    def test_double_s_words_are_not_mangled(self):
        assert "clas" not in search.tokenize("class")

    def test_technical_terms_are_protected(self):
        assert "gres" in search.tokenize("--gres=gpu:1")
        assert "globus" in search.tokenize("Globus")

    def test_cluster_names_emit_both_forms(self):
        tokens = search.tokenize("midway3")
        assert "midway3" in tokens
        assert "midway" in tokens
        assert "3" in tokens

    def test_single_characters_are_kept_so_r_is_searchable(self):
        """`R` is a language users ask about; IDF handles the noisy letters."""
        assert search.tokenize("use R") == ["use", "r"]

    def test_single_letter_language_is_retrievable(self, real_index):
        pages = {result.chunk.path for result in real_index.search("use R on midway", 5)}
        assert "software/apps-and-envs/r.md" in pages


class TestExpandQuery:
    def test_exact_terms_outweigh_synonyms(self):
        weights = search.expand_query("scavenge")
        assert weights[search._stem("scavenge")] == 1.0
        assert weights[search._stem("preemptible")] == config.SYNONYM_WEIGHT

    def test_symptom_language_reaches_mechanism_language(self):
        weights = search.expand_query("my job was killed")
        assert search._stem("memory") in weights

    def test_empty_query_expands_to_nothing(self):
        assert search.expand_query("   ") == {}


class TestRanking:
    def test_shorter_focused_pages_beat_long_dumps(self):
        """BM25 length normalization is what the old `min(count, 5)` scorer lacked."""
        filler = " ".join(f"unrelated sentence {n}" for n in range(4000))
        corpus = make_corpus(
            ("focused.md", "Storage quota", "Your storage quota is 25 GB on /home."),
            ("dump.md", "Publications", f"quota {filler}"),
        )
        results = search.Index(corpus).search("storage quota")
        assert results[0].chunk.path == "focused.md"

    def test_rare_terms_outrank_common_ones(self):
        corpus = make_corpus(
            ("a.md", "A", "the the the the sbatch"),
            ("b.md", "B", "the the the the the the the the"),
            ("c.md", "C", "the the the the the"),
        )
        results = search.Index(corpus).search("the sbatch")
        assert results[0].chunk.path == "a.md"

    def test_title_matches_are_boosted(self):
        corpus = make_corpus(
            ("a.md", "Unrelated heading", "globus appears once here"),
            ("b.md", "Globus transfers", "some other body text entirely"),
        )
        results = search.Index(corpus).search("globus")
        assert results[0].chunk.path == "b.md"

    def test_the_user_guide_outranks_the_scraped_site_on_a_tie(self):
        text = "Storage quotas are enforced per directory."
        chunks = [
            Chunk("web/p.txt#1", "web", "p.txt", "Storage", "Storage", "Storage", text, "u"),
            Chunk("docs/p.md#1", "docs", "p.md", "Storage", "Storage", "Storage", text, "u"),
        ]
        results = search.Index(Corpus(chunks=chunks)).search("storage quotas")
        assert results[0].source == "docs"

    def test_no_match_returns_nothing(self):
        corpus = make_corpus(("a.md", "A", "storage quota information"))
        assert search.Index(corpus).search("xylophone unicorn") == []

    def test_empty_index_is_safe(self):
        assert search.Index(Corpus()).search("anything") == []

    def test_limit_is_respected(self, real_index):
        assert len(real_index.search("storage", limit=3)) == 3


class TestSnippet:
    def test_original_casing_is_preserved(self):
        """The old snippet sliced a lowercased copy, mangling Midway3 and CNetID."""
        text = "Connect to Midway3 with your CNetID and run sbatch --gres=gpu:1 now."
        out = search.snippet(text, search.expand_query("cnetid"))
        assert "CNetID" in out
        assert "--gres=gpu:1" in out

    def test_window_centres_on_the_match(self):
        text = "filler " * 60 + "QUOTA MARKER" + " tail" * 60
        out = search.snippet(text, search.expand_query("quota"), width=80)
        assert "QUOTA MARKER" in out
        assert out.startswith("…")

    def test_short_text_is_returned_whole(self):
        out = search.snippet("Short body.", search.expand_query("short"))
        assert out == "Short body."


def test_index_builds_over_the_real_corpus(real_index):
    assert real_index.total > 300
    assert real_index.average_length > 0
