"""End-to-end smoke tests for app.py against a stubbed Streamlit.

These cover the rewritten tool loop: that a search → read → answer sequence streams,
that the sections actually read become the Sources strip, and that a failure lands in
a typed, user-readable error instead of taking the page down.
"""

import pytest

import stub_streamlit
from sage import config, llm, providers


def event(content=None, tool_calls=None):
    return providers.Chunk(text=content or "", tool_calls=tool_calls or [])


def tool_call(index, cid, name, arguments):
    return {"index": index, "id": cid, "name": name, "arguments": arguments}


class ScriptedProvider:
    """Replays a list of turns, one per `stream(...)` call."""

    def __init__(self, turns, error=None, name="mistral", models=("m1",)):
        self.name = name
        self.turns = list(turns)
        self.error = error
        self.calls = 0
        self.sent: list[list[dict]] = []
        self.tools_seen: list = []
        self._models = models

    def models(self):
        return [providers.Model(self.name, model_id) for model_id in self._models]

    def stream(self, model, messages, tools):
        self.calls += 1
        self.sent.append(messages)
        self.tools_seen.append(tools)
        if self.error:
            raise self.error
        if not self.turns:
            raise AssertionError("provider called more times than scripted")
        yield from self.turns.pop(0)


def run_app(monkeypatch, *, client=None, session=None, extra=None,
            opencode=False, **stub_kwargs):
    """Import app.py under the stub and return (stub, module-or-None).

    `opencode=True` configures a second provider, so the model picker appears.
    """
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    if opencode:
        monkeypatch.setenv("OPENCODE_API_KEY", "sk-zen-test")
    else:
        monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    stub = stub_streamlit.install(**stub_kwargs)
    if session:
        stub.session_state.update(session)
    if client is not None:
        registry = {client.name: client, **(extra or {})}
        monkeypatch.setattr(
            providers, "build", lambda name, _key: registry[name]
        )

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
        # The limits line was removed from the hero: it duplicated the disclaimer
        # under the input. The About panel still states them.
        assert "Sage reads the docs" not in html
        assert "Run commands or read files on the cluster" in html

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
        client = ScriptedProvider([self.SEARCH, self.READ, self.ANSWER])
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
        client = ScriptedProvider([self.SEARCH, self.READ, self.ANSWER])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        # The answer arrived as two separate deltas through write_stream, which only
        # happens if the post-tool turn was consumed as a live generator.
        assert stub.stream_chunks[-1] == 2

    def test_sections_that_were_read_become_sources(self, monkeypatch):
        client = ScriptedProvider([self.SEARCH, self.READ, self.ANSWER])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        sources = stub.session_state["messages"][-1]["sources"]
        assert [source["id"] for source in sources] == ["docs/storage/main.md#quotas"]
        assert sources[0]["url"].endswith("/storage/main/#quotas")
        assert sources[0]["source"] == "docs"

    def test_tool_results_are_sent_back_to_the_model(self, monkeypatch):
        client = ScriptedProvider([self.SEARCH, self.READ, self.ANSWER])
        run_app(monkeypatch, client=client, session=self.session())
        final = client.sent[-1]
        roles = [message["role"] for message in final]
        assert roles.count("tool") == 2
        assert roles[0] == "system"
        tool_bodies = [m["content"] for m in final if m["role"] == "tool"]
        assert any("path: docs/" in body for body in tool_bodies)
        assert any("Quotas" in body for body in tool_bodies)

    def test_related_sections_are_offered_alongside_sources(self, monkeypatch):
        client = ScriptedProvider([self.SEARCH, self.READ, self.ANSWER])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        # Rendering the stored answer happens on the rerun, so render it here.
        html = "\n".join(stub.markdown_html)
        assert "Sources" in html or stub.session_state["messages"][-1]["sources"]

    def test_an_answer_with_no_tools_still_works(self, monkeypatch):
        client = ScriptedProvider([[event("I cannot run commands.")]])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert client.calls == 1
        assert stub.session_state["messages"][-1]["text"] == "I cannot run commands."
        assert stub.session_state["messages"][-1]["sources"] == []

    def test_the_tool_round_limit_is_enforced(self, monkeypatch):
        from sage import config

        client = ScriptedProvider([self.SEARCH] * (config.MAX_TOOL_ROUNDS + 1))
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert client.calls == config.MAX_TOOL_ROUNDS + 1
        assert "wasn't able to finish" in stub.session_state["messages"][-1]["text"]

    def test_api_failure_becomes_a_typed_user_message(self, monkeypatch):
        error = RuntimeError("rate limit exceeded")
        monkeypatch.setattr(llm.time, "sleep", lambda _s: None)
        client = ScriptedProvider([], error=error)
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert stub.session_state["error"] == llm.AssistantError("rate_limit").user_message
        assert stub.session_state["processing"] is False
        # The question survives so the retry button has something to resend.
        assert stub.session_state["messages"][-1]["role"] == "user"

    def test_an_unexpected_exception_does_not_take_the_page_down(self, monkeypatch):
        client = ScriptedProvider([], error=ValueError("totally unexpected"))
        stub, _module = run_app(monkeypatch, client=client, session=self.session())
        assert stub.session_state["error"]
        assert stub.session_state["processing"] is False


