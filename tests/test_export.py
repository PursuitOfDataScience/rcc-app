"""Transcript export. The failure this guards is silent: an export that skips
`links.fix_links` looks perfect and ships a document full of dead links."""

from sage import config, export
from sage.corpus import Chunk, Corpus, Document, docs_url

DOC = Document(
    source="docs",
    path="slurm/sbatch.md",
    title="Batch jobs",
    url=docs_url("slurm/sbatch.md"),
    text="body",
)
CHUNK = Chunk(
    id="docs/slurm/sbatch.md#gpu-jobs",
    source="docs",
    path="slurm/sbatch.md",
    doc_title="Batch jobs",
    heading="GPU jobs",
    breadcrumb="Batch jobs › GPU jobs",
    text="Use --gres=gpu:1",
    url=docs_url("slurm/sbatch.md", "gpu-jobs"),
)
CORPUS = Corpus(documents={DOC.id: DOC}, chunks=[CHUNK])

STAMP = "2026-08-08T12:00:00Z"


def conversation():
    return [
        {"role": "user", "text": "how do I request a GPU?", "attachments": []},
        {
            "role": "assistant",
            "text": "See [GPU jobs](docs/slurm/sbatch.md#gpu-jobs) and "
                    "[nope](docs/missing/gone.md).",
            "sources": [
                {
                    "id": CHUNK.id,
                    "label": "Batch jobs — GPU jobs",
                    "url": CHUNK.url,
                    "source": "docs",
                }
            ],
            "model": "mistral:mistral-small-latest",
        },
    ]


class TestMarkdown:
    def test_internal_citations_become_real_urls(self):
        out = export.as_markdown(conversation(), CORPUS, STAMP)
        assert "slurm/sbatch/#gpu-jobs" in out
        assert "docs/slurm/sbatch.md#gpu-jobs)" not in out

    def test_unresolvable_citations_are_not_linked_to_the_root(self):
        out = export.as_markdown(conversation(), CORPUS, STAMP)
        assert f"[nope]({config.DOCS_BASE_URL})" not in out
        assert "nope" in out

    def test_provenance_front_matter_is_present(self):
        out = export.as_markdown(conversation(), CORPUS, STAMP)
        assert out.startswith("---\n")
        assert STAMP in out
        assert config.HELP_DESK_EMAIL in out
        assert "mistral:mistral-small-latest" in out

    def test_the_docs_snapshot_is_carried(self):
        """The field that makes an answer checkable out of context."""
        snapshot = config.snapshot()
        out = export.as_markdown(conversation(), CORPUS, STAMP)
        if snapshot.get("user_guide_commit"):
            assert snapshot["user_guide_commit"] in out

    def test_sources_are_listed_with_urls(self):
        out = export.as_markdown(conversation(), CORPUS, STAMP)
        assert "**Sources**" in out
        assert CHUNK.url in out

    def test_questions_and_answers_are_numbered_in_pairs(self):
        out = export.as_markdown(conversation(), CORPUS, STAMP)
        assert "## Q1" in out
        assert "## A1 — mistral:mistral-small-latest" in out

    def test_secrets_pasted_into_a_question_are_not_exported(self):
        messages = conversation()
        messages[0]["text"] = "why does sk-abcdefghijklmnopqrstuvwx fail"
        out = export.as_markdown(messages, CORPUS, STAMP)
        assert "sk-abcdefghijklmnopqrstuvwx" not in out

    def test_a_trimmed_answer_says_so(self):
        messages = conversation()
        messages[1]["trimmed"] = True
        out = export.as_markdown(messages, CORPUS, STAMP)
        assert "not sent to the model" in out

    def test_an_empty_conversation_still_produces_a_document(self):
        out = export.as_markdown([], CORPUS, STAMP)
        assert out.startswith("---\n")

    def test_filename_is_filesystem_safe(self):
        name = export.filename(STAMP)
        assert name.endswith(".md")
        assert ":" not in name


class TestHelpDeskDraft:
    def test_the_question_and_searches_are_carried(self):
        url = export.help_desk_mailto(
            "Can I use Julia on Beagle3?",
            [{"query": "julia module"}],
            [],
        )
        assert url.startswith(f"mailto:{config.HELP_DESK_EMAIL}?")
        assert "Julia" in url
        assert "julia%20module" in url

    def test_it_says_when_nothing_was_found(self):
        url = export.help_desk_mailto("obscure thing", [], [])
        assert "no%20matching%20documentation" in url

    def test_secrets_are_not_put_in_a_mailto(self):
        url = export.help_desk_mailto("key sk-abcdefghijklmnopqrstuvwx", [], [])
        assert "sk-abcdefghijklmnopqrstuvwx" not in url


class TestDocsIssue:
    def test_a_prefilled_issue_carries_the_retrieval_trace(self):
        url = export.docs_issue_url("Julia on Beagle3", [{"query": "julia"}])
        assert url.startswith(config.DOCS_ISSUE_URL)
        assert "Docs%20gap" in url
        assert "julia" in url

    def test_no_url_configured_means_no_button(self, monkeypatch):
        monkeypatch.setattr(config, "DOCS_ISSUE_URL", "")
        assert export.docs_issue_url("anything", []) == ""
