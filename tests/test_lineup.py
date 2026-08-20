"""The lineup drift check, offline.

`tools/lineup_check.py` is the answer to "does this repository still describe the
models the provider actually serves". Every part of it that talks to the network is
injected here, because the one thing a check like this must not do is need the network
to be tested — and because a free tier's catalogue is precisely the input that cannot
be relied on to hold still for a test.

What is worth holding it to, in order of what it would cost to get wrong:

* **Free is decided by the profile's rule, not a copy of it.** Two definitions of
  "free" is the bug this whole mechanism exists to prevent, and a second one living in
  the checker would be the funniest possible place for it.
* **Nothing is removed and nothing is reordered.** The first entry of the profile's
  list is what every fresh session starts on and what an automatic failover lands on.
* **A quiet day is quiet.** A daily report that always has something in it is a daily
  report nobody reads, so latency wobble is not news and a first run is not drift.
* **Account state does not reach the ledger**, which is committed to a public repo.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace

import pytest

from sage import config, profile
from tools import lineup_check

ZEN = profile.active().provider("opencode")


def zen(**overrides):
    return replace(ZEN, **overrides)


def options(**overrides) -> argparse.Namespace:
    base = {
        "provider": "opencode",
        "ledger": "",
        "probe": False,
        "probe_budget": 12,
        "update": False,
        "summary_out": "",
        "fail_on_drift": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestFreeIsTheProfilesRule:
    def test_it_asks_the_adapter_rather_than_matching_its_own_pattern(self):
        """The point of `free_marks` is that there is one definition of free.

        `-contributor-free` is the case that makes this concrete: it is not the `-free`
        suffix the convention was written for, but the rule matches substrings, so the
        picker offered `muse-spark-1.2-contributor-free` before anything named it. A
        checker with its own endswith test would have called it paid and filed a bug
        against reality.
        """
        entry = zen()
        assert lineup_check.is_free(entry, "muse-spark-1.2-contributor-free")
        assert lineup_check.is_free(entry, "hy3-free")
        assert lineup_check.is_free(entry, "big-pickle")
        assert not lineup_check.is_free(entry, "claude-opus-5")
        assert not lineup_check.is_free(entry, "gpt-5.2-codex")

    def test_widening_the_rule_widens_the_check(self):
        entry = zen(free_marks=("-free", "big-pickle", "muse-"))
        assert lineup_check.is_free(entry, "muse-anything")
        assert not lineup_check.is_free(zen(), "muse-anything")


class TestReview:
    def test_it_separates_appeared_from_vanished_from_unclassified(self):
        entry = zen(models=("a-free", "gone-free"))
        got = lineup_check.review(
            entry, ["a-free", "new-free", "claude-opus-5"], {"providers": {}}
        )
        assert got["appeared"] == ["new-free"]
        assert got["vanished"] == ["gone-free"]
        # The only candidate for the next `big-pickle`, and the only name a probe is
        # worth spending on.
        assert got["unclassified"] == ["claude-opus-5"]
        assert got["free"] == ["a-free", "new-free"]

    def test_a_name_the_ledger_has_already_priced_is_not_probed_again(self):
        """This is what keeps a daily run at nearly zero requests.

        Fifty-five of Zen's sixty-three models are paid. Re-probing them every morning
        would be fifty-five requests a day to re-learn a fact that does not change.
        """
        ledger = {"providers": {"opencode": {"paid": ["claude-opus-5"]}}}
        got = lineup_check.review(
            zen(models=()), ["claude-opus-5", "gpt-5.2"], ledger
        )
        assert got["unclassified"] == ["gpt-5.2"]

    def test_missing_since_accrues_instead_of_being_recomputed(self):
        """The profile keeps a model that is broken today, on the grounds that a free
        tier's outages end. What it could not say is how long a given one has run."""
        ledger = {
            "providers": {
                "opencode": {"missing_since": {"gone-free": "2026-01-01"}, "paid": []}
            }
        }
        got = lineup_check.review(zen(models=("gone-free", "also-free")), [], ledger)
        assert got["missing_since"]["gone-free"] == "2026-01-01"
        assert got["missing_since"]["also-free"] == lineup_check.today()

    def test_a_returning_model_stops_being_missing(self):
        ledger = {
            "providers": {
                "opencode": {"missing_since": {"hy3-free": "2026-01-01"}, "paid": []}
            }
        }
        got = lineup_check.review(zen(models=("hy3-free",)), ["hy3-free"], ledger)
        assert got["missing_since"] == {}

    def test_it_notices_the_configured_default_is_not_served(self, monkeypatch):
        """Not an outage — `app.current_model` falls through to the first discovered
        model — but `SAGE_DEFAULT_MODEL` is a fiction until somebody changes it."""
        monkeypatch.setattr(config, "DEFAULT_MODEL", "opencode:vanished-free")
        got = lineup_check.review(zen(models=()), ["hy3-free"], {"providers": {}})
        assert got["default_missing"] is True

    def test_it_notices_the_rule_matching_nothing(self):
        """With `free_only` set this is the state where the picker offers the entire
        paid lineup as if it worked. The adapter logs it; nobody reads those logs."""
        got = lineup_check.review(
            zen(models=()), ["claude-opus-5", "gpt-5.2"], {"providers": {}}
        )
        assert got["rule_matched_nothing"] is True


