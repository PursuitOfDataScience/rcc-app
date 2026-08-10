import pytest

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


class TestArgumentsAreWhateverTheModelTyped:
    """`llm._parse` guarantees a dict and nothing about what is in it.

    A weak model typing its query as a number — `{"query": 123}` — used to raise
    AttributeError out of `.strip()`, which ended the turn with an error card blaming
    the network for a mistake the model made.
    """

    @pytest.mark.parametrize("query", [123, 4.5, ["gpu", "jobs"], {"q": "x"}, True])
    def test_a_search_argument_of_any_type_answers(self, real_index, query):
        assert runner(real_index).run(tools.SEARCH_DOCS, {"query": query})

    @pytest.mark.parametrize("path", [123, ["docs/slurm/sbatch.md"], {"p": 1}])
    def test_a_read_argument_of_any_type_answers(self, real_index, path):
        assert "Error" in runner(real_index).run(tools.READ_DOC, {"path": path})

    def test_a_missing_argument_is_not_searched_for_as_the_word_none(self, real_index):
        tool = runner(real_index)
        assert tool.run(tools.SEARCH_DOCS, {}) == tool.run(
            tools.SEARCH_DOCS, {"query": ""}
        )


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
