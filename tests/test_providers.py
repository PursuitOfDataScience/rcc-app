"""Provider adapters: Mistral SDK and the OpenAI-compatible OpenCode Zen endpoint."""

import importlib
import os
import sys
from types import ModuleType, SimpleNamespace

import pytest

from sage import config, providers


class TestModel:
    def test_key_round_trips(self):
        model = providers.Model("opencode", "deepseek-v4-flash-free")
        assert model.key == "opencode:deepseek-v4-flash-free"
        assert providers.parse_key(model.key) == model

    def test_labels_are_the_model_name_and_stay_short(self):
        """No provider prefix. "Zen · deepseek-v4-flash-free" spent a third of the
        picker's width restating what the rest of the row already said, on every line,
        and `mistral-` on the front of the Mistral ids does that job for free."""
        mistral = providers.Model("mistral", "mistral-small-latest").label
        zen = providers.Model("opencode", "deepseek-v4-flash-free").label
        assert mistral == "mistral-small-latest"
        assert zen == "deepseek-v4-flash-free"
        assert "·" not in mistral + zen
        # Long labels get ellipsed in a 240px picker, so keep them under ~30 chars.
        assert max(len(mistral), len(zen)) <= 30

    @pytest.mark.parametrize("bad", ["", "nope", "mistral:", ":model", "other:m"])
    def test_malformed_keys_are_rejected(self, bad):
        assert providers.parse_key(bad) is None

    def test_a_model_id_containing_a_colon_survives(self):
        model = providers.parse_key("opencode:vendor/model:v2")
        assert model.id == "vendor/model:v2"

    def test_tool_support_is_configurable(self, monkeypatch):
        monkeypatch.setattr(config, "TOOLLESS_MODELS", ("big-pickle",))
        assert not providers.Model("opencode", "Big-Pickle").supports_tools
        assert providers.Model("opencode", "deepseek-v4-flash").supports_tools

    def test_everything_supports_tools_by_default(self, monkeypatch):
        monkeypatch.setattr(config, "TOOLLESS_MODELS", ())
        assert providers.Model("opencode", "anything").supports_tools


class TestParseSSE:
    """OpenCode Zen speaks the OpenAI streaming format."""

    def test_text_deltas(self):
        lines = [
            'data: {"choices":[{"delta":{"content":"Use "}}]}',
            'data: {"choices":[{"delta":{"content":"sbatch."}}]}',
            "data: [DONE]",
        ]
        chunks = list(providers.parse_sse(iter(lines)))
        assert "".join(chunk.text for chunk in chunks) == "Use sbatch."

    def test_tool_calls_arrive_in_fragments(self):
        lines = [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
            '"function":{"name":"search_docs","arguments":"{\\"query\\":"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
            '"function":{"arguments":"\\"gpu\\"}"}}]}}]}',
        ]
        fragments = [f for chunk in providers.parse_sse(iter(lines))
                     for f in chunk.tool_calls]
        assert fragments[0]["name"] == "search_docs"
        assert "".join(f["arguments"] for f in fragments) == '{"query":"gpu"}'

    def test_done_stops_the_stream(self):
        lines = ["data: [DONE]", 'data: {"choices":[{"delta":{"content":"after"}}]}']
        assert list(providers.parse_sse(iter(lines))) == []

    def test_keepalives_comments_and_blanks_are_ignored(self):
        lines = ["", ": keep-alive", "event: ping", 'data: {"choices":[]}',
                 'data: {"choices":[{"delta":{"content":"ok"}}]}']
        assert "".join(c.text for c in providers.parse_sse(iter(lines))) == "ok"

    def test_a_malformed_event_does_not_kill_the_stream(self):
        lines = ["data: {not json", 'data: {"choices":[{"delta":{"content":"ok"}}]}']
        assert "".join(c.text for c in providers.parse_sse(iter(lines))) == "ok"

    def test_bytes_lines_are_decoded(self):
        lines = [b'data: {"choices":[{"delta":{"content":"bytes"}}]}']
        assert "".join(c.text for c in providers.parse_sse(iter(lines))) == "bytes"


class TestNormalisation:
    def test_sdk_style_tool_call_objects(self):
        call = SimpleNamespace(
            index=2, id="x", function=SimpleNamespace(name="read_doc", arguments="{}")
        )
        assert providers._tool_fragments([call]) == [
            {"index": 2, "id": "x", "name": "read_doc", "arguments": "{}"}
        ]

    def test_dict_style_tool_calls(self):
        call = {"index": 1, "id": "y", "function": {"name": "search_docs"}}
        assert providers._tool_fragments([call])[0]["name"] == "search_docs"

    def test_missing_index_falls_back_to_position(self):
        calls = [{"function": {"name": "a"}}, {"function": {"name": "b"}}]
        assert [f["index"] for f in providers._tool_fragments(calls)] == [0, 1]

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            (None, ""),
            ("plain", "plain"),
            (["a", "b"], "ab"),
            ([{"text": "a"}, {"text": "b"}], "ab"),
            ([SimpleNamespace(text="x")], "x"),
        ],
    )
    def test_content_shapes_flatten(self, content, expected):
        assert providers._flatten(content) == expected