class TestMaterialChange:
    def test_a_first_run_is_not_drift(self):
        """An empty ledger listed all eight free models as news, which is the report a
        reader learns to skim past."""
        after = lineup_check.review(zen(), ["hy3-free"], {"providers": {}})
        reasons = lineup_check.material({"free": None, "verdicts": {}}, after)
        assert len(reasons) == 1
        assert "first record" in reasons[0]

    def test_latency_alone_is_not_news(self, monkeypatch):
        monkeypatch.setattr(config, "DEFAULT_MODEL", "opencode:hy3-free")
        after = lineup_check.review(
            zen(models=("hy3-free",)), ["hy3-free"], {"providers": {}}
        )
        after["verdicts"] = {"hy3-free": {"answered": True, "seconds": 9.9}}
        after["candidates"] = []
        before = {
            "free": ["hy3-free"],
            "verdicts": {"hy3-free": {"answered": True, "seconds": 0.4}},
        }
        assert lineup_check.material(before, after) == []

    def test_a_verdict_flipping_is_news_in_both_directions(self):
        after = lineup_check.review(
            zen(models=("hy3-free",)), ["hy3-free"], {"providers": {}}
        )
        after["candidates"] = []
        after["verdicts"] = {"hy3-free": {"answered": False}}
        before = {"free": ["hy3-free"], "verdicts": {"hy3-free": {"answered": True}}}
        assert any("stopped answering" in reason
                   for reason in lineup_check.material(before, after))

        after["verdicts"] = {"hy3-free": {"answered": True}}
        before = {"free": ["hy3-free"], "verdicts": {"hy3-free": {"answered": False}}}
        assert any("answers again" in reason
                   for reason in lineup_check.material(before, after))

    def test_a_new_free_model_is_news(self):
        after = lineup_check.review(
            zen(models=("hy3-free",)), ["hy3-free", "new-free"], {"providers": {}}
        )
        after["candidates"] = []
        before = {"free": ["hy3-free"], "verdicts": {}}
        reasons = lineup_check.material(before, after)
        assert any("`new-free` is now served free" in reason for reason in reasons)

    def test_a_stealth_candidate_is_news(self):
        after = lineup_check.review(zen(), ["hy3-free"], {"providers": {}})
        after["candidates"] = ["big-cucumber"]
        after["verdicts"] = {}
        reasons = lineup_check.material({"free": ["hy3-free"], "verdicts": {}}, after)
        assert any("without matching `free_marks`" in reason for reason in reasons)


