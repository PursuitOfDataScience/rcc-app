import pytest

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


class TestStemming:
    """The stemmer claimed to be "Porter-ish" and stripped plurals only."""

    @pytest.mark.parametrize(
        ("inflected", "base"),
        [
            # The group ("scavenge", "preemptible", "preempt") was written for this
            # query and could never fire, because `preempted` reached the index as
            # itself and matched no member of it.
            ("preempted", "preempt"),
            ("purged", "purge"),
            ("exceeded", "exceed"),
            ("submitting", "submit"),
            ("installed", "install"),
            ("cancelled", "cancel"),
        ],
    )
    def test_a_verb_and_its_inflection_share_a_key(self, inflected, base):
        assert search._stem(inflected) == search._stem(base)

    @pytest.mark.parametrize("word", ["running", "getting", "making"])
    def test_generic_verbs_are_left_apart(self, word):
        """`running` onto `run` hands that key the frequency of both, and the golden
        set charged 2.9pp of recall for it: `ecosystems.md` stopped being the best
        answer to "what clusters does RCC run" because every page mentions running
        something. A three-letter stem is scaffolding, not a topic."""
        assert search._stem(word) != search._stem(word[:3])

    @pytest.mark.parametrize("word", ["scoring", "sharing"])
    def test_gerunds_do_not_collapse_onto_four_letter_fragments(self, word):
        """`scoring` → `scor` matched a GIS page titled "Match Score" and scored a
        radiology question the corpus cannot answer at 28.7, on a title boost."""
        assert search._stem(word) == word

    def test_the_synonym_group_written_for_preemption_now_fires(self, real_index):
        weights = search.expand_query("my job was preempted")
        assert search._stem("scavenge") in weights


class TestAssessment:
    """Whether retrieval admits it is weak. Both thresholds are pinned here, on the
    labelled queries their values were measured from — the previous version of this
    idea shipped a threshold that passed the whole suite at any value from 0 to 20."""

    OUT_OF_SCOPE = [
        "how do I install OpenFOAM",
        "PI-RADS prostate MRI scoring",
        "mpMRI prostate imaging protocol",
        "what is the weather in Chicago",
        "who won the world cup",
        "how do I bake sourdough bread",
    ]
    # In scope, and each carrying a word the documentation has never seen: a daemon
    # named in an error message, a job ID, a CNetID, an error token.
    WITH_IDENTIFIERS = [
        "my job was killed by slurmstepd oom-kill event",
        "why did job 41235567 fail",
        "my CNetID is jsmith and I cannot log in",
        "srun: error: task 0 launch failed: Unspecified error",
    ]

    @pytest.mark.parametrize("question", OUT_OF_SCOPE)
    def test_out_of_scope_questions_are_not_confident(self, real_index, question):
        assessment = real_index.assess(question)
        assert not assessment.confident, f"{question!r} scored {assessment.top_score:.1f}"
        assert assessment.caveat()

    @pytest.mark.parametrize("question", WITH_IDENTIFIERS)
    def test_an_unseen_word_does_not_veto_strong_evidence(self, real_index, question):
        """This is what made the idea unusable before: every one of these was told the
        documentation does not cover it, and every one of them is answered by it."""
        assessment = real_index.assess(question)
        assert assessment.confident, (
            f"{question!r} scored {assessment.top_score:.1f} and was refused over "
            f"{assessment.unknown_terms}"
        )
        assert assessment.caveat() == ""

    def test_a_job_number_is_never_an_unseen_topic(self, real_index):
        assert real_index.assess("why did job 41235567 fail").unknown_terms == ()

    def test_the_caveat_quotes_the_readers_words_not_stems(self, real_index):
        """It said "No section contains: prostat, unspecifi, instal"."""
        assessment = real_index.assess("how do I bake sourdough bread")
        assert "sourdough" in assessment.caveat()
        # `bake` stems to `bak`, and the stem is what used to be quoted.
        assert "bake" in assessment.unknown_terms
        assert "bak" not in assessment.unknown_terms

    def test_a_caveat_is_not_a_percentage(self, real_index):
        assessment = real_index.assess("how do I install OpenFOAM")
        assert "%" not in assessment.caveat()
        assert assessment.margin >= 0