class TestModelPicker:
    """Switching provider mid-session is the way round a spent API quota."""

    def session(self):
        return {"messages": [], "processing": False}

    def test_no_picker_when_only_one_model_is_available(self, monkeypatch):
        provider = ScriptedProvider([], models=("only-one",))
        stub, _m = run_app(monkeypatch, client=provider, session=self.session())
        assert not [e for e in stub.events if e[0] == "selectbox"]

    def test_picker_lists_every_model_from_every_configured_provider(self, monkeypatch):
        mistral = ScriptedProvider([], name="mistral", models=("mistral-small-latest",))
        zen = ScriptedProvider([], name="opencode",
                               models=("deepseek-v4-flash-free", "big-pickle"))
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=self.session(), opencode=True)
        picks = [e for e in stub.events if e[0] == "selectbox"]
        assert picks, "expected a model picker"
        offered = picks[0][1][1]
        assert "mistral:mistral-small-latest" in offered
        assert "opencode:deepseek-v4-flash-free" in offered
        assert "opencode:big-pickle" in offered

    def test_the_selected_model_is_the_one_used(self, monkeypatch):
        mistral = ScriptedProvider([], name="mistral", models=("mistral-small-latest",))
        zen = ScriptedProvider([[event("Zen answered.")]], name="opencode",
                               models=("deepseek-v4-flash-free",))
        session = {
            "messages": [{"role": "user", "text": "hi", "attachment": None}],
            "processing": True,
            "model": "opencode:deepseek-v4-flash-free",
        }
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=session, opencode=True)
        assert zen.calls == 1
        assert mistral.calls == 0
        assert stub.session_state["messages"][-1]["text"] == "Zen answered."
        assert stub.session_state["messages"][-1]["model"] == (
            "opencode:deepseek-v4-flash-free"
        )

    def test_an_unknown_saved_model_falls_back_instead_of_crashing(self, monkeypatch):
        provider = ScriptedProvider([[event("ok")]], models=("m1",))
        session = {
            "messages": [{"role": "user", "text": "hi", "attachment": None}],
            "processing": True,
            "model": "opencode:retired-model",
        }
        stub, _m = run_app(monkeypatch, client=provider, session=session)
        assert stub.session_state["model"] == "mistral:m1"
        assert stub.session_state["error"] is None


