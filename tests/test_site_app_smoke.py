"""The site deployment, end to end: `SAGE_PROFILE=site streamlit run app.py`.

`test_app_smoke.py` boots the same module but asserts RCC copy throughout, so it
cannot tell whether the *other* deployment works. This file is small on purpose —
it checks the things that would make the site app fail to start or answer from the
wrong corpus, and leaves everything the two share to the RCC suite.
"""

from types import SimpleNamespace

import pytest

import stub_streamlit
from sage import corpus as corpus_mod
from sage import engine, profiles, providers
from sage.search import Index

SITE = profiles.get("site")


def event(content=None, tool_calls=None):
    return providers.Chunk(text=content or "", tool_calls=tool_calls or [])


class ScriptedProvider:
    name = "mistral"

    def __init__(self, turns):
        self.turns = list(turns)
        self.sent: list[list[dict]] = []

    def models(self):
        return [providers.Model(self.name, "m1")]

    def stream(self, model, messages, tools):
        self.sent.append(list(messages))
        yield from self.turns.pop(0)


@pytest.fixture(autouse=True)
def _clean_modules():
    yield
    import sys

    for name in ("app",):
        sys.modules.pop(name, None)


@pytest.fixture
def site_index():
    built = corpus_mod.build(profile=SITE)
    if not built.chunks:
        pytest.skip("no site/ corpus; run tools/build_site_corpus.py")
    return Index(built)


def boot(monkeypatch, provider):
    """Import app.py fresh under the site profile.

    `app` is dropped from `sys.modules` *before* the import, not only after: a
    module left behind by an earlier test file makes `import app` a no-op, and the
    test then measures an empty stub while every assertion about the profile still
    passes — which reads as "the site welcome is missing" rather than "the app was
    never run".
    """
    import sys

    sys.modules.pop("app", None)
    monkeypatch.setenv("SAGE_PROFILE", "site")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    stub = stub_streamlit.install()
    monkeypatch.setattr(providers, "build", lambda name, _key: provider)
    module = None
    try:
        import app as module  # noqa: PLC0415
    except (stub_streamlit.Rerun, stub_streamlit.Stop):
        pass
    return stub, module


class TestBoot:
    def test_the_site_deployment_starts_and_shows_its_own_welcome(self, monkeypatch):
        """The failure this guards is a deployment that boots to the RCC welcome
        over a corpus of blog posts — which looks like a prompt bug, not a config
        one, and would take an afternoon to trace."""
        stub, module = boot(monkeypatch, ScriptedProvider([]))
        assert module is not None, "app.py did not import under SAGE_PROFILE=site"
        assert module.PROFILE.key == "site"

        # Not the whole page: app.css opens with a comment naming the RCC app, and
        # asserting over that too would fail for a reason that has nothing to do
        # with which assistant booted.
        copy = "\n".join(
            block for block in stub.markdown_html if "<style>" not in block
        )
        assert "Ask about anything I've written" in copy
        assert "RCC" not in copy

    def test_the_brand_palette_is_injected_after_the_stylesheet(self, monkeypatch):
        """Order is the whole mechanism: the overrides are custom properties of
        equal specificity, so the later block is the one that wins."""
        stub, _module = boot(monkeypatch, ScriptedProvider([]))
        styles = [call for call in stub.markdown_html if "<style>" in call]
        assert styles, "no stylesheet was injected"
        assert "--brand: #2563eb" in styles[0]
        assert styles[0].index("--brand: #2563eb") > styles[0].index(".stChatMessage")

    def test_the_starter_cards_are_the_sites_own(self, monkeypatch):
        stub, _module = boot(monkeypatch, ScriptedProvider([]))
        labels = " ".join(str(label) for label in stub.button_labels.values())
        assert "Pretraining from scratch" in labels
        assert "Midway" not in labels


