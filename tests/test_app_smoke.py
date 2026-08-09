"""End-to-end smoke tests for app.py against a stubbed Streamlit.

These cover the rewritten tool loop: that a search → read → answer sequence streams,
that the sections actually read become the Sources strip, and that a failure lands in
a typed, user-readable error instead of taking the page down.
"""

import time
from types import SimpleNamespace

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
        # Collapsed, because the markup is wrapped for the source file and a
        # sentence in it is split across lines wherever that happened to land.
        html = " ".join("\n".join(stub.markdown_html).split())
        assert "What can I help you with?" in html
        # The hero says what this is, and that is all the explaining the landing
        # screen does. The limits were a third line in the hero, then an ℹ️ popover
        # in the row under the input, then three paragraphs of small print under the
        # starter cards, then one 11px caveat line beside the model name. Each was
        # one explanation too many in the way of the box you type in, and the last
        # of them is gone too.
        assert "Sage reads the docs" not in html
        assert "What Sage is" not in html
        assert "Documentation synced" not in html
        assert "drop into the walk-in lab" not in html
        assert "Sage can make mistakes" not in html
        assert "RCC Help Desk" not in html

    def test_nothing_explains_the_app_with_a_control(self, monkeypatch):
        """A button whose only job is to explain the app is one more thing in the
        way on every screen, for something you read once."""
        stub, _module = run_app(monkeypatch)
        assert ("popover", "ℹ️") not in stub.events
        assert "clear" not in stub.button_labels
        assert not any("landing-note" in html for html in stub.markdown_html)

    def test_no_hover_tooltip_on_a_control_that_already_has_a_label(self, monkeypatch):
        """A tooltip repeating a card's own text is a black box chasing the
        cursor. Only the icon-only controls, which have nothing else to go on,
        keep theirs."""
        stub, _module = run_app(monkeypatch)
        assert not [key for key in stub.tooltips if str(key).startswith("example-")]

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
            "messages": [{"role": "user", "text": question, "attachments": []}],
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

    def test_the_models_own_sources_list_does_not_reach_the_transcript(self, monkeypatch):
        """The screenshot: an answer ending `Sources: Storage System Layout › Quotas`,
        directly above the app's own strip saying the same thing. The list the reader
        should see is the one built from what was actually retrieved."""
        answer = [
            event("Your /home quota is 30 GB.\n\n"),
            event("Sources: [Quotas](docs/storage/main.md#quotas)"),
        ]
        client = ScriptedProvider([self.SEARCH, self.READ, answer])
        stub, _module = run_app(monkeypatch, client=client, session=self.session())

        stored = stub.session_state["messages"][-1]
        assert stored["text"] == "Your /home quota is 30 GB."
        # And the strip the app draws itself is untouched by the removal.
        assert [source["id"] for source in stored["sources"]] == [
            "docs/storage/main.md#quotas"
        ]

    def test_the_prompt_asks_for_no_sources_list(self):
        """Stripping is the backstop. Not spending the tokens is the fix."""
        from sage.prompts import SYSTEM_PROMPT

        assert "Cite inline" in SYSTEM_PROMPT
        # Every form of it, not just the word "Sources": told only that, a model drops
        # the label and closes with "Cited from X and Y" instead.
        assert "do not restate your citations" in SYSTEM_PROMPT.lower()
        assert "Cited from" in SYSTEM_PROMPT

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

    @staticmethod
    def _offered(stub):
        return {key: label for key, label in stub.button_labels.items()
                if str(key).startswith("pick-")}

    def test_no_picker_when_only_one_model_is_available(self, monkeypatch):
        provider = ScriptedProvider([], models=("only-one",))
        stub, _m = run_app(monkeypatch, client=provider, session=self.session())
        assert not self._offered(stub)

    def test_picker_lists_every_model_from_every_configured_provider(self, monkeypatch):
        mistral = ScriptedProvider([], name="mistral", models=("mistral-small-latest",))
        zen = ScriptedProvider([], name="opencode",
                               models=("deepseek-v4-flash-free", "big-pickle"))
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=self.session(), opencode=True)
        offered = " | ".join(self._offered(stub).values())
        assert offered, "expected a model picker"
        assert "mistral-small-latest" in offered
        assert "deepseek-v4-flash-free" in offered
        assert "big-pickle" in offered

    def test_the_trigger_names_the_model_in_use(self, monkeypatch):
        """Otherwise the only way to see which model answers is to open the menu."""
        mistral = ScriptedProvider([], name="mistral", models=("mistral-small-latest",))
        zen = ScriptedProvider([], name="opencode", models=("deepseek-v4-flash-free",))
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=self.session(), opencode=True)
        assert ("popover", "mistral-small-latest") in stub.events

    def test_it_is_not_a_selectbox(self, monkeypatch):
        """A selectbox kept its own value and clobbered an automatic failover on
        the very next rerun; it also had no intrinsic width, so in a row that
        sizes its children to their labels it rendered invisible. Buttons have
        neither problem."""
        mistral = ScriptedProvider([], name="mistral", models=("m1",))
        zen = ScriptedProvider([], name="opencode", models=("z1",))
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=self.session(), opencode=True)
        assert not [e for e in stub.events if e[0] == "selectbox"]

    def test_choosing_a_model_switches_to_it(self, monkeypatch):
        mistral = ScriptedProvider([], name="mistral", models=("m1",))
        zen = ScriptedProvider([], name="opencode", models=("z1",))
        session = self.session() | {"failed_over": True, "notice": "stale"}
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=session, opencode=True, buttons={"pick-1": True})
        assert stub.session_state["model"] == "opencode:z1"
        # A deliberate choice re-arms the automatic one and drops its message.
        assert stub.session_state["failed_over"] is False
        assert stub.session_state["notice"] == ""

    def test_the_selected_model_is_the_one_used(self, monkeypatch):
        mistral = ScriptedProvider([], name="mistral", models=("mistral-small-latest",))
        zen = ScriptedProvider([[event("Zen answered.")]], name="opencode",
                               models=("deepseek-v4-flash-free",))
        session = {
            "messages": [{"role": "user", "text": "hi", "attachments": []}],
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
            "messages": [{"role": "user", "text": "hi", "attachments": []}],
            "processing": True,
            "model": "opencode:retired-model",
        }
        stub, _m = run_app(monkeypatch, client=provider, session=session)
        assert stub.session_state["model"] == "mistral:m1"
        assert stub.session_state["error"] is None