class TestMistralAdapter:
    """The SDK returns a context manager on 1.x and a bare iterator on some builds."""

    @staticmethod
    def _event(text):
        delta = SimpleNamespace(content=text, tool_calls=None)
        return SimpleNamespace(
            data=SimpleNamespace(choices=[SimpleNamespace(delta=delta)])
        )

    def _provider(self, stream):
        adapter = providers.MistralProvider.__new__(providers.MistralProvider)
        adapter._client = SimpleNamespace(
            chat=SimpleNamespace(stream=lambda **_kwargs: stream)
        )
        return adapter

    def test_a_bare_iterator_works(self):
        stream = iter([self._event("a"), self._event("b")])
        chunks = list(self._provider(stream).stream("m", [], None))
        assert "".join(c.text for c in chunks) == "ab"

    def test_a_context_manager_is_entered_and_closed(self):
        events = [self._event("hi")]

        class Managed:
            entered = exited = False

            def __enter__(inner):
                inner.entered = True
                return iter(events)

            def __exit__(inner, *_exc):
                inner.exited = True
                return False

        managed = Managed()
        chunks = list(self._provider(managed).stream("m", [], None))
        assert "".join(c.text for c in chunks) == "hi"
        assert managed.entered and managed.exited

    def test_malformed_events_are_skipped(self):
        stream = iter([
            SimpleNamespace(data=None),
            SimpleNamespace(data=SimpleNamespace(choices=[])),
            self._event("ok"),
        ])
        chunks = list(self._provider(stream).stream("m", [], None))
        assert "".join(c.text for c in chunks) == "ok"


class TestOpenAICompat:
    def test_the_key_is_sent_as_a_bearer_token(self):
        provider = providers.OpenAICompatProvider("sk-zen-abc", "https://x.test/v1/")
        headers = provider._headers()
        assert headers["Authorization"] == "Bearer sk-zen-abc"

    def test_the_base_url_loses_a_trailing_slash(self):
        provider = providers.OpenAICompatProvider("k", "https://x.test/v1/")
        assert provider._base == "https://x.test/v1"

    def test_model_discovery_falls_back_when_the_endpoint_is_unreachable(self):
        provider = providers.OpenAICompatProvider("k", "http://127.0.0.1:1/v1")
        found = provider.models()
        assert [model.id for model in found] == list(config.OPENCODE_MODELS)
        assert all(model.provider == providers.OPENCODE for model in found)

    def test_discovery_keeps_the_preferred_order_and_appends_the_rest(self):
        """Order is not cosmetic: it picks the session default *and* what an
        automatic failover lands on. Sorting alphabetically made a spent Mistral
        quota fail over to `big-pickle` rather than the free deepseek model."""
        provider = providers.OpenAICompatProvider(
            "k", "https://x.test/v1", preferred=("deepseek-v4-flash-free", "mimo-v2.5")
        )
        ordered = provider._order(["zzz-model", "mimo-v2.5", "big-pickle",
                                   "deepseek-v4-flash-free"])
        assert ordered == ["deepseek-v4-flash-free", "mimo-v2.5",
                           "big-pickle", "zzz-model"]

    def test_a_preferred_model_the_endpoint_no_longer_serves_is_dropped(self):
        provider = providers.OpenAICompatProvider(
            "k", "https://x.test/v1", preferred=("retired", "kept")
        )
        assert provider._order(["kept", "new"]) == ["kept", "new"]


def test_build_rejects_an_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        providers.build("nope", "key")


def _shipped_max_tokens() -> int:
    """`config.MAX_TOKENS` with any environment override taken away.

    The module reads the environment at import, so the number the app ships with is
    only visible with `SAGE_MAX_TOKENS` unset — otherwise this asserts on whatever
    the machine running the tests happens to export. The second reload puts the
    process back the way it was found.
    """
    saved = os.environ.pop("SAGE_MAX_TOKENS", None)
    try:
        return importlib.reload(config).MAX_TOKENS
    finally:
        if saved is not None:
            os.environ["SAGE_MAX_TOKENS"] = saved
        importlib.reload(config)