class TestAppendModels:
    PROFILE = '''\
[[providers]]
name = "opencode"
kind = "openai"
# A comment that has to survive.
models = [
    # Why this one is first.
    "first-free",
    "second-free",
]
free_marks = ["-free"]

[[providers]]
name = "other"
models = ["untouched"]
'''

    def test_it_appends_at_the_end_and_keeps_every_comment(self):
        got = lineup_check.append_models(self.PROFILE, "opencode", ["new-free"])
        assert "# Why this one is first." in got
        assert "# A comment that has to survive." in got
        lines = [line.strip() for line in got.splitlines()]
        assert lines.index('"new-free",') > lines.index('"second-free",')

    def test_it_never_reorders_or_removes(self):
        """The first entry decides what every fresh session starts on and what a
        failover lands on. A daily job that reordered it would be choosing, once a day,
        which model every reader gets — from a catalogue listing that says nothing about
        whether the model is any good."""
        got = lineup_check.append_models(self.PROFILE, "opencode", ["new-free"])
        kept = [line for line in got.splitlines() if line.strip().startswith('"')]
        assert [line.strip() for line in kept][:3] == [
            '"first-free",', '"second-free",', '"new-free",'
        ]

    def test_it_leaves_other_providers_alone(self):
        got = lineup_check.append_models(self.PROFILE, "opencode", ["new-free"])
        assert 'models = ["untouched"]' in got

    def test_it_handles_a_single_line_list(self):
        text = '[[providers]]\nname = "p"\nmodels = ["a", "b"]\n'
        got = lineup_check.append_models(text, "p", ["c"])
        assert got == '[[providers]]\nname = "p"\nmodels = ["a", "b", "c"]\n'

    def test_nothing_to_add_changes_nothing(self):
        assert lineup_check.append_models(self.PROFILE, "opencode", []) == self.PROFILE

    def test_an_unknown_provider_raises_rather_than_writing_the_wrong_block(self):
        with pytest.raises(ValueError):
            lineup_check.append_models(self.PROFILE, "absent", ["x"])

    def test_the_result_still_parses_as_the_profile_it_was(self, tmp_path):
        """The check that matters: an edit that produced valid-looking text but an
        unparseable profile would take the app down, and this runs unattended."""
        source = profile.active().origin
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        target = tmp_path / "rcc.toml"
        target.write_text(lineup_check.append_models(text, "opencode", ["probe-free"]))
        loaded = profile.load(str(target))
        entry = loaded.provider("opencode")
        assert entry.models[-1] == "probe-free"
        assert entry.models[0] == ZEN.models[0], "the failover target moved"
        assert loaded.identity.name == profile.active().identity.name


class TestScrub:
    def test_it_takes_the_billing_url_out_of_a_credits_error(self):
        """Zen's `CreditsError` carries the workspace id in a billing link. That is
        account state, it is not a fact about the model, and this ledger is committed
        to a public repository. Found by reading the first one this wrote."""
        body = (
            '{"error":{"type":"CreditsError","message":"Insufficient balance. Manage '
            'your billing here: https://opencode.ai/workspace/wrk_01KQ5KVT0SG152WC5'
            'TMF735F2F/billing"}}'
        )
        got = lineup_check.scrub(body)
        assert "wrk_01" not in got
        assert "opencode.ai" not in got
        # Still says the thing the classification depends on.
        assert "CreditsError" in got
        assert lineup_check._looks_paid(got)

    def test_it_takes_a_bare_opaque_id_too(self):
        assert "sk_" not in lineup_check.scrub("key sk_0123456789abcdefghij rejected")

    def test_it_collapses_whitespace_and_truncates(self):
        assert lineup_check.scrub("a\n\n  b") == "a b"
        assert len(lineup_check.scrub("x" * 400)) == 200