class TestComposerStrip:
    """The controls belong under the input box, and on every screen.

    They used to be a bar across the top of the page, which failed twice: it sat
    in the band Streamlit's own full-width header takes the clicks for, and on
    the landing screen the picker inside it did not appear at all — so the one
    screen where a new user has to choose a model was the one screen without a
    way to choose one. tools/render_check.py holds the geometry; these hold the
    structure that geometry depends on.
    """

    @staticmethod
    def _containers(stub):
        return [key for name, key in stub.events if name == "container"]

    @staticmethod
    def _index(stub, name, key=None):
        return next(
            position for position, event in enumerate(stub.events)
            if event[0] == name and (key is None or event[1] == key)
        )

    def two_providers(self, monkeypatch, session, **kwargs):
        mistral = ScriptedProvider([], name="mistral", models=("mistral-small-latest",))
        zen = ScriptedProvider([], name="opencode",
                               models=("deepseek-v4-flash-free", "big-pickle"))
        return run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                       session=session, opencode=True, **kwargs)

    def test_the_controls_live_in_the_strip_under_the_input(self, monkeypatch):
        stub, _m = self.two_providers(monkeypatch, {"messages": [], "processing": False})
        assert "composer-strip" in self._containers(stub)
        assert "topbar" not in self._containers(stub)
        # One container, not a strip wrapping a row: two of them meant two sets of
        # layout rules for two elements whose identity depends on where Streamlit
        # hangs the `st-key-…` class, and the inner rule outranked the outer one.
        assert "controls" not in self._containers(stub)

    def test_the_strip_is_rendered_after_the_input(self, monkeypatch):
        """Order is the whole point: rendered before it, this is a top bar again."""
        stub, _m = self.two_providers(monkeypatch, {"messages": [], "processing": False})
        assert (self._index(stub, "container", "composer-strip")
                > self._index(stub, "chat_input"))

    def test_the_picker_is_there_before_the_first_question(self, monkeypatch):
        """Reported from the running app: the picker did not show up on the
        landing page at all — not until a prompt had been entered."""
        stub, _m = self.two_providers(monkeypatch, {"messages": [], "processing": False})
        assert ("popover", "mistral-small-latest") in stub.events
        assert [key for key in stub.button_labels if str(key).startswith("pick-")]

    def test_the_picker_is_still_there_mid_conversation(self, monkeypatch):
        session = {
            "messages": [{"role": "user", "text": "hi", "attachments": []}],
            "processing": False,
        }
        stub, _m = self.two_providers(monkeypatch, session)
        assert ("popover", "mistral-small-latest") in stub.events

    def test_clear_appears_only_once_there_is_something_to_clear(self, monkeypatch):
        stub, _m = self.two_providers(monkeypatch, {"messages": [], "processing": False})
        assert "clear" not in stub.button_labels

        session = {
            "messages": [{"role": "user", "text": "hi", "attachments": []}],
            "processing": False,
        }
        stub, _m = self.two_providers(monkeypatch, session)
        assert "clear" in stub.button_labels

    def test_clear_empties_the_conversation(self, monkeypatch):
        session = {
            "messages": [{"role": "user", "text": "hi", "attachments": []}],
            "processing": False,
            "notice": "stale",
            "failed_over": True,
        }
        stub, _m = self.two_providers(monkeypatch, session, buttons={"clear": True})
        assert stub.session_state["messages"] == []
        assert stub.session_state["notice"] == ""
        assert stub.session_state["failed_over"] is False

    def test_nothing_under_the_input_but_controls(self, monkeypatch):
        """The caveat line is gone, and nothing may quietly replace it.

        It was a popover, then three paragraphs under the starter cards, then one
        11px line beside the model name, and every version was a permanent fixture
        for something read once. What is under the input now is Clear and the model
        picker: two controls, no prose. This fails if any of it comes back.
        """
        stub, _m = self.two_providers(
            monkeypatch,
            {"messages": [{"role": "user", "text": "hi", "attachments": []}],
             "processing": False},
        )
        assert not any(
            "ai-disclaimer" in html or "can make mistakes" in html
            for html in stub.markdown_html
        )

    def test_the_input_asks_for_no_character_counter(self, monkeypatch):
        """`max_chars` is the only thing that puts "15/8000" inside the box.

        Asserted on the call rather than on CSS: hiding the counter would mean
        naming a Streamlit test id this repo cannot see, and that rule would fail
        silently the day it changed. Not asking for it cannot fail that way.
        """
        stub, _m = self.two_providers(monkeypatch, {"messages": [], "processing": False})
        assert stub.chat_input_kwargs == {}, (
            f"st.chat_input was passed {stub.chat_input_kwargs}; max_chars puts a "
            "character counter in the box"
        )


