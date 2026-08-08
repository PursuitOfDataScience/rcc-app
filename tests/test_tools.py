from sage import tools
from sage.search import Index


def runner(real_index) -> tools.ToolRunner:
    return tools.ToolRunner(real_index)


def test_search_returns_paths_the_model_can_read_back(real_index):
    out = runner(real_index).run(tools.SEARCH_DOCS, {"query": "storage quota"})
    assert "path: docs/" in out
    assert "snippet:" in out


def test_empty_search_is_reported_not_crashed(real_index):
    out = runner(real_index).run(tools.SEARCH_DOCS, {"query": ""})
    assert "No matching RCC documentation" in out


def test_hopeless_search_points_at_the_help_desk(real_index):
    out = runner(real_index).run(tools.SEARCH_DOCS, {"query": "zzzz qqqq xxxx"})
    assert "Help Desk" in out


def test_reading_a_section_returns_it_with_a_breadcrumb(real_index):
    tool = runner(real_index)
    out = tool.run(READ := tools.READ_DOC, {"path": "docs/slurm/sbatch.md#managing-jobs"})
    assert READ == "read_doc"
    assert "Batch jobs › Managing jobs" in out
    assert "Sections on this page:" in out


def test_reads_are_recorded_as_sources(real_index):
    tool = runner(real_index)
    tool.run(tools.READ_DOC, {"path": "docs/slurm/sbatch.md#managing-jobs"})
    tool.run(tools.READ_DOC, {"path": "docs/slurm/sbatch.md#managing-jobs"})
    assert len(tool.sources) == 1
    assert tool.sources[0].url.endswith("#managing-jobs")


def test_reading_a_whole_page_works(real_index):
    out = runner(real_index).run(tools.READ_DOC, {"path": "docs/glossary.md"})
    assert "Glossary" in out


def test_a_long_page_returns_an_outline_instead_of_being_silently_cut(real_index):
    out = runner(real_index).run(tools.READ_DOC, {"path": "docs/slurm/sbatch.md"})
    assert "Sections on this page:" in out
    assert "read_doc again" in out


class TestPathSafety:
    """Reads resolve against the index, so a filesystem path cannot be reached."""

    def test_traversal_is_not_resolvable(self, real_index):
        for probe in (
            "docs/../../etc/passwd",
            "docs/../app.py",
            "/etc/passwd",
            "web/../../../../etc/hosts",
        ):
            out = runner(real_index).run(tools.READ_DOC, {"path": probe})
            assert "not in the documentation index" in out or "invalid path" in out

    def test_unknown_source_is_rejected(self, real_index):
        out = runner(real_index).run(tools.READ_DOC, {"path": "secrets/key.md"})
        assert "not in the documentation index" in out

    def test_missing_path_is_rejected(self, real_index):
        out = runner(real_index).run(tools.READ_DOC, {"path": ""})
        assert "invalid path" in out

    def test_nothing_outside_the_index_is_ever_recorded(self, real_index):
        tool = runner(real_index)
        tool.run(tools.READ_DOC, {"path": "docs/../app.py"})
        assert tool.sources == []


def test_unknown_tool_name_is_reported(real_index):
    assert "Unknown tool" in runner(real_index).run("rm_rf", {})


def test_tool_schemas_are_well_formed():
    names = {schema["function"]["name"] for schema in tools.TOOL_SCHEMAS}
    assert names == {tools.SEARCH_DOCS, tools.READ_DOC}
    for schema in tools.TOOL_SCHEMAS:
        function = schema["function"]
        assert schema["type"] == "function"
        assert function["description"]
        assert function["parameters"]["required"]


def test_runner_works_on_an_empty_index():
    from sage.corpus import Corpus

    tool = tools.ToolRunner(Index(Corpus()))
    assert "No matching" in tool.run(tools.SEARCH_DOCS, {"query": "anything"})