class TestRun:
    """The whole script, with `served` stubbed. Nothing here touches the network."""

    def stub(self, monkeypatch, catalogue):
        monkeypatch.setattr(lineup_check, "served", lambda entry, key="": catalogue)
        monkeypatch.setattr(lineup_check, "discoverable", lambda: [zen()])

    def test_a_quiet_day_exits_zero_and_reports_no_change(self, monkeypatch, tmp_path):
        self.stub(monkeypatch, list(ZEN.models))
        ledger = tmp_path / "lineup.json"
        # First run seeds; second is the quiet one.
        lineup_check.run(options(ledger=str(ledger)))
        code, body, changed = lineup_check.run(options(ledger=str(ledger)))
        assert code == 0
        assert changed is False
        assert "**Changed:**" not in body

    def test_it_writes_a_ledger_that_round_trips(self, monkeypatch, tmp_path):
        self.stub(monkeypatch, ["hy3-free", "claude-opus-5"])
        ledger = tmp_path / "nested" / "lineup.json"
        lineup_check.run(options(ledger=str(ledger)))
        found = json.loads(ledger.read_text())
        assert found["providers"]["opencode"]["free"] == ["hy3-free"]
        assert found["checked"]

    def test_fail_on_drift_is_opt_in(self, monkeypatch, tmp_path):
        """A free tier rotating its lineup is not this repository's fault, so the
        default is a report rather than a red build — the same reasoning `EVAL.md`
        gives for Axis B never being gated."""
        self.stub(monkeypatch, ["brand-new-free"])
        ledger = tmp_path / "lineup.json"
        lineup_check.run(options(ledger=str(ledger)))
        self.stub(monkeypatch, ["brand-new-free", "newer-free"])
        assert lineup_check.run(options(ledger=str(ledger)))[0] == 0
        code, _, changed = lineup_check.run(
            options(ledger=str(ledger), fail_on_drift=True)
        )
        assert changed is True
        assert code == 1

    def test_an_unreachable_endpoint_is_a_finding_not_a_crash(
        self, monkeypatch, tmp_path
    ):
        def boom(entry, key=""):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(lineup_check, "served", boom)
        monkeypatch.setattr(lineup_check, "discoverable", lambda: [zen()])
        code, body, _ = lineup_check.run(options(ledger=str(tmp_path / "l.json")))
        assert code == 2
        assert "Could not list models" in body

    def test_update_holds_back_a_model_whose_probe_got_nothing(
        self, monkeypatch, tmp_path
    ):
        """Served is not working. `north-mini-code-free` was in the profile's list and
        answering 401 from Zen's own upstream, and a list-only check called that
        lineup healthy."""
        target = tmp_path / "rcc.toml"
        target.write_text(
            '[[providers]]\nname = "opencode"\nkind = "openai"\n'
            'base_url = "http://x/v1"\nmodels = [\n    "known-free",\n]\n'
            'free_marks = ["-free"]\nfree_only = true\n'
        )
        loaded = profile.load(str(target))
        monkeypatch.setattr(profile, "active", lambda: loaded)
        monkeypatch.setattr(lineup_check, "_active", lambda: loaded)
        monkeypatch.setattr(lineup_check, "discoverable", lambda: list(loaded.providers))
        monkeypatch.setattr(
            lineup_check, "served", lambda entry, key="": ["known-free", "dud-free"]
        )
        monkeypatch.setattr(lineup_check.providers, "api_key", lambda name: "k")
        monkeypatch.setattr(
            lineup_check,
            "probe",
            lambda entry, key, model_id, tools=True: {
                "model": model_id, "status": 200, "answered": False, "tier": "free",
                "seconds": 1.0, "chars": 0,
            },
        )
        code, body, _ = lineup_check.run(
            options(ledger=str(tmp_path / "l.json"), probe=True, update=True)
        )
        assert code == 0
        assert "Held back" in body
        assert "dud-free" not in target.read_text()

    def test_update_appends_a_model_whose_probe_answered(self, monkeypatch, tmp_path):
        target = tmp_path / "rcc.toml"
        target.write_text(
            '[[providers]]\nname = "opencode"\nkind = "openai"\n'
            'base_url = "http://x/v1"\nmodels = [\n    "known-free",\n]\n'
            'free_marks = ["-free"]\nfree_only = true\n'
        )
        loaded = profile.load(str(target))
        monkeypatch.setattr(lineup_check, "_active", lambda: loaded)
        monkeypatch.setattr(lineup_check, "discoverable", lambda: list(loaded.providers))
        monkeypatch.setattr(
            lineup_check, "served", lambda entry, key="": ["known-free", "good-free"]
        )
        monkeypatch.setattr(lineup_check.providers, "api_key", lambda name: "k")
        monkeypatch.setattr(
            lineup_check,
            "probe",
            lambda entry, key, model_id, tools=True: {
                "model": model_id, "status": 200, "answered": True, "tier": "free",
                "seconds": 0.8, "chars": 40, "tool_calls": 1,
            },
        )
        lineup_check.run(
            options(ledger=str(tmp_path / "l.json"), probe=True, update=True)
        )
        assert profile.load(str(target)).provider("opencode").models == (
            "known-free", "good-free",
        )

    def test_the_probe_budget_says_what_it_dropped(self, monkeypatch, tmp_path):
        """A cap nobody is told about reads as "everything was covered"."""
        self.stub(monkeypatch, ["a-paid", "b-paid", "c-paid"])
        monkeypatch.setattr(lineup_check.providers, "api_key", lambda name: "k")
        monkeypatch.setattr(
            lineup_check,
            "probe",
            lambda entry, key, model_id, tools=True: {
                "model": model_id, "status": 401, "tier": "paid", "answered": False,
            },
        )
        _, body, _ = lineup_check.run(
            options(ledger=str(tmp_path / "l.json"), probe=True, probe_budget=1)
        )
        assert "2 unclassified name(s) went unprobed" in body

    def test_probing_without_a_key_says_so_rather_than_pretending(
        self, monkeypatch, tmp_path
    ):
        self.stub(monkeypatch, ["hy3-free", "claude-opus-5"])
        monkeypatch.setattr(lineup_check.providers, "api_key", lambda name: "")
        _, body, _ = lineup_check.run(
            options(ledger=str(tmp_path / "l.json"), probe=True)
        )
        assert "nothing was probed" in body