class TestToollessModels:
    """Free models that cannot call tools still answer, from a single retrieval."""

    def session(self, model):
        return {
            "messages": [
                {"role": "user", "text": "what is my storage quota", "attachments": []}
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
                          "attachments": []}],
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
        # It must say what to do, without pointing at a control by position —
        # the error card now carries a one-click switch of its own.
        assert "Switch to another model" in llm.classify(
            self._payment_required()
        ).user_message

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

    def test_the_notice_does_not_claim_an_answer_that_has_not_happened(
        self, monkeypatch
    ):
        """It used to say the answer "came from" a model that had not run yet."""
        mistral = ScriptedProvider([], name="mistral", models=("m1",),
                                   error=self._payment_required())
        zen = ScriptedProvider([], name="opencode", models=("z1",))
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=self.session(), opencode=True)
        assert "Retrying with z1" in stub.session_state["notice"]
        assert "came from" not in stub.session_state["notice"]
        assert stub.session_state["switched_from"] == ("m1", "quota")

    def test_the_notice_turns_past_tense_once_the_answer_lands(self, monkeypatch):
        """The state a failover rerun arrives in: switched, and about to answer."""
        zen = ScriptedProvider([[event("Zen answered.")]], name="opencode",
                               models=("z1",))
        mistral = ScriptedProvider([], name="mistral", models=("m1",))
        session = self.session() | {
            "model": "opencode:z1",
            "failed_over": True,
            "switched_from": ("Mistral · m1", "quota"),
            "notice": "Mistral · m1 is unavailable (out of credit). Retrying…",
        }
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=session, opencode=True)
        notice = stub.session_state["notice"]
        assert "was unavailable (out of credit)" in notice
        assert "z1 answered instead" in notice
        # And it points at where the picker actually is. It said "the button at
        # the top left" for as long as there was a top left to point at.
        assert "under the input box" in notice
        assert "top left" not in notice
        assert stub.session_state["switched_from"] is None
        assert stub.session_state["error"] is None

    def test_a_failed_failover_leaves_no_notice_contradicting_the_error(
        self, monkeypatch
    ):
        """A "retrying with Zen…" banner above "could not complete that request"
        is the UI arguing with itself. One of them has to go, and it is not the
        error."""
        zen = ScriptedProvider([], name="opencode", models=("z1",),
                               error=self._payment_required())
        mistral = ScriptedProvider([], name="mistral", models=("m1",))
        session = self.session() | {
            "model": "opencode:z1",
            "failed_over": True,
            "switched_from": ("Mistral · m1", "quota"),
            "notice": "Mistral · m1 is unavailable (out of credit). Retrying…",
        }
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=session, opencode=True)
        assert stub.session_state["error"], "the second failure must surface"
        assert stub.session_state["notice"] == ""
        assert stub.session_state["switched_from"] is None
        assert "opencode:z1" in stub.session_state["error_detail"], (
            "the details must name the model that actually failed"
        )

    def test_the_error_card_offers_the_switch_it_tells_you_to_make(self, monkeypatch):
        """Advice to "switch to another model" is useless if the control is at the
        other end of the page — and worse than useless if that control is the one
        that failed to render."""
        mistral = ScriptedProvider([], name="mistral", models=("m1",))
        zen = ScriptedProvider([], name="opencode", models=("z1",))
        session = self.session() | {
            "processing": False,
            "error": "This model is out of credit or its quota is used up.",
            "error_detail": "HTTP 402",
        }
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=session, opencode=True)
        assert stub.button_labels.get("switch-model") == "→ Use z1"

    def test_taking_that_switch_reruns_the_question_on_the_new_model(self, monkeypatch):
        mistral = ScriptedProvider([], name="mistral", models=("m1",))
        zen = ScriptedProvider([], name="opencode", models=("z1",))
        session = self.session() | {
            "processing": False, "error": "out of credit", "error_detail": "HTTP 402",
            "failed_over": True,
        }
        stub, _m = run_app(monkeypatch, client=mistral, extra={"opencode": zen},
                           session=session, opencode=True,
                           buttons={"switch-model": True})
        assert stub.session_state["model"] == "opencode:z1"
        assert stub.session_state["processing"] is True
        assert stub.session_state["error"] is None
        assert stub.session_state["failed_over"] is False

    def test_no_switch_button_when_there_is_nowhere_to_switch_to(self, monkeypatch):
        provider = ScriptedProvider([], models=("m1",))
        session = self.session() | {
            "processing": False, "error": "boom", "error_detail": "x",
        }
        stub, _m = run_app(monkeypatch, client=provider, session=session)
        assert "switch-model" not in stub.button_labels
        assert "retry" in stub.button_labels

    def test_a_clean_answer_clears_a_notice_from_an_earlier_turn(self, monkeypatch):
        provider = ScriptedProvider([[event("Fresh answer.")]], models=("m1",))
        session = self.session() | {"notice": "left over from two turns ago"}
        stub, _m = run_app(monkeypatch, client=provider, session=session)
        assert stub.session_state["notice"] == ""

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
                {"role": "user", "text": "how do I submit a job", "attachments": []},
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
        assert "docs.rcc.uchicago.edu/slurm/sbatch/" in rendered
        assert "docs/slurm/sbatch.md" not in rendered

    def test_user_html_is_escaped(self, monkeypatch):
        session = {
            "messages": [
                {
                    "role": "user",
                    "text": "<img src=x onerror=alert(1)>",
                    "attachments": [],
                }
            ],
            "processing": False,
        }
        stub, _module = run_app(monkeypatch, session=session)
        html = "\n".join(stub.markdown_html)
        assert "<img src=x" not in html
        assert "&lt;img" in html


