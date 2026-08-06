"""Streaming and error handling, exercised against a fake Mistral SDK surface."""

from types import SimpleNamespace

import pytest

from sage import llm


def event(content=None, tool_calls=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(data=SimpleNamespace(choices=[SimpleNamespace(delta=delta)]))


def call(index=0, cid=None, name=None, arguments=None):
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=cid, function=function)


class FakeClient:
    """Mimics `client.chat.stream(...)`, optionally failing the first N calls."""

    def __init__(self, events, failures=0, error=None):
        self.events = events
        self.failures = failures
        self.error = error or RuntimeError("boom")
        self.calls = 0
        self.chat = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        if self.calls <= self.failures:
            raise self.error
        return iter(self.events)


class TestTurn:
    def test_text_deltas_stream_and_accumulate(self):
        turn = llm.Turn(stream=iter([event("Hello "), event("world")]))
        assert list(turn.deltas()) == ["Hello ", "world"]
        assert turn.text == "Hello world"
        assert turn.tool_calls == []
        assert turn.finished

    def test_consume_blocks_and_returns_the_same_turn(self):
        """The single reader that lets the post-tool answer stream too."""
        turn = llm.Turn(stream=iter([event("a"), event("b")])).consume()
        assert turn.text == "ab"

    def test_tool_call_arguments_are_reassembled_across_chunks(self):
        events = [
            event(tool_calls=[call(0, "id-1", "search_docs", '{"que')]),
            event(tool_calls=[call(0, None, None, 'ry": "gpu jobs"}')]),
        ]
        turn = llm.Turn(stream=iter(events)).consume()
        assert turn.tool_calls == [
            {"id": "id-1", "name": "search_docs", "input": {"query": "gpu jobs"}}
        ]

    def test_parallel_tool_calls_are_kept_separate(self):
        events = [
            event(tool_calls=[call(0, "a", "search_docs", '{"query":"x"}')]),
            event(tool_calls=[call(1, "b", "read_doc", '{"path":"docs/a.md"}')]),
        ]
        turn = llm.Turn(stream=iter(events)).consume()
        assert [c["name"] for c in turn.tool_calls] == ["search_docs", "read_doc"]
        assert turn.tool_calls[1]["input"] == {"path": "docs/a.md"}

    def test_text_and_tool_calls_can_arrive_together(self):
        events = [
            event("Let me look. "),
            event(tool_calls=[call(0, "a", "search_docs", '{"query":"x"}')]),
        ]
        turn = llm.Turn(stream=iter(events)).consume()
        assert turn.text == "Let me look. "
        assert len(turn.tool_calls) == 1

    def test_unparseable_arguments_degrade_to_empty_input(self):
        events = [event(tool_calls=[call(0, "a", "search_docs", "{not json")])]
        turn = llm.Turn(stream=iter(events)).consume()
        assert turn.tool_calls[0]["input"] == {}

    def test_nameless_tool_calls_are_discarded(self):
        turn = llm.Turn(stream=iter([event(tool_calls=[call(0, "a", None, "{}")])]))
        turn.consume()
        assert turn.tool_calls == []

    def test_empty_and_malformed_events_are_skipped(self):
        events = [
            SimpleNamespace(data=None),
            SimpleNamespace(data=SimpleNamespace(choices=[])),
            event("ok"),
        ]
        assert llm.Turn(stream=iter(events)).consume().text == "ok"

    def test_list_content_parts_are_joined(self):
        turn = llm.Turn(stream=iter([event(["a", SimpleNamespace(text="b")])]))
        assert turn.consume().text == "ab"

    def test_stream_failures_are_classified(self):
        def explode():
            yield event("partial")
            raise TimeoutError("connection timed out")

        turn = llm.Turn(stream=explode())
        with pytest.raises(llm.AssistantError) as caught:
            list(turn.deltas())
        assert caught.value.kind == "network"

    def test_as_message_shapes_the_tool_call_turn(self):
        events = [event("hm", [call(0, "id-9", "read_doc", '{"path":"docs/a.md#b"}')])]
        message = llm.Turn(stream=iter(events)).consume().as_message()
        assert message["role"] == "assistant"
        assert message["content"] == "hm"
        assert message["tool_calls"][0]["type"] == "function"
        assert message["tool_calls"][0]["function"]["name"] == "read_doc"
        assert '"path"' in message["tool_calls"][0]["function"]["arguments"]


