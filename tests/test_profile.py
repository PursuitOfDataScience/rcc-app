"""The seam that makes this app a *documentation* assistant rather than the RCC's.

Two things are worth holding here, and neither is visible from any other test:

* a second profile really does produce a second assistant — different prompt,
  different tool descriptions, different copy — without touching code;
* and nothing under `sage/` says "RCC", so there is nowhere for the subject to hide
  when someone swaps the profile and wonders why an answer still mentions Midway.
"""

from __future__ import annotations

import ast
import os

import pytest

from sage import corpus as corpus_mod
from sage import profile as profile_mod
from sage import prompts, retrieval, runtime, tools
from sage.profile import Profile, from_mapping

SAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sage")

OTHER = {
    "assistant": {
        "name": "Atlas",
        "icon": "🗺️",
        "page_title": "Atlas — Maps Handbook",
        "subject": "the Cartography Department's handbook",
        "topic": "mapping",
        "corpus_name": "the Maps Handbook",
        "contact": "maps@example.org",
        "contact_label": "the Maps desk",
        "operator": "the maps team",
        "topics": "projections, datums or tiling",
        "path_example": "handbook/projections.md#utm",
    },
    "copy": {
        "welcome_title": "Ask about maps",
        "placeholder": "Ask any question about mapping…",
    },
    "prompt": {"system": "You are {name}. You answer about {subject}. Ask {contact}."},
    "examples": [{"icon": "🗺️", "label": "Pick a projection"}],
    "sources": [
        {
            "name": "handbook",
            "path": "./handbook",
            "extensions": [".md"],
            "reader": "markdown",
            "links": "direct",
            "base_url": "https://maps.example.org/",
            "weight": 1.5,
        }
    ],
    "retrieval": {"engine": "bm25", "synonyms": [["utm", "grid"]], "protected": ["wgs84"]},
    "providers": [
        {"name": "local", "kind": "openai", "key_env": "LOCAL_KEY",
         "base_url": "http://127.0.0.1:8000/v1", "models": ["qwen3"]}
    ],
}


@pytest.fixture
def atlas():
    """A wholly different deployment, installed for the duration of one test."""
    built = from_mapping(OTHER, origin="profiles/atlas.toml")
    profile_mod.use(built)
    yield built
    profile_mod.use(None)


class TestTheProfileIsTheDeployment:
    def test_the_shipped_profile_loads_from_its_file(self, profile):
        assert profile.origin.endswith("rcc.toml")
        assert profile.identity.name == "Sage"
        assert [source.name for source in profile.sources] == ["docs", "web"]
        assert [entry.name for entry in profile.providers] == ["mistral", "opencode"]
        assert profile.prompt, "the prompt file beside the profile was not read"

    def test_a_second_profile_changes_who_the_assistant_is(self, atlas):
        assert prompts.system_prompt(atlas) == (
            "You are Atlas. You answer about the Cartography Department's handbook. "
            "Ask maps@example.org."
        )
        assert atlas.identity.documentation == "the mapping documentation"

    def test_a_second_profile_changes_what_the_tools_say(self, atlas):
        index = retrieval.Index(corpus_mod.Corpus())
        schemas = {
            schema["function"]["name"]: schema["function"]["description"]
            for schema in tools.build(index, atlas.identity).schemas
        }
        assert "the Maps Handbook" in schemas[tools.SEARCH_DOCS]
        assert "projections, datums or tiling" in schemas[tools.SEARCH_DOCS]
        assert "handbook/projections.md#utm" in schemas[tools.READ_DOC]
        assert "RCC" not in "".join(schemas.values())

    def test_a_second_profile_changes_where_citations_point(self, atlas):
        source = atlas.source("handbook")
        assert corpus_mod.url_for(source, "projections.md", "utm") == (
            "https://maps.example.org/projections.md#utm"
        )

    def test_a_second_profile_changes_the_vocabulary(self, atlas):
        words = retrieval.vocabulary(atlas)
        assert "grid" in words.expand("utm")
        # The RCC groups are not inherited: "killed" no longer reaches "memory".
        assert words.stem("memory") not in words.expand("my job was killed")

    def test_an_absent_source_tree_is_a_warning_not_a_crash(self, atlas):
        built = runtime.build(atlas)
        assert built.corpus.chunks == []
        assert built.identity.name == "Atlas"
        assert built.toolset.schemas


class TestNothingUnderSageNamesTheSubject:
    """A string a reader or a model can see must come from the profile.

    Scanned as string *literals*, with docstrings excluded: the comments and
    docstrings in this package are full of the RCC, because that is where the
    evidence for every decision came from and deleting it would cost more than it
    buys. What must not survive is a sentence the app can actually emit.
    """

    BRANDED = ("rcc", "uchicago", "midway", "beagle", "skyway", "cnetid")

    def literals(self, path: str) -> list[str]:
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            ):
                body = getattr(node, "body", None)
                if body and isinstance(body[0], ast.Expr) and isinstance(
                    body[0].value, ast.Constant
                ) and isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))
        return [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ]

    def modules(self) -> list[str]:
        found = []
        for root, _dirs, names in os.walk(SAGE):
            found += [
                os.path.join(root, name) for name in names if name.endswith(".py")
            ]
        return sorted(found)

    def test_the_package_is_not_about_anything_in_particular(self):
        assert self.modules(), "no modules were scanned"
        offences = [
            (os.path.relpath(path, SAGE), text)
            for path in self.modules()
            for text in self.literals(path)
            if any(word in text.lower() for word in self.BRANDED)
            # The one exception, and it is the mechanism rather than a leak: the
            # default value of `SAGE_PROFILE` has to name a file, and the file this
            # repository ships is the RCC's. A path is not a sentence the app emits.
            and not text.endswith(".toml")
        ]
        assert not offences, (
            "these strings name this deployment and belong in a profile: "
            f"{offences[:5]}"
        )

    def test_the_shipped_profile_is_where_it_all_lives(self, profile):
        """…and the counterpart: the profile really does say all of it."""
        text = "\n".join(
            [profile.identity.subject, profile.identity.corpus_name, profile.prompt]
            + [source.base_url for source in profile.sources]
        ).lower()
        for word in ("rcc", "uchicago", "midway"):
            assert word in text


def test_the_default_profile_is_a_working_assistant():
    """No file at all: unbranded copy, no documents, and no sentence with a hole in it.

    The topic is an adjective, so leaving it unset has to read as English rather than
    as a template that was never filled — "any question", not "any  question", and no
    dangling "point the user at the maintainers ()".
    """
    empty = Profile()
    prompt = prompts.system_prompt(empty)
    assert prompt and "{" not in prompt
    assert empty.identity.documentation == "the documentation"

    search = next(
        schema["function"]["description"]
        for schema in tools.build(
            retrieval.Index(corpus_mod.Corpus()), empty.identity
        ).schemas
        if schema["function"]["name"] == tools.SEARCH_DOCS
    )
    assert "for any question, then read" in search
    assert "  " not in search
