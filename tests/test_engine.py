"""The agent loop, driven directly — no Streamlit, no stub of one.

These are the tests the loop could not have while it lived inside `app.py`: every
one of them used to require driving a fake Streamlit through `test_app_smoke`, and
several of them (the round cap, the drain guarantee, the failover ladder) were not
covered at all because doing so through the view was more trouble than it was worth.
"""

import pytest

from sage import engine, llm
from sage.corpus import Chunk, Corpus
from sage.providers import Chunk as StreamChunk
from sage.providers import Model
from sage.search import Index


def event(content=None, tool_calls=None):
    return StreamChunk(text=content or "", tool_calls=tool_calls or [])


def call(index=0, cid="c1", name="search_docs", arguments='{"query":"x"}'):
    return {"index": index, "id": cid, "name": name, "arguments": arguments}


class ScriptedProvider:
    """Replays one list of chunks per `stream()` call, in order.

    `errors` maps a zero-based call number to an exception raised instead;
    `always` raises on every call. The distinction matters because `llm.start`
    retries the transient kinds ("network", "rate_limit", "unavailable") before
    giving up, so a one-shot failure of those never reaches the caller — which is
    correct behaviour and would silently make a failover test vacuous.
    """

    name = "scripted"

    def __init__(self, turns, errors=None, always=None):
        self.turns = list(turns)
        self.errors = errors or {}
        self.always = always
        self.calls = 0
        self.seen = []

    def models(self):
        return []

    def stream(self, model, messages, tools):
        index = self.calls
        self.calls += 1
        self.seen.append({"model": model, "messages": list(messages), "tools": tools})
        if self.always is not None:
            raise self.always
        if index in self.errors:
            raise self.errors[index]
        yield from (self.turns[index] if index < len(self.turns) else [])


def tiny_index() -> Index:
    chunks = [
        Chunk(
            id="docs/storage.md#quotas",
            source="docs",
            path="storage.md",
            doc_title="Storage",
            heading="Quotas",
            breadcrumb="Storage › Quotas",
            text="Home directories have a 30 GB quota on Midway.",
            url="https://example.test/storage/#quotas",
        ),
        Chunk(
            id="docs/storage.md#scratch",
            source="docs",
            path="storage.md",
            doc_title="Storage",
            heading="Scratch",
            breadcrumb="Storage › Scratch",
            text="Scratch is purged after thirty days and is not backed up.",
            url="https://example.test/storage/#scratch",
        ),
    ]
    return Index(Corpus(chunks=chunks, documents={}))


def model(key="scripted:m1"):
    provider, _, name = key.partition(":")
    return Model(provider, name)


def drive(events):
    """Consume an event stream the way a caller must: draining every `stream`."""
    collected = []
    for item in events:
        if item.kind == engine.STREAM:
            collected.append((item.kind, "".join(item.deltas)))
        else:
            collected.append((item.kind, item.text))
    return collected


def answer_of(events):
    for item in events:
        if item.kind == engine.ANSWER:
            return item.data
    return None


# --- the happy paths --------------------------------------------------------


def test_a_plain_answer_streams_and_is_returned():
    provider = ScriptedProvider([[event("Home is "), event("30 GB.")]])
    seen = []
    result = None
    for item in engine.run_turn(
        index=tiny_index(), messages=[{"role": "system", "content": "s"}],
        model=model(), provider=provider, question="quota",
    ):
        if item.kind == engine.STREAM:
            seen.extend(item.deltas)
        elif item.kind == engine.ANSWER:
            result = item.data

    assert seen == ["Home is ", "30 GB."]
    assert result["text"] == "Home is 30 GB."
    assert result["sources"] == []
    assert result["model"] == "scripted:m1"


def test_the_first_event_names_what_is_happening():
    provider = ScriptedProvider([[event("hi")]])
    stream = engine.run_turn(
        index=tiny_index(), messages=[{"role": "system", "content": "s"}],
        model=model(), provider=provider,
    )
    first = next(stream)
    assert (first.kind, first.text) == (engine.STATUS, engine.THINKING)
    drive(stream)


def test_a_search_round_resets_the_answer_and_says_what_it_searched():
    """The status text is the whole point of `describe`: a named action, not a shimmer."""
    provider = ScriptedProvider([
        [event("Let me look. "), event(tool_calls=[call(arguments='{"query":"quota"}')])],
        [event("Home is 30 GB.")],
    ])
    kinds = drive(engine.run_turn(
        index=tiny_index(), messages=[{"role": "system", "content": "s"}],
        model=model(), provider=provider, question="quota",
    ))

    assert [kind for kind, _ in kinds] == [
        engine.STATUS, engine.STREAM, engine.RESET, engine.STATUS,
        engine.STREAM, engine.ANSWER,
    ]
    assert kinds[3][1] == "Searching the docs for “quota”"


