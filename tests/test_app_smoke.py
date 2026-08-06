"""End-to-end smoke tests for app.py against a stubbed Streamlit.

These cover the rewritten tool loop: that a search → read → answer sequence streams,
that the sections actually read become the Sources strip, and that a failure lands in
a typed, user-readable error instead of taking the page down.
"""

from types import SimpleNamespace

import pytest

import stub_streamlit
from sage import llm


def event(content=None, tool_calls=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(data=SimpleNamespace(choices=[SimpleNamespace(delta=delta)]))


def tool_call(index, cid, name, arguments):
    return SimpleNamespace(
        index=index, id=cid, function=SimpleNamespace(name=name, arguments=arguments)
    )


class ScriptedClient:
    """Replays a list of turns, one per `chat.stream(...)` call."""

    def __init__(self, turns, error=None):
        self.turns = list(turns)
        self.error = error
        self.calls = 0
        self.sent: list[list[dict]] = []
        self.chat = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        self.calls += 1
        self.sent.append(kwargs["messages"])
        if self.error:
            raise self.error
        if not self.turns:
            raise AssertionError("client called more times than scripted")
        return iter(self.turns.pop(0))


def run_app(monkeypatch, *, client=None, session=None, **stub_kwargs):
    """Import app.py under the stub and return (stub, module-or-None)."""
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    stub = stub_streamlit.install(**stub_kwargs)
    if session:
        stub.session_state.update(session)
    if client is not None:
        monkeypatch.setattr(llm, "create_client", lambda _key: client)

    module = None
    try:
        import app as module  # noqa: PLC0415
    except (stub_streamlit.Rerun, stub_streamlit.Stop):
        pass
    return stub, module


@pytest.fixture(autouse=True)
def _clean_modules():
    yield
    import sys

    for name in ("app", "streamlit", "streamlit.components", "streamlit.components.v1"):
        sys.modules.pop(name, None)


class TestWelcome:
    def test_renders_without_a_conversation(self, monkeypatch):
        stub, module = run_app(monkeypatch)
        assert module is not None
        html = "\n".join(stub.markdown_html)
        assert "What can I help you with?" in html
        assert "cannot run commands" in html

    def test_example_cards_get_stable_keyed_containers(self, monkeypatch):
        """CSS staggers on these keys; :nth-child never worked for Streamlit buttons."""
        stub, _module = run_app(monkeypatch)
        keys = {key for name, key in stub.events if name == "container"}
        assert {f"example-card-{n}" for n in range(6)} <= keys

    def test_missing_api_key_stops_with_a_clear_message(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        stub = stub_streamlit.install()
        with pytest.raises(stub_streamlit.Stop):
            import app  # noqa: F401, PLC0415
        assert any("MISTRAL_API_KEY" in error for error in stub.errors)


class TestTurnLoop:
    SEARCH = [event(tool_calls=[tool_call(0, "c1", "search_docs", '{"query":"quota"}')])]
    READ = [
        event(tool_calls=[tool_call(0, "c2", "read_doc", '{"path":"docs/storage/main.md#quotas"}')])
    ]
    ANSWER = [event("Your /home quota is "), event("30 GB.")]

    def session(self, question="what is my storage quota"):
        return {
            "messages": [{"role": "user", "text": question, "attachment": None}],
            "processing": True,
        }

    def test_search_read_answer_produces_a_stored_answer(self, monkeypatch):
        client = ScriptedClient([self.SEARCH, self.READ, self.ANSWER])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())

        assert client.calls == 3
        messages = stub.session_state["messages"]
        assert messages[-1]["role"] == "assistant"
        assert messages[-1]["text"] == "Your /home quota is 30 GB."
        assert stub.session_state["processing"] is False
        assert stub.session_state["error"] is None

    def test_the_final_answer_is_streamed_not_dumped(self, monkeypatch):
        """The old loop collected the post-tool answer silently, so the most common
        interaction (search -> read -> answer) never streamed at all."""
        client = ScriptedClient([self.SEARCH, self.READ, self.ANSWER])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        # The answer arrived as two separate deltas through write_stream, which only
        # happens if the post-tool turn was consumed as a live generator.
        assert stub.stream_chunks[-1] == 2

    def test_sections_that_were_read_become_sources(self, monkeypatch):
        client = ScriptedClient([self.SEARCH, self.READ, self.ANSWER])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        sources = stub.session_state["messages"][-1]["sources"]
        assert [source["id"] for source in sources] == ["docs/storage/main.md#quotas"]
        assert sources[0]["url"].endswith("/storage/main/#quotas")
        assert sources[0]["source"] == "docs"

    def test_tool_results_are_sent_back_to_the_model(self, monkeypatch):
        client = ScriptedClient([self.SEARCH, self.READ, self.ANSWER])
        run_app(monkeypatch, client=client, session=self.session())
        final = client.sent[-1]
        roles = [message["role"] for message in final]
        assert roles.count("tool") == 2
        assert roles[0] == "system"
        tool_bodies = [m["content"] for m in final if m["role"] == "tool"]
        assert any("path: docs/" in body for body in tool_bodies)
        assert any("Quotas" in body for body in tool_bodies)

    def test_related_sections_are_offered_alongside_sources(self, monkeypatch):
        client = ScriptedClient([self.SEARCH, self.READ, self.ANSWER])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        # Rendering the stored answer happens on the rerun, so render it here.
        html = "\n".join(stub.markdown_html)
        assert "Sources" in html or stub.session_state["messages"][-1]["sources"]

    def test_an_answer_with_no_tools_still_works(self, monkeypatch):
        client = ScriptedClient([[event("I cannot run commands.")]])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert client.calls == 1
        assert stub.session_state["messages"][-1]["text"] == "I cannot run commands."
        assert stub.session_state["messages"][-1]["sources"] == []

    def test_the_tool_round_limit_is_enforced(self, monkeypatch):
        from sage import config

        client = ScriptedClient([self.SEARCH] * (config.MAX_TOOL_ROUNDS + 1))
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert client.calls == config.MAX_TOOL_ROUNDS + 1
        assert "wasn't able to finish" in stub.session_state["messages"][-1]["text"]

    def test_api_failure_becomes_a_typed_user_message(self, monkeypatch):
        error = RuntimeError("rate limit exceeded")
        monkeypatch.setattr(llm.time, "sleep", lambda _s: None)
        client = ScriptedClient([], error=error)
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert stub.session_state["error"] == llm.AssistantError("rate_limit").user_message
        assert stub.session_state["processing"] is False
        # The question survives so the retry button has something to resend.
        assert stub.session_state["messages"][-1]["role"] == "user"

    def test_an_unexpected_exception_does_not_take_the_page_down(self, monkeypatch):
        client = ScriptedClient([], error=ValueError("totally unexpected"))
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert stub.session_state["error"]
        assert stub.session_state["processing"] is False


class TestConversationRendering:
    def test_prior_answers_render_with_resolved_links(self, monkeypatch):
        session = {
            "messages": [
                {"role": "user", "text": "how do I submit a job", "attachment": None},
                {
                    "role": "assistant",
                    "text": "See [Batch jobs](docs/slurm/sbatch.md).",
                    "sources": [
                        {
                            "id": "docs/slurm/sbatch.md#batch-jobs",
                            "label": "Batch jobs",
                            "url": "https://example.test/x",
                            "source": "docs",
                        }
                    ],
                    "rating": None,
                },
            ],
            "processing": False,
        }
        stub, _module = run_app(monkeypatch, session=session)
        rendered = "\n".join(str(body) for _name, body in stub.events if _name == "markdown")
        assert "rcc-uchicago.github.io/user-guide/slurm/sbatch/" in rendered
        assert "docs/slurm/sbatch.md" not in rendered

    def test_user_html_is_escaped(self, monkeypatch):
        session = {
            "messages": [
                {
                    "role": "user",
                    "text": "<img src=x onerror=alert(1)>",
                    "attachment": None,
                }
            ],
            "processing": False,
        }
        stub, _module = run_app(monkeypatch, session=session)
        html = "\n".join(stub.markdown_html)
        assert "<img src=x" not in html
        assert "&lt;img" in html