class TestAttachments:
    """More than one file, and the chips where the composer is.

    Two bugs lived here. The uploader took one file and the app ignored anything
    offered while one was already held, so attaching a second did nothing at all and
    said nothing about why; and the chip rendered wherever the script reached it,
    which put it in the middle of the page, a long way from the box it belongs to.
    """

    class Upload:
        """What st.file_uploader hands back per file."""

        def __init__(self, name, data):
            self.name = name
            self._data = data
            self.size = len(data)

        def getvalue(self):
            return self._data

    def app(self, monkeypatch, uploads, session=None, **stub_kwargs):
        mistral = ScriptedProvider([], name="mistral", models=("mistral-small-latest",))
        return run_app(
            monkeypatch, client=mistral, upload=uploads,
            session={"messages": [], "processing": False, **(session or {})},
            **stub_kwargs,
        )

    def test_the_uploader_asks_for_more_than_one_file(self, monkeypatch):
        stub, _m = self.app(monkeypatch, [])
        assert stub.uploader_kwargs.get("accept_multiple_files") is True

    def test_the_uploader_does_not_filter_by_extension(self, monkeypatch):
        """`type=` is what refused a pasted screenshot: app.js names one, and no
        list of extensions was ever going to contain that name. The bytes decide."""
        stub, _m = self.app(monkeypatch, [])
        assert "type" not in stub.uploader_kwargs

    def test_two_files_are_both_held(self, monkeypatch):
        stub, _m = self.app(monkeypatch, [
            self.Upload("slurm-1.out", b"OOM killed\n"),
            self.Upload("submit.sbatch", b"#SBATCH -p caslake\n"),
        ])
        names = [item.filename for item in stub.session_state["attachments"]]
        assert names == ["slurm-1.out", "submit.sbatch"]

    def test_the_same_file_is_not_held_twice_across_reruns(self, monkeypatch):
        """The uploader reports its files again on every rerun. Without an identity
        check one attachment became one per interaction with the page.

        Both runs go through the app, rather than the second one being handed a
        hand-built attachment: what identifies a file is the app's business and has
        changed once already, and a fixture that mints its own identity stops
        exercising the check the moment that happens — which is how this test came to
        pass a file the app would have recognised.
        """
        stub, _m = self.app(monkeypatch, [self.Upload("run.err", b"segfault\n")])
        assert len(stub.session_state["attachments"]) == 1

        # The rerun: same widget, same file, reported again.
        again, _m = self.app(
            monkeypatch, [self.Upload("run.err", b"segfault\n")],
            session=dict(stub.session_state),
        )
        assert len(again.session_state["attachments"]) == 1, (
            "the same file was attached twice by a rerun that changed nothing"
        )

    def test_a_rejected_file_does_not_take_the_others_with_it(self, monkeypatch):
        """A bad file used to reset the whole widget, dropping the good ones too."""
        stub, _m = self.app(monkeypatch, [
            self.Upload("good.txt", b"readable\n"),
            self.Upload("a.out", b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 24),
        ])
        names = [item.filename for item in stub.session_state["attachments"]]
        assert names == ["good.txt"]
        assert any("does not look like text" in warning for warning in stub.warnings)

    def test_the_chips_are_rendered_in_their_own_pinned_container(self, monkeypatch):
        stub, _m = self.app(monkeypatch, [self.Upload("notes.md", b"# hi\n")])
        keys = [key for name, key in stub.events if name == "container"]
        assert "attachments" in keys

    def test_the_chips_are_rendered_after_the_input_box(self, monkeypatch):
        """Pinned to the composer, like the controls strip. Rendered where the
        script first hears about the upload, they landed in the middle of the page."""
        stub, _m = self.app(monkeypatch, [self.Upload("notes.md", b"# hi\n")])
        names = [name for name, _key in stub.events]
        order = [
            index for index, (name, key) in enumerate(stub.events)
            if name == "chat_input" or (name == "container" and key == "attachments")
        ]
        assert names.count("chat_input") == 1
        assert len(order) == 2 and order[0] < order[1], stub.events

    def test_an_image_on_a_text_only_model_says_so(self, monkeypatch):
        """An image sent to a text-only model is a 4xx. Said next to the picture,
        beside the picker that can fix it, rather than discovered in the answer."""
        png = b"\x89PNG\r\n\x1a\n" + b"x" * 40
        stub, _m = self.app(monkeypatch, [self.Upload("pasted-image.png", png)])
        assert any("cannot read images" in caption for caption in stub.captions)

    def test_a_dismissed_file_does_not_come_back_on_the_next_rerun(self, monkeypatch):
        """The ✕ has to outlive the rerun it triggers.

        Nothing in this app can reach into the uploader widget and remove a file from
        it, so the widget goes on reporting a dismissed one on every rerun. Without a
        record of what was dismissed the chip disappeared and was rebuilt on the next
        frame, which is a control that undoes itself.
        """
        stub, _m = self.app(
            monkeypatch, [self.Upload("slurm-1.out", b"OOM killed\n")],
            buttons={"drop-attachment-0": True},
        )
        assert stub.session_state["attachments"] == []

        # The rerun that ✕ ends in: the same widget, still holding the same file.
        after, _m = self.app(
            monkeypatch, [self.Upload("slurm-1.out", b"OOM killed\n")],
            session=dict(stub.session_state),
        )
        assert [item.filename for item in after.session_state["attachments"]] == [], (
            "the dismissed file was re-attached by the rerun the dismissal caused"
        )

    def test_the_chip_that_was_dismissed_is_the_one_that_goes(self, monkeypatch):
        """Every chip needs its own key and its own index.

        One key for the row — which is what a single-attachment composer had — makes
        every ✕ the same button: Streamlit refuses the duplicate, or the first file
        goes whichever chip was clicked.
        """
        stub, _m = self.app(monkeypatch, [
            self.Upload("keep.out", b"still wanted\n"),
            self.Upload("drop.out", b"not wanted\n"),
        ], buttons={"drop-attachment-1": True})
        assert [item.filename for item in stub.session_state["attachments"]] == [
            "keep.out",
        ]

    def test_two_different_files_with_one_name_are_both_held(self, monkeypatch):
        """A name is not an identity, so an edited file attaches beside the old one.

        Keyed on the name alone the second of these is dropped without a word — the
        same failure as the guard that dropped every file offered while one was
        already held. Not a corner case: every screenshot pasted into the box arrives
        called pasted-image.png, and every cluster has more than one config.yaml.
        """
        stub, _m = self.app(monkeypatch, [
            self.Upload("submit.sbatch", b"#SBATCH -p caslake\n"),
            self.Upload("submit.sbatch", b"#SBATCH -p caslake\n#SBATCH --mem=64G\n"),
        ])
        held = stub.session_state["attachments"]
        assert len(held) == 2, "the edited file was taken for the one already held"
        assert "--mem=64G" in held[1].text

    def test_sending_the_turn_hands_the_files_over_and_empties_the_composer(
        self, monkeypatch
    ):
        """Both files travel with the question, and none is left in the composer.

        A turn used to carry one attachment, so the second was not merely unsent — it
        was unsendable. And a file left behind in the composer is re-sent, and paid
        for, with every later question in the conversation.
        """
        stub, _m = self.app(
            monkeypatch,
            [self.Upload("slurm-1.out", b"OOM killed\n"),
             self.Upload("submit.sbatch", b"#SBATCH -p caslake\n")],
            chat_input="why did this die?",
        )
        sent = stub.session_state["messages"][-1]
        assert [item.filename for item in sent["attachments"]] == [
            "slurm-1.out", "submit.sbatch",
        ]
        assert stub.session_state["attachments"] == []
        assert stub.session_state["uploader_key"] == 1, (
            "the widget has to be reset, or it reports the sent files again"
        )

    def test_a_dismissal_does_not_outlive_the_turn_it_was_made_in(self, monkeypatch):
        """Dismissed keys name files in a widget that is gone once a turn is sent.

        Kept past the send, they refuse the same file for the rest of the
        conversation: a paperclip that does nothing, for a file the user attached
        successfully two questions ago.
        """
        data = b"OOM killed\n"
        dismissed, _m = self.app(
            monkeypatch, [self.Upload("slurm-1.out", data)],
            buttons={"drop-attachment-0": True},
        )
        assert dismissed.session_state["dropped_uploads"], "nothing was remembered"

        sent, _m = self.app(
            monkeypatch, [self.Upload("slurm-1.out", data)],
            session=dict(dismissed.session_state), chat_input="why did this die?",
        )
        assert sent.session_state["messages"][-1]["attachments"] == []
        # Emptied, whatever it is kept in — a set of keys once, counts per key now.
        assert not sent.session_state["dropped_uploads"]

        # The next question, and the same file offered again to a fresh widget.
        again, _m = self.app(
            monkeypatch, [self.Upload("slurm-1.out", data)],
            session=dict(sent.session_state) | {"processing": False},
        )
        assert [item.filename for item in again.session_state["attachments"]] == [
            "slurm-1.out",
        ], "a dismissal from an earlier turn still refuses the file"