def test_a_read_round_names_the_section_being_read():
    provider = ScriptedProvider([
        [event(tool_calls=[call(
            name="read_doc", arguments='{"path":"docs/storage.md#quotas"}'
        )])],
        [event("Thirty gigabytes.")],
    ])
    statuses = [
        text for kind, text in drive(engine.run_turn(
            index=tiny_index(), messages=[{"role": "system", "content": "s"}],
            model=model(), provider=provider,
        )) if kind == engine.STATUS
    ]
    assert statuses[1] == "Reading Storage — Quotas"


def test_what_the_model_read_becomes_the_sources_strip():
    provider = ScriptedProvider([
        [event(tool_calls=[call(
            name="read_doc", arguments='{"path":"docs/storage.md#scratch"}'
        )])],
        [event("Purged after thirty days.")],
    ])
    result = answer_of(engine.run_turn(
        index=tiny_index(), messages=[{"role": "system", "content": "s"}],
        model=model(), provider=provider,
    ))
    assert [source["id"] for source in result["sources"]] == ["docs/storage.md#scratch"]
    assert result["sources"][0]["url"].endswith("#scratch")
    assert result["sources"][0]["label"] == "Storage — Scratch"


def test_the_footer_a_model_writes_for_itself_is_stripped_before_storage():
    """It would otherwise print directly above the identical strip the app renders,
    and go back upstream as a worked example teaching the model to write another."""
    provider = ScriptedProvider([
        [event("Thirty gigabytes.\n\nSources:\n- [Storage](docs/storage.md#quotas)")]
    ])
    result = answer_of(engine.run_turn(
        index=tiny_index(), messages=[{"role": "system", "content": "s"}],
        model=model(), provider=provider,
    ))
    assert result["text"] == "Thirty gigabytes."


# --- the paths that had no coverage at all ----------------------------------


def test_the_round_cap_ends_the_loop_with_something_to_read():
    """A model that only ever calls tools must not leave an empty bubble."""
    forever = [event(tool_calls=[call()])]
    provider = ScriptedProvider([forever] * 12)
    result = answer_of(engine.run_turn(
        index=tiny_index(), messages=[{"role": "system", "content": "s"}],
        model=model(), provider=provider, max_rounds=3,
    ))
    assert result["text"] == engine.UNFINISHED
    # rounds + 1 attempts, and not one more.
    assert provider.calls == 4


def test_text_from_a_capped_run_is_kept_over_the_placeholder():
    partial = [event("Nearly there"), event(tool_calls=[call()])]
    provider = ScriptedProvider([partial] * 5)
    result = answer_of(engine.run_turn(
        index=tiny_index(), messages=[{"role": "system", "content": "s"}],
        model=model(), provider=provider, max_rounds=2,
    ))
    assert result["text"] == "Nearly there"


def test_a_caller_that_ignores_the_stream_still_gets_the_answer():
    """The drain guarantee. Skipping a `stream` event would otherwise abandon a
    half-read HTTP response and lose the round's text."""
    provider = ScriptedProvider([
        [event(tool_calls=[call()])],
        [event("Thirty gigabytes.")],
    ])
    result = None
    for item in engine.run_turn(
        index=tiny_index(), messages=[{"role": "system", "content": "s"}],
        model=model(), provider=provider,
    ):
        if item.kind == engine.ANSWER:
            result = item.data
    assert result["text"] == "Thirty gigabytes."


def test_a_partially_read_stream_is_finished_rather_than_truncated():
    provider = ScriptedProvider([[event("one "), event("two "), event("three")]])
    result = None
    for item in engine.run_turn(
        index=tiny_index(), messages=[{"role": "system", "content": "s"}],
        model=model(), provider=provider,
    ):
        if item.kind == engine.STREAM:
            next(iter(item.deltas))  # take one piece and walk away
        elif item.kind == engine.ANSWER:
            result = item.data
    assert result["text"] == "one two three"


def test_a_model_that_rejects_tools_falls_back_to_one_retrieval_pass():
    rejected = llm.AssistantError("unknown", ValueError("tools are not supported"))
    provider = ScriptedProvider(
        [[], [event("Thirty gigabytes.")]], errors={0: rejected}
    )
    result = answer_of(engine.run_turn(
        index=tiny_index(), messages=[{"role": "system", "content": "s"}],
        model=model(), provider=provider, question="storage quota",
    ))

    assert result["text"] == "Thirty gigabytes."
    # Retrieved up front, so the answer is still cited even though the model never
    # asked for anything.
    assert [source["id"] for source in result["sources"]] == ["docs/storage.md#quotas"]
    # The retry carries the context and no tool schemas.
    retry = provider.seen[1]
    assert retry["tools"] is None
    assert "30 GB quota" in retry["messages"][1]["content"]