class TestTokenBudgetReachesTheRequest:
    """The cap is only a fix where the request is built.

    `SAGE_MAX_TOKENS` was 1600 and answers came back severed mid-sentence — "Per the
    RCC docs," and then nothing. Two things have to hold, and neither implies the
    other: the shipped default has to be generous, and it has to be the number each
    provider actually asks for. The SDK client and the HTTP client are stood in for
    here; the payload built between them is the thing under test.
    """

    def test_the_default_is_not_the_value_that_severed_answers(self):
        assert _shipped_max_tokens() >= 8000, (
            "1600 tokens cut a walkthrough with two code blocks off mid-sentence"
        )

    def test_the_mistral_request_asks_for_the_configured_budget(self):
        asked = {}

        def stream(**kwargs):
            asked.update(kwargs)
            delta = SimpleNamespace(content="ok", tool_calls=None)
            return iter([
                SimpleNamespace(data=SimpleNamespace(
                    choices=[SimpleNamespace(delta=delta)]
                ))
            ])

        adapter = providers.MistralProvider.__new__(providers.MistralProvider)
        adapter._client = SimpleNamespace(chat=SimpleNamespace(stream=stream))
        assert "".join(chunk.text for chunk in adapter.stream("m", [], None)) == "ok"
        assert asked.get("max_tokens") == config.MAX_TOKENS

    def test_the_openai_compatible_payload_carries_the_configured_budget(
        self, monkeypatch
    ):
        sent = {}

        class Response:
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def iter_lines(self):
                return iter([
                    'data: {"choices":[{"delta":{"content":"ok"}}]}',
                    "data: [DONE]",
                ])

        class Client:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def stream(self, _method, _url, json=None, **_kwargs):
                sent.update(json or {})
                return Response()

        fake = ModuleType("httpx")
        fake.Client = Client
        fake.Timeout = lambda *_a, **_k: None
        monkeypatch.setitem(sys.modules, "httpx", fake)

        provider = providers.OpenAICompatProvider("k", "https://x.test/v1")
        streamed = "".join(c.text for c in provider.stream("z1", [], None))
        assert streamed == "ok"
        assert sent.get("max_tokens") == config.MAX_TOKENS


class TestFreeZenModels:
    """Zen serves its paid lineup from the same endpoint as its free one.

    Discovery returned all of it — the whole Claude and GPT range — and the picker
    offered every one as if this deployment had a balance for it. Each of those is a
    button that returns a 402.
    """

    def endpoint(self, monkeypatch, served):
        """An OpenCode provider whose /models call returns `served`.

        httpx is imported inside the method under test and is not installed here, so
        the module is stubbed the way the streaming tests above do it.
        """
        class Response:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"data": [{"id": name} for name in served]}

        fake = ModuleType("httpx")
        fake.get = lambda *a, **k: Response()
        monkeypatch.setitem(sys.modules, "httpx", fake)
        return providers.OpenAICompatProvider(
            "sk-zen-test", "https://opencode.ai/zen/v1",
            preferred=("deepseek-v4-flash-free",),
        )

    def test_the_paid_lineup_is_not_offered(self, monkeypatch):
        served = [
            "deepseek-v4-flash-free", "big-pickle", "hy3-free",
            "claude-opus-4-7", "claude-fable-5", "gpt-5.5", "claude-haiku-4-5",
        ]
        offered = [model.id for model in self.endpoint(monkeypatch, served).models()]
        assert set(offered) == {"deepseek-v4-flash-free", "big-pickle", "hy3-free"}

    def test_the_rule_is_a_convention_not_a_hardcoded_list(self, monkeypatch):
        """Zen's free lineup changes without notice, so a model this repo has never
        heard of must still be offered if it is named like a free one."""
        served = ["something-brand-new-free", "claude-opus-9"]
        offered = [model.id for model in self.endpoint(monkeypatch, served).models()]
        assert offered == ["something-brand-new-free"]

    def test_nothing_free_means_offer_everything_rather_than_nothing(
        self, monkeypatch, caplog=None
    ):
        """If Zen renames its free tier, an empty picker is worse than a full one:
        the reader can still pick something, and the log says to check the marks."""
        served = ["claude-opus-4-7", "gpt-5.5"]
        offered = [model.id for model in self.endpoint(monkeypatch, served).models()]
        assert offered == served

    def test_a_paid_deployment_can_see_its_whole_lineup(self, monkeypatch):
        monkeypatch.setattr(config, "ZEN_FREE_ONLY", False)
        served = ["deepseek-v4-flash-free", "claude-opus-4-7"]
        offered = [model.id for model in self.endpoint(monkeypatch, served).models()]
        assert offered == served


def test_a_model_label_is_just_the_model_name():
    """The provider prefix spent a third of the picker's width restating what the row
    already said, on every line."""
    assert providers.Model(providers.OPENCODE, "deepseek-v4-flash-free").label == (
        "deepseek-v4-flash-free"
    )
    assert providers.Model(providers.MISTRAL, "mistral-small-latest").label == (
        "mistral-small-latest"
    )
    assert "Zen" not in providers.Model(providers.OPENCODE, "big-pickle").label