class TestVisionModels:
    """A pasted screenshot is only useful if the model is handed the picture.

    Pasting one used to do nothing whatsoever. Now it attaches, and whether the bytes
    travel is `config.sees_images`' decision — an image sent to a text-only model is a
    4xx, not a polite decline. These drive the whole app rather than `history.build`
    directly, because the wiring is half the fix: app.py has to ask that question and
    hand the answer to the builder.
    """

    PNG = b"\x89PNG\r\n\x1a\n" + b"IHDR" + b"pixels" * 8

    def session(self, model_key):
        from sage import files as files_mod  # noqa: PLC0415

        shot, error = files_mod.process("pasted-image.png", self.PNG)
        assert error is None, error
        return {
            "messages": [{"role": "user", "text": "what does this error mean?",
                          "attachments": [shot]}],
            "processing": True,
            "model": model_key,
        }

    def content_sent(self, monkeypatch, model_id):
        """The user turn as the provider received it."""
        provider = ScriptedProvider([[event("That is an out-of-memory kill.")]],
                                    name="mistral", models=(model_id,))
        run_app(monkeypatch, client=provider,
                session=self.session(f"mistral:{model_id}"))
        assert provider.calls == 1
        return provider.sent[0][-1]["content"]

    def test_a_vision_model_is_handed_the_picture(self, monkeypatch):
        content = self.content_sent(monkeypatch, "pixtral-12b-latest")
        assert isinstance(content, list), f"the image never became a part: {content!r}"
        assert [part["type"] for part in content] == ["text", "image_url"]
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert "pasted-image.png" in content[0]["text"]

    def test_a_text_only_model_is_told_about_the_file_instead(self, monkeypatch):
        """Held back deliberately: the request would come back 4xx, and a 4xx is a
        worse answer than "there is an image here that I cannot read"."""
        content = self.content_sent(monkeypatch, "mistral-small-latest")
        assert isinstance(content, str), f"bytes went to a text-only model: {content!r}"
        assert "pasted-image.png" in content
        assert "base64" not in content