class TestStart:
    def test_generation_parameters_are_always_bounded(self):
        """max_tokens and temperature were previously unset entirely."""
        client = FakeClient([event("x")])
        llm.start(client, [{"role": "user", "content": "hi"}], [{"t": 1}])
        assert client.kwargs["max_tokens"] > 0
        assert client.kwargs["temperature"] is not None
        assert client.kwargs["tool_choice"] == "auto"

    def test_no_tools_means_no_tool_choice(self):
        client = FakeClient([event("x")])
        llm.start(client, [{"role": "user", "content": "hi"}])
        assert client.kwargs["tools"] is None
        assert client.kwargs["tool_choice"] is None

    def test_transient_failures_are_retried(self, monkeypatch):
        monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)
        error = RuntimeError("503 service unavailable")
        error.status_code = 503
        client = FakeClient([event("recovered")], failures=1, error=error)
        turn = llm.start(client, [], None)
        assert turn.consume().text == "recovered"
        assert client.calls == 2

    def test_permanent_failures_are_not_retried(self):
        error = RuntimeError("unauthorized")
        error.status_code = 401
        client = FakeClient([], failures=5, error=error)
        with pytest.raises(llm.AssistantError) as caught:
            llm.start(client, [], None)
        assert caught.value.kind == "auth"
        assert client.calls == 1

    def test_retries_give_up_and_surface_the_error(self, monkeypatch):
        monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)
        error = RuntimeError("rate limit exceeded")
        client = FakeClient([], failures=99, error=error)
        with pytest.raises(llm.AssistantError) as caught:
            llm.start(client, [], None)
        assert caught.value.kind == "rate_limit"
        assert client.calls == llm.config.REQUEST_RETRIES + 1


class TestClassify:
    @pytest.mark.parametrize(
        ("exc", "kind"),
        [
            (RuntimeError("Invalid API key provided"), "auth"),
            (RuntimeError("Rate limit exceeded, slow down"), "rate_limit"),
            (RuntimeError("maximum context length is 32000 tokens"), "context"),
            (RuntimeError("Connection reset by peer"), "network"),
            (RuntimeError("request timed out"), "network"),
            (RuntimeError("something odd"), "unknown"),
        ],
    )
    def test_messages_are_specific(self, exc, kind):
        error = llm.classify(exc)
        assert error.kind == kind
        assert error.user_message

    def test_status_codes_take_priority(self):
        exc = RuntimeError("server exploded")
        exc.status_code = 500
        assert llm.classify(exc).kind == "unavailable"

    def test_only_transient_kinds_are_retryable(self):
        assert llm.AssistantError("network").retryable
        assert llm.AssistantError("rate_limit").retryable
        assert not llm.AssistantError("auth").retryable
        assert not llm.AssistantError("context").retryable

    def test_an_assistant_error_classifies_to_itself(self):
        original = llm.AssistantError("auth")
        assert llm.classify(original) is original

    def test_unknown_kinds_fall_back_safely(self):
        assert llm.AssistantError("nonsense-kind").kind == "unknown"


def test_missing_api_key_is_an_auth_error():
    with pytest.raises(llm.AssistantError) as caught:
        llm.create_client("")
    assert caught.value.kind == "auth"


def test_tool_result_message_shape():
    message = llm.tool_result_message({"id": "x", "name": "read_doc"}, "content here")
    assert message == {
        "role": "tool",
        "tool_call_id": "x",
        "name": "read_doc",
        "content": "content here",
    }