class TestWeakSearchWarnsTheModel:
    """Retrieval has to be able to say it does not know.

    `Index.search` returns any chunk scoring above zero, so "how do I install
    OpenFOAM" came back with three irrelevant sections formatted exactly like three
    good ones. The caveat goes ahead of the results because the model reads top-down.
    """

    def test_an_uncovered_topic_is_flagged(self, real_index):
        out = runner(real_index).run(
            tools.SEARCH_DOCS, {"query": "how do I install OpenFOAM"}
        )
        assert "RETRIEVAL WARNING" in out
        assert "openfoam" in out.lower()
        # The warning must come before the results it is about.
        assert out.index("RETRIEVAL WARNING") < out.index("path:")

    def test_a_real_question_is_not_second_guessed(self, real_index):
        out = runner(real_index).run(
            tools.SEARCH_DOCS, {"query": "how do I submit a batch job with sbatch"}
        )
        assert "RETRIEVAL WARNING" not in out

    def test_a_missed_search_offers_somewhere_to_go(self, real_index):
        """A query matching literally nothing gets the topic map as a recovery
        route — which is what makes a third `list_docs` tool unnecessary."""
        out = runner(real_index).run(tools.SEARCH_DOCS, {"query": "flibbertigibbet"})
        assert "No matching RCC documentation" in out
        assert "top level" in out

    def test_a_query_that_partly_matches_gets_the_warning_instead(self, real_index):
        """Distinct from the above: there *are* results, they are just not about what
        was asked, so the model needs the caveat rather than the topic map."""
        out = runner(real_index).run(
            tools.SEARCH_DOCS, {"query": "zzzqqq nonexistent topic"}
        )
        assert "RETRIEVAL WARNING" in out
        assert "zzzqqq" in out

    def test_the_trace_records_what_happened(self, real_index):
        run = runner(real_index)
        run.run(tools.SEARCH_DOCS, {"query": "storage quota"})
        run.run(tools.SEARCH_DOCS, {"query": "how do I install OpenFOAM"})
        assert len(run.searches) == 2
        assert run.searches[0]["confident"] is True
        assert run.searches[1]["confident"] is False
        assert run.weak_searches == 1
        # The only record that a search missed; without it every answer looks
        # equally well-supported.
        assert "openfoam" in run.searches[1]["unknown_terms"]


class TestReadDeduplication:
    def test_the_same_section_is_not_sent_twice(self, real_index):
        run = runner(real_index)
        first = run.run(tools.READ_DOC, {"path": "docs/slurm/sbatch.md"})
        second = run.run(tools.READ_DOC, {"path": "docs/slurm/sbatch.md"})
        assert len(first) > 200
        assert "already provided above" in second
        # Roughly 900 tokens per duplicate, and because each round resends the whole
        # conversation it was paid for again in every later round.
        assert len(second) < len(first) / 4

    def test_a_different_section_still_reads(self, real_index):
        run = runner(real_index)
        run.run(tools.READ_DOC, {"path": "docs/slurm/sbatch.md"})
        other = run.run(tools.READ_DOC, {"path": "docs/storage/main.md"})
        assert "already provided above" not in other

    def test_reads_are_recorded_for_the_trace(self, real_index):
        run = runner(real_index)
        run.run(tools.READ_DOC, {"path": "docs/slurm/sbatch.md"})
        assert len(run.reads) == 1


class TestFollowUpQueries:
    """The toolless path retrieved on the raw last message, so "what about on
    Midway3?" was a BM25 query of five stopwords and a cluster name."""

    def previous(self):
        return [
            {"role": "user", "text": "what are the storage quotas"},
            {
                "role": "assistant",
                "text": "...",
                "sources": [{"label": "Storage — Quotas", "id": "docs/storage/main.md"}],
            },
        ]

    def test_a_follow_up_carries_the_previous_topic(self):
        out = tools.follow_up_queries("what about on Midway3?", self.previous())
        assert "Quotas" in out
        assert "Midway3" in out

    def test_a_standalone_question_is_left_alone(self):
        question = "how do I submit a batch job with sbatch on Midway3"
        assert tools.follow_up_queries(question, self.previous()) == question

    def test_the_first_turn_is_left_alone(self):
        assert tools.follow_up_queries("what about it?", []) == "what about it?"

    def test_a_pronoun_alone_counts_as_a_follow_up(self):
        out = tools.follow_up_queries("is it backed up?", self.previous())
        assert out != "is it backed up?"

    def test_no_previous_sources_means_no_rewrite(self):
        history = [{"role": "assistant", "text": "...", "sources": []}]
        assert tools.follow_up_queries("what about it?", history) == "what about it?"


class TestGatherContextWarns:
    def test_a_weak_single_pass_retrieval_is_flagged(self, real_index):
        """It matters more here than in the tool loop: a toolless model cannot
        search again, so being told is all that stands between it and invention."""
        context, _chunks = tools.gather_context(real_index, "how do I install OpenFOAM")
        assert "RETRIEVAL WARNING" in context

    def test_a_good_single_pass_retrieval_is_clean(self, real_index):
        context, chunks = tools.gather_context(real_index, "how do I submit a batch job")
        assert "RETRIEVAL WARNING" not in context
        assert chunks