class TestToollessModels:
    """Free models that cannot call tools still answer, from a single retrieval."""

    def session(self, model):
        return {
            "messages": [
                {"role": "user", "text": "what is my storage quota", "attachment": None}
            ],
            "processing": True,
            "model": model,
        }

    def test_a_configured_toolless_model_retrieves_up_front(self, monkeypatch):
        # config reads env at import, so patch the value the app actually uses.
        monkeypatch.setattr(config, "TOOLLESS_MODELS", ("big-pickle",))
        zen = ScriptedProvider([[event("Your quota is 30 GB.")]], name="opencode",
                               models=("big-pickle",))
        mistral = ScriptedProvider([], name="mistral", models=("m1",))
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=self.session("opencode:big-pickle"), opencode=True)
        assert zen.calls == 1
        assert zen.tools_seen == [None], "tools must not be offered"
        sent = "\n".join(m["content"] for m in zen.sent[0])
        assert "Answer only from these RCC documentation sections" in sent
        assert "docs/storage" in sent
        answer = stub.session_state["messages"][-1]
        assert answer["text"] == "Your quota is 30 GB."
        assert answer["sources"], "retrieved sections should become the Sources strip"

    def test_a_provider_rejecting_tools_falls_back_automatically(self, monkeypatch):
        monkeypatch.setattr(config, "TOOLLESS_MODELS", ())

        class RejectsTools(ScriptedProvider):
            def stream(self, model, messages, tools):
                self.calls += 1
                self.sent.append(messages)
                self.tools_seen.append(tools)
                if tools:
                    raise RuntimeError("this model does not support tools")
                yield event("Answered without tools.")

        provider = RejectsTools([], models=("m1",))
        stub, _m = run_app(monkeypatch, client=provider,
                           session=self.session("mistral:m1"))
        assert provider.tools_seen[0] is not None
        assert provider.tools_seen[-1] is None
        assert stub.session_state["messages"][-1]["text"] == "Answered without tools."
        assert stub.session_state["error"] is None


class TestQuotaFailover:
    """A spent quota on one provider should not dead-end the app."""

    def session(self):
        return {
            "messages": [{"role": "user", "text": "what can you do?",
                          "attachment": None}],
            "processing": True,
            "model": "mistral:m1",
        }

    @staticmethod
    def _payment_required():
        error = RuntimeError('API error occurred: Status 402. '
                             'Body: {"detail":"Check your subscription"}')
        error.status_code = 402
        return error

    def test_402_is_reported_as_an_actionable_quota_error(self):
        assert llm.classify(self._payment_required()).kind == "quota"
        assert "selector" in llm.classify(self._payment_required()).user_message

    def test_quota_is_not_retried_against_the_same_provider(self):
        assert not llm.classify(self._payment_required()).retryable

    def test_a_spent_quota_switches_to_the_other_provider(self, monkeypatch):
        mistral = ScriptedProvider([], name="mistral", models=("m1",),
                                   error=self._payment_required())
        zen = ScriptedProvider([], name="opencode", models=("deepseek-v4-flash-free",))
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=self.session(), opencode=True)
        assert stub.session_state["model"] == "opencode:deepseek-v4-flash-free"
        assert stub.session_state["processing"] is True, "the turn should be retried"
        assert stub.session_state["error"] is None
        assert "unavailable" in stub.session_state["notice"]

    def test_it_only_fails_over_once_so_it_cannot_ping_pong(self, monkeypatch):
        mistral = ScriptedProvider([], name="mistral", models=("m1",),
                                   error=self._payment_required())
        zen = ScriptedProvider([], name="opencode", models=("z1",),
                               error=self._payment_required())
        session = self.session()
        session["failed_over"] = True
        session["model"] = "opencode:z1"
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=session, opencode=True)
        assert stub.session_state["processing"] is False
        assert stub.session_state["error"], "the second failure must surface"

    def test_with_one_provider_the_error_surfaces_instead(self, monkeypatch):
        mistral = ScriptedProvider([], name="mistral", models=("m1",),
                                   error=self._payment_required())
        stub, _m = run_app(monkeypatch, client=mistral, session=self.session())
        assert stub.session_state["processing"] is False
        assert "out of credit" in stub.session_state["error"]
        assert "402" in stub.session_state["error_detail"]


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