class TestComposerReset:
    """Clearing the conversation has to clear the box too.

    The text in Streamlit's chat input is client-side state that Python only reads on
    submit, so nothing in app.py can empty it. Clearing therefore wiped the transcript
    and left the last question sitting over the starter cards as if it were about to be
    sent. app.py publishes a token; app.js does the emptying.
    """

    def app(self, monkeypatch, session=None, **kwargs):
        client = ScriptedProvider([], name="mistral", models=("m1",))
        return run_app(monkeypatch, client=client,
                       session={"processing": False, **(session or {})}, **kwargs)

    def test_the_token_is_published_for_app_js(self, monkeypatch):
        stub, _m = self.app(monkeypatch, {"messages": []})
        assert any(
            'id="composer-reset"' in html and "data-token=" in html
            for html in stub.markdown_html
        ), "app.js has nothing to watch"

    def test_clearing_moves_the_token(self, monkeypatch):
        session = {"messages": [{"role": "user", "text": "hi", "attachments": []}]}
        before, _m = self.app(monkeypatch, session)
        start = before.session_state["clear_token"]
        after, _m2 = self.app(monkeypatch, session, buttons={"clear": True})
        assert after.session_state["clear_token"] == start + 1

    def test_an_ordinary_run_leaves_the_token_alone(self, monkeypatch):
        """It must move only on a clear: app.js empties the box whenever it changes,
        and a token that drifted would delete a half-typed question."""
        session = {"messages": [{"role": "user", "text": "hi", "attachments": []}],
                   "clear_token": 7}
        stub, _m = self.app(monkeypatch, session)
        assert stub.session_state["clear_token"] == 7


class TestCitationApparatus:
    """Sources and Related used to be two rows of identical chips, which left the reader
    unable to tell what an answer was built from from what it merely suggests next — and
    as wrapping rows they were ragged, because a flex row whose first item is the label
    indents its first line only."""

    @staticmethod
    def session(count=3):
        return {
            "messages": [
                {"role": "user", "text": "what are the storage quotas", "attachments": []},
                {
                    "role": "assistant",
                    "text": "Your /home quota is 30 GB.",
                    "sources": [
                        {
                            "id": f"docs/storage/main.md#q{n}",
                            "label": f"Storage System Layout — Quota rule {n}",
                            "url": f"https://example.test/storage/#q{n}",
                            "source": "docs" if n % 2 else "web",
                        }
                        for n in range(count)
                    ],
                    "rating": None,
                },
            ],
            "processing": False,
        }

    @staticmethod
    def markup(stub):
        """The rendered markup only. `markdown_html` also carries the injected
        stylesheet, and app.css names every class asserted on below — so an
        unscoped search finds `.source-list` in the CSS and passes on a page that
        rendered none."""
        return "\n".join(
            html for html in stub.markdown_html if "<style" not in html
        )

    def render(self, monkeypatch, count=3):
        stub, _module = run_app(monkeypatch, session=self.session(count))
        return self.markup(stub)

    def test_sources_are_a_numbered_list_one_per_line(self, monkeypatch):
        html = self.render(monkeypatch)
        assert html.count('class="source-item"') == 3
        assert 'class="source-list"' in html

    def test_the_chip_layout_is_gone(self, monkeypatch):
        """Not a shared class with a different label — the layout has to say it."""
        html = self.render(monkeypatch)
        assert "source-chip" not in html

    def test_no_list_element_is_used(self, monkeypatch):
        """Streamlit styles markdown lists, and a `[data-testid=…] ol` rule outranks a
        single class — so an `<ol>` here would inherit Streamlit's list indent in the
        app while the render harness, which has no list rules at all, showed it
        perfectly. Divs inherit nothing and a CSS counter numbers them just as well."""
        html = self.render(monkeypatch)
        for tag in ("<ol", "<ul", "<li>", "<li "):
            assert tag not in html, f"{tag} rendered in the citation markup"

    def test_every_citation_link_opens_in_a_new_tab_safely(self, monkeypatch):
        html = self.render(monkeypatch)
        links = [m for m in html.split("<a ") if "source-link" in m[:40]]
        assert links, "no citation links rendered"
        for link in links:
            head = link[: link.index(">")]
            assert 'target="_blank"' in head
            assert 'rel="noopener noreferrer"' in head

    def test_the_source_kind_badge_survives(self, monkeypatch):
        assert 'class="source-kind">docs<' in self.render(monkeypatch)

    def test_a_label_is_escaped(self, monkeypatch):
        session = self.session(1)
        session["messages"][1]["sources"][0]["label"] = "<script>x</script>"
        stub, _module = run_app(monkeypatch, session=session)
        html = self.markup(stub)
        assert "<script>x</script>" not in html
        assert "&lt;script&gt;" in html

    def test_related_is_absent_when_there_is_nothing_to_relate(self, monkeypatch):
        """The Related block is optional; an empty one would render a bare label."""
        html = self.render(monkeypatch)
        if "related-list" in html:
            assert 'class="related-item"' in html

    def test_nothing_renders_without_citations(self, monkeypatch):
        session = self.session(1)
        session["messages"][1]["sources"] = []
        stub, _module = run_app(monkeypatch, session=session)
        html = self.markup(stub)
        assert "source-list" not in html
        assert "sources-label" not in html