class TestProbeCost:
    def test_a_probe_asks_for_the_budget_the_app_would(self, monkeypatch):
        """The reasoning-model trap. `muse-spark-1.2-contributor-free` at
        `max_tokens=200` returns `completion_tokens: 200` and an empty completion,
        three times out of three — its thinking is not emitted and it never reaches the
        answer. A cheap probe would report a working model as a dead endpoint, and
        `--update` would hold it back on that evidence.
        """
        sent = {}

        class Response:
            status_code = 200

            def iter_lines(self):
                return iter(['data: [DONE]'])

            def read(self):
                return b""

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def stream(self, method, url, json=None, headers=None):
                sent.update(json or {})
                return Response()

        class Stub:
            Client = staticmethod(lambda **kwargs: Client())
            Timeout = staticmethod(lambda *a, **k: None)

        monkeypatch.setitem(__import__("sys").modules, "httpx", Stub)
        Response.__enter__ = lambda self: self
        Response.__exit__ = lambda self, *exc: False
        lineup_check.probe(zen(), "k", "muse-spark-1.2-contributor-free")
        assert sent["max_tokens"] == config.MAX_TOKENS
        assert sent["max_tokens"] >= 4000, "a reasoning model needs room to think"
        # Offered a real tool, so the verdict can say whether it can call one.
        assert sent["tools"][0]["function"]["name"] == "search_docs"