class TestProfileSelection:
    """How the deployment learns which assistant to be.

    Getting this wrong is not a crash — it is the RCC assistant booting over the
    blog corpus, answering in the wrong voice about the wrong things, and looking
    like a prompt bug.
    """

    def test_the_environment_wins(self, monkeypatch):
        _stub, module = boot(monkeypatch, ScriptedProvider([]))
        assert module.PROFILE.key == "site"

    def test_secrets_are_read_when_the_environment_is_empty(self, monkeypatch):
        """Community Cloud does export root-level secrets as environment
        variables. This does not depend on that having happened yet."""
        import sys

        sys.modules.pop("app", None)
        monkeypatch.delenv("SAGE_PROFILE", raising=False)
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
        stub = stub_streamlit.install()
        stub.secrets = SimpleNamespace(
            get=lambda key, default="": (
                "site" if key == "SAGE_PROFILE" else default
            )
        )
        monkeypatch.setattr(
            providers, "build", lambda name, _key: ScriptedProvider([])
        )
        module = None
        try:
            import app as module  # noqa: PLC0415
        except (stub_streamlit.Rerun, stub_streamlit.Stop):
            pass
        assert module is not None
        assert module.PROFILE.key == "site"

    def test_neither_source_means_the_assistant_this_repo_already_shipped(
        self, monkeypatch
    ):
        import sys

        sys.modules.pop("app", None)
        monkeypatch.delenv("SAGE_PROFILE", raising=False)
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
        stub_streamlit.install()
        monkeypatch.setattr(
            providers, "build", lambda name, _key: ScriptedProvider([])
        )
        module = None
        try:
            import app as module  # noqa: PLC0415
        except (stub_streamlit.Rerun, stub_streamlit.Stop):
            pass
        assert module.PROFILE.key == "rcc"


class TestAnswering:
    def test_a_turn_searches_the_blog_and_cites_a_real_permalink(self, site_index):
        """The whole point, in one test: the model is handed the site's tools, the
        search runs against the articles, and the citation is a live deep link."""
        provider = ScriptedProvider([
            [event(tool_calls=[{
                "index": 0, "id": "c1", "name": "search_docs",
                "arguments": '{"query":"rapidu disk usage"}',
            }])],
            [event(tool_calls=[{
                "index": 0, "id": "c2", "name": "read_doc",
                "arguments": '{"path":"post/2026-08-04-rapidu/rapidu.md"}',
            }])],
            [event("rapiDU is a faster `du`.")],
        ])
        result = None
        for item in engine.run_turn(
            index=site_index,
            messages=[{"role": "system", "content": SITE.system_prompt}],
            model=providers.Model("mistral", "m1"),
            provider=provider,
            question="what is rapiDU",
        ):
            if item.kind == engine.STREAM:
                list(item.deltas)
            elif item.kind == engine.ANSWER:
                result = item.data

        assert result["text"] == "rapiDU is a faster `du`."
        assert result["sources"], "the section it read was not cited"
        url = result["sources"][0]["url"]
        assert url.startswith("https://youzhi.netlify.app/post/2026-08-04-rapidu/")

    def test_the_model_is_given_the_sites_tool_descriptions(self, site_index):
        provider = ScriptedProvider([[event("An answer.")]])
        list(engine.run_turn(
            index=site_index, messages=[{"role": "system", "content": "s"}],
            model=providers.Model("mistral", "m1"), provider=provider,
        ))
        # `stream()` records messages; the schemas are what matter here, so read
        # them off the profile the index carries rather than the call.
        from sage.tools import tool_schemas

        described = tool_schemas(site_index.corpus.profile)[0]["function"]
        assert "blog" in described["description"].lower()
        assert "RCC" not in described["description"]

    def test_a_search_status_names_the_articles_not_the_docs(self, site_index):
        calls = [{"name": "search_docs", "input": {"query": "penguins"}}]
        assert engine.describe(calls, site_index.corpus) == (
            "Searching the articles for “penguins”"
        )