class TestDistinctDestinations:
    """A citation and a lead are both a place to click, so two of them are only two if
    they land somewhere different.

    Reported from the app: asking who directs the RCC cited "Our Team" and then offered
    "Our Team (part 2)", "(part 3)" and "(part 4)" under Related — four links, one page,
    and the three leads pointed at the citation directly above them. The page is
    windowed for indexing at 2400 characters, and every one of its thirteen windows
    carries the page's own URL because a scraped page has no anchors to deep-link to.
    Filtering leads by chunk id could not see that; the id was what differed.
    """

    @staticmethod
    def source(module, chunk_id):
        chunk = module.CORPUS.chunk(chunk_id)
        assert chunk is not None, f"{chunk_id} is not in the bundled corpus"
        return {
            "id": chunk.id,
            "label": chunk.label,
            "url": chunk.url,
            "source": chunk.source,
        }

    def test_the_reported_answer_offers_no_lead_back_to_its_own_citation(
        self, monkeypatch
    ):
        _stub, module = run_app(monkeypatch)
        cited = self.source(module, "web/about-rcc_our-team.txt#1")
        related = module.related_sections([cited])
        assert [item["url"] for item in related] == []

    def test_every_lead_is_somewhere_the_reader_is_not_already_being_sent(
        self, monkeypatch
    ):
        """Swept over the whole corpus, not just the page that was reported: 62 of the
        536 chunks that produce a Related list led back to their own citation, and 36
        listed one destination twice."""
        _stub, module = run_app(monkeypatch)
        for chunk in module.CORPUS.chunks:
            cited = self.source(module, chunk.id)
            urls = [item["url"] for item in module.related_sections([cited])]
            assert len(urls) == len(set(urls)), f"{chunk.id} repeats a lead"
            assert chunk.url not in urls, f"{chunk.id} leads back to itself"

    def test_leads_still_reach_the_other_sections_of_a_real_page(self, monkeypatch):
        """The rule above is satisfied by showing nothing, so hold the feature down
        too: an anchored docs page still offers its siblings."""
        _stub, module = run_app(monkeypatch)
        cited = self.source(module, "docs/storage/main.md#quotas")
        related = module.related_sections([cited])
        assert len(related) == 3
        assert all(item["url"].startswith("https://") for item in related)

    def test_the_sources_strip_lists_each_destination_once(self, monkeypatch):
        """Same defect one row up. `search_docs` may return two windows of one page
        (MAX_PER_PAGE allows two sections of any page), and for a scraped page those
        two are one link — so "who is the director of the RCC" cited four sections
        that were two pages."""
        _stub, module = run_app(monkeypatch)
        from sage import tools

        _context, chunks = tools.gather_context(
            module.INDEX, "who is the director of the rcc"
        )
        assert len(chunks) > 1, "expected a multi-section retrieval to test against"
        urls = [item["url"] for item in module.citations(chunks)]
        assert len(urls) == len(set(urls))


def configure(monkeypatch, **values):
    """Override settings the way the app reads them.

    `sage/config.py` resolves every setting at import time, so `monkeypatch.setenv`
    after the module is loaded changes nothing — the same import-time coupling that
    made this suite depend on the developer's shell. Setting the attribute is what
    actually takes effect, and monkeypatch puts it back.
    """
    for name, value in values.items():
        monkeypatch.setattr(config, name, value)


def with_auth(stub, **user):
    """A stub with an `[auth]` block configured, and optionally someone signed in."""
    stub.secrets = SimpleNamespace(
        get=lambda key, default="": {"client_id": "x"} if key == "auth" else default
    )
    if user:
        stub.user = SimpleNamespace(**user)
    return stub