def test_a_tool_less_model_is_never_offered_tools_in_the_first_place():
    provider = ScriptedProvider([[event("Thirty gigabytes.")]])
    answer_of(engine.run_turn(
        index=tiny_index(), messages=[{"role": "system", "content": "s"}],
        model=model(), provider=provider, question="quota", tools=False,
    ))
    assert provider.calls == 1
    assert provider.seen[0]["tools"] is None


def test_a_real_failure_is_raised_not_swallowed_into_an_empty_answer():
    provider = ScriptedProvider([[]], always=llm.AssistantError("auth"))
    with pytest.raises(llm.AssistantError) as caught:
        drive(engine.run_turn(
            index=tiny_index(), messages=[{"role": "system", "content": "s"}],
            model=model(), provider=provider,
        ))
    assert caught.value.kind == "auth"


def test_the_incoming_history_is_not_mutated_by_tool_rounds():
    """The caller's list is session state in the app; appending to it would leave
    tool traffic in the transcript."""
    provider = ScriptedProvider([
        [event(tool_calls=[call()])],
        [event("Thirty gigabytes.")],
    ])
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
    drive(engine.run_turn(
        index=tiny_index(), messages=messages, model=model(), provider=provider,
    ))
    assert len(messages) == 2


# --- failover, which the app does by rerunning -------------------------------


def providers_for(mapping):
    return lambda name: mapping[name]


def test_a_spent_quota_moves_to_the_other_provider_and_says_so():
    dead = ScriptedProvider([[]], always=llm.AssistantError("quota"))
    alive = ScriptedProvider([[event("Thirty gigabytes.")]])
    models = [Model("a", "m1"), Model("b", "m2")]

    seen = drive(engine.run_conversation(
        index=tiny_index(), messages=[{"role": "system", "content": "s"}],
        models=models, provider_for=providers_for({"a": dead, "b": alive}),
    ))

    notices = [text for kind, text in seen if kind == engine.NOTICE]
    assert notices == ["m1 is unavailable (out of credit). Retrying with m2…"]
    assert [kind for kind, _ in seen][-1] == engine.ANSWER


def test_the_answer_records_which_model_was_abandoned():
    dead = ScriptedProvider([[]], always=llm.AssistantError("auth"))
    alive = ScriptedProvider([[event("ok")]])
    result = answer_of(engine.run_conversation(
        index=tiny_index(), messages=[{"role": "system", "content": "s"}],
        models=[Model("a", "m1"), Model("b", "m2")],
        provider_for=providers_for({"a": dead, "b": alive}),
    ))
    assert result["switched_from"] == ("m1", "auth")
    assert result["model"] == "b:m2"


def test_failover_skips_the_rest_of_the_provider_whose_key_is_dead():
    """A spent key is spent for every model behind it. Trying each in turn is three
    round-trips to learn one fact."""
    dead = ScriptedProvider([[]], always=llm.AssistantError("quota"))
    alive = ScriptedProvider([[event("ok")]])
    models = [Model("a", "m1"), Model("a", "m2"), Model("a", "m3"), Model("b", "m4")]

    drive(engine.run_conversation(
        index=tiny_index(), messages=[{"role": "system", "content": "s"}],
        models=models, provider_for=providers_for({"a": dead, "b": alive}),
    ))
    assert dead.calls == 1
    assert alive.calls == 1


@pytest.mark.parametrize("kind", ["network", "context", "unavailable", "unknown"])
def test_only_quota_and_auth_fail_over(kind):
    """Retrying a timeout on a second provider hides a real fault behind a second bill."""
    broken = ScriptedProvider([[]], always=llm.AssistantError(kind))
    spare = ScriptedProvider([[event("ok")]])
    with pytest.raises(llm.AssistantError):
        drive(engine.run_conversation(
            index=tiny_index(), messages=[{"role": "system", "content": "s"}],
            models=[Model("a", "m1"), Model("b", "m2")],
            provider_for=providers_for({"a": broken, "b": spare}),
        ))
    assert spare.calls == 0


def test_a_last_model_that_fails_raises_rather_than_running_out_quietly():
    dead = ScriptedProvider([[]], always=llm.AssistantError("quota"))
    with pytest.raises(llm.AssistantError):
        drive(engine.run_conversation(
            index=tiny_index(), messages=[{"role": "system", "content": "s"}],
            models=[Model("a", "m1")], provider_for=providers_for({"a": dead}),
        ))


def test_no_models_at_all_is_an_error_not_an_empty_answer():
    with pytest.raises(llm.AssistantError):
        drive(engine.run_conversation(
            index=tiny_index(), messages=[], models=[], provider_for=providers_for({}),
        ))