class TestUsageLimits:
    """The gate in `start_new_turn()`, the one place a turn can begin.

    The arithmetic is covered in `tests/test_limits.py` without a browser. What
    matters here is that a refusal leaves the app in a state a reader can understand.
    """

    def test_a_refused_turn_leaves_the_transcript_alone(self, monkeypatch):
        """The failure to avoid is a question on screen with no answer under it.

        Appending the message and then declining to process it produces exactly the
        dead end the turn loop's own comments are about, so the check runs before any
        state is touched.
        """
        configure(monkeypatch, RATE_BURST=1, RATE_REFILL_SECONDS=600.0,
                  DAILY_TURNS=0, CALL_BUDGET=0)
        stub, _ = run_app(monkeypatch, chat_input=None)
        import app  # noqa: PLC0415

        with pytest.raises(stub_streamlit.Rerun):
            app.start_new_turn("first question")      # spends the only token
        stub.session_state["processing"] = False
        before = list(stub.session_state["messages"])

        with pytest.raises(stub_streamlit.Rerun):
            app.start_new_turn("second question")     # refused

        assert stub.session_state["messages"] == before, "nothing was appended"
        assert not stub.session_state["processing"], "no turn was started"
        assert "minute" in stub.session_state["notice"], "and it says how long"

    def test_the_budget_refusal_blames_the_deployment(self, monkeypatch):
        """A reader on their first question must not be told they asked too much."""
        configure(monkeypatch, RATE_BURST=0, DAILY_TURNS=0, CALL_BUDGET=1)
        stub, _ = run_app(monkeypatch, chat_input=None)
        import app  # noqa: PLC0415

        # The same clock the app uses. Spending at 0.0 while the app checks at
        # `time.monotonic()` puts the two more than a window apart, and the budget
        # legitimately rolls over between them.
        app.get_limiter().record_calls(1, time.monotonic())
        with pytest.raises(stub_streamlit.Rerun):
            app.start_new_turn("a question")

        assert stub.session_state["messages"] == []
        assert "deployment" in stub.session_state["notice"]

    def test_limits_configured_off_let_everything_through(self, monkeypatch):
        configure(monkeypatch, RATE_BURST=0, RATE_REFILL_SECONDS=0.0,
                  DAILY_TURNS=0, CALL_BUDGET=0)
        stub, _ = run_app(monkeypatch, chat_input=None)
        import app  # noqa: PLC0415

        for index in range(25):
            with pytest.raises(stub_streamlit.Rerun):
                app.start_new_turn(f"question {index}")
            stub.session_state["processing"] = False
        assert len(stub.session_state["messages"]) == 25

    def test_each_session_gets_its_own_allowance(self, monkeypatch):
        """Anonymous identity is per session, so one tab cannot spend another's."""
        configure(monkeypatch, RATE_BURST=1, RATE_REFILL_SECONDS=600.0,
                  DAILY_TURNS=0, CALL_BUDGET=0)
        stub, _ = run_app(monkeypatch, chat_input=None)
        import app  # noqa: PLC0415

        first = app.whoami()
        stub.session_state.pop("session_id")
        assert app.whoami() != first


class TestLoginGate:
    """Auth is opt-in, and neither way of misconfiguring it may lock people out of
    an otherwise working app."""

    def test_the_flag_alone_does_not_gate(self, monkeypatch, caplog):
        """`SAGE_REQUIRE_LOGIN` with no `[auth]` block would send every reader to a
        sign-in button that cannot work — including whoever set the flag. It fails
        open, and says so loudly enough to be found in the logs."""
        configure(monkeypatch, REQUIRE_LOGIN=True)
        with caplog.at_level("ERROR"):
            _stub, module = run_app(monkeypatch, chat_input=None)
        assert module is not None, "the app rendered rather than stopping"
        assert any("running OPEN" in record.message for record in caplog.records)

    def test_a_configured_gate_stops_an_anonymous_visitor(self, monkeypatch):
        configure(monkeypatch, REQUIRE_LOGIN=True)
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        stub = with_auth(stub_streamlit.install(chat_input=None))
        with pytest.raises(stub_streamlit.Stop):
            import app  # noqa: F401,PLC0415
        # Stopping is not enough on its own: a stop with nothing on screen is a
        # blank page, which reads as broken rather than as private.
        assert "Sign in" in stub.button_labels, "there is a way in"
        assert not any(kind == "chat_input" for kind, _ in stub.events), (
            "and the composer never rendered"
        )

    def test_a_wrong_domain_is_refused(self, monkeypatch):
        configure(monkeypatch, REQUIRE_LOGIN=True,
                  ALLOWED_EMAIL_DOMAINS=("uchicago.edu",))
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        stub = with_auth(
            stub_streamlit.install(chat_input=None),
            is_logged_in=True, email="someone@example.com", sub="abc",
        )
        with pytest.raises(stub_streamlit.Stop):
            import app  # noqa: F401,PLC0415
        assert any("outside the domains" in text for text in stub.errors)

    def test_the_right_domain_gets_in(self, monkeypatch):
        configure(monkeypatch, REQUIRE_LOGIN=True,
                  ALLOWED_EMAIL_DOMAINS=("uchicago.edu",))
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        with_auth(
            stub_streamlit.install(chat_input=None),
            is_logged_in=True, email="someone@uchicago.edu", sub="abc",
        )
        import app  # noqa: PLC0415

        assert app.whoami() == "user:abc", "limits key off the account, not the tab"


class TestAllowedDomains:
    @pytest.mark.parametrize("email,domains,allowed", [
        ("a@uchicago.edu", ("uchicago.edu",), True),
        ("a@UChicago.EDU", ("uchicago.edu",), True),
        ("a@example.com", ("uchicago.edu",), False),
        # The trap: a domain check by substring lets anyone register the suffix.
        ("a@notuchicago.edu", ("uchicago.edu",), False),
        ("a@uchicago.edu.evil.com", ("uchicago.edu",), False),
        ("a@cs.uchicago.edu", ("cs.uchicago.edu", "uchicago.edu"), True),
        ("", ("uchicago.edu",), False),
        ("anyone@anywhere.test", (), True),
    ])
    def test_domains_are_matched_whole(self, monkeypatch, email, domains, allowed):
        monkeypatch.setattr(config, "ALLOWED_EMAIL_DOMAINS", domains)
        assert config.email_allowed(email) is allowed
