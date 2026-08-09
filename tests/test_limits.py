"""The limiter's arithmetic, run at whatever speed the test wants.

`now` is a parameter everywhere in `sage.limits`, so a day of traffic costs no wall
clock here and none of these tests can go flaky on a slow machine.
"""

from __future__ import annotations

import pytest

from sage import limits


def make(**kwargs) -> limits.Limiter:
    """A limiter with everything off unless a test asks for it, so each test
    exercises one mechanism instead of whichever one happens to trip first."""
    base = {"burst": 0, "refill_seconds": 0, "daily_turns": 0, "call_budget": 0}
    base.update(kwargs)
    return limits.Limiter(**base)


class TestTokenBucket:
    def test_a_burst_is_allowed_then_the_rate_applies(self):
        limiter = make(burst=5, refill_seconds=15)
        assert all(limiter.check("me", 0.0).allowed for _ in range(5)), "the burst"
        assert not limiter.check("me", 0.0).allowed, "the sixth in the same instant"

    def test_a_token_comes_back_after_the_refill_interval(self):
        limiter = make(burst=2, refill_seconds=15)
        limiter.check("me", 0.0)
        limiter.check("me", 0.0)
        assert not limiter.check("me", 14.0).allowed
        assert limiter.check("me", 15.0).allowed

    def test_the_bucket_refills_to_capacity_and_no_further(self):
        """An hour away must not buy an hour's worth of questions at once."""
        limiter = make(burst=3, refill_seconds=10)
        for _ in range(3):
            limiter.check("me", 0.0)
        allowed = sum(limiter.check("me", 3600.0).allowed for _ in range(10))
        assert allowed == 3

    def test_the_wait_it_reports_is_long_enough_to_succeed(self):
        """A message that says "try in Ns" and is refused at N is worse than none."""
        limiter = make(burst=1, refill_seconds=15)
        limiter.check("me", 0.0)
        verdict = limiter.check("me", 0.0)
        assert not verdict.allowed
        assert limiter.check("me", verdict.retry_after).allowed

    def test_identities_do_not_share_a_bucket(self):
        limiter = make(burst=1, refill_seconds=15)
        assert limiter.check("a", 0.0).allowed
        assert not limiter.check("a", 0.0).allowed
        assert limiter.check("b", 0.0).allowed, "b is not charged for a's questions"

    def test_a_refused_turn_does_not_spend_a_token(self):
        """Otherwise hammering the button holds the bucket empty indefinitely."""
        limiter = make(burst=1, refill_seconds=10)
        limiter.check("me", 0.0)
        for _ in range(20):
            limiter.check("me", 1.0)
        assert limiter.check("me", 10.0).allowed


class TestDailyCap:
    def test_the_cap_applies_and_then_the_window_rolls(self):
        limiter = make(daily_turns=3, daily_window=100.0)
        assert sum(limiter.check("me", 0.0).allowed for _ in range(5)) == 3
        assert limiter.check("me", 100.0).allowed, "a fresh window"

    def test_a_refused_turn_is_not_counted_against_the_day(self):
        """Being rate-limited must not also cost you the day's allowance.

        Stepped one refill apart so the bucket is never the thing refusing after the
        first burst — otherwise this measures the bucket and says nothing about the
        daily counter.
        """
        limiter = make(burst=1, refill_seconds=10.0, daily_turns=5)
        assert limiter.check("me", 0.0).allowed  # day 1 of 5
        for _ in range(10):
            assert not limiter.check("me", 1.0).allowed, "refused by the bucket"
        allowed = sum(limiter.check("me", step * 10.0).allowed for step in range(1, 10))
        assert allowed == 4, "the remaining four of five, not fewer"


class TestDeploymentBudget:
    def test_calls_not_turns_are_what_exhaust_it(self):
        """The point of the budget: one turn can be seven provider calls."""
        limiter = make(call_budget=10)
        assert limiter.check("me", 0.0).allowed
        limiter.record_calls(7, 0.0)
        assert limiter.check("me", 0.0).allowed, "3 left"
        limiter.record_calls(3, 0.0)
        assert not limiter.check("me", 0.0).allowed

    def test_it_is_shared_across_everyone(self):
        limiter = make(call_budget=5)
        limiter.record_calls(5, 0.0)
        assert not limiter.check("someone-new", 0.0).allowed

    def test_the_window_rolls(self):
        limiter = make(call_budget=5, budget_window=100.0)
        limiter.record_calls(5, 0.0)
        assert not limiter.check("me", 50.0).allowed
        assert limiter.check("me", 100.0).allowed

    def test_the_budget_message_names_the_deployment_not_the_reader(self):
        """A reader who has asked one question must not be told it was their fault."""
        limiter = make(call_budget=1)
        limiter.record_calls(1, 0.0)
        message = limiter.check("me", 0.0).message.lower()
        assert "deployment" in message
        assert "you" not in message.split()


class TestDisabled:
    @pytest.mark.parametrize("kwargs", [
        {},
        {"burst": 0, "refill_seconds": 15},
        {"burst": 5, "refill_seconds": 0},
        {"daily_turns": 0},
        {"call_budget": 0},
    ])
    def test_zero_means_off(self, kwargs):
        limiter = make(**kwargs)
        limiter.record_calls(10_000, 0.0)
        assert all(limiter.check("me", 0.0).allowed for _ in range(50))


class TestHousekeeping:
    def test_stale_identities_are_forgotten(self):
        limiter = make(burst=2, refill_seconds=15, daily_turns=10, daily_window=100.0)
        limiter.check("old", 0.0)
        limiter.check("recent", 500.0)
        assert limiter.prune(500.0) == 1
        assert limiter.snapshot(500.0)["identities"] == 1

    def test_pruning_does_not_hand_back_an_unspent_day(self):
        """A live identity must keep its daily count across a prune."""
        limiter = make(daily_turns=2, daily_window=10_000.0)
        limiter.check("me", 0.0)
        limiter.check("me", 1.0)
        limiter.prune(2.0)
        assert not limiter.check("me", 3.0).allowed

    def test_snapshot_reports_the_budget(self):
        limiter = make(call_budget=100)
        limiter.record_calls(12, 0.0)
        assert limiter.snapshot(0.0) == {
            "calls_used": 12, "call_budget": 100, "identities": 0,
        }


class TestHumanise:
    @pytest.mark.parametrize("seconds,expected", [
        (0.1, "1 second"), (1, "1 second"), (2, "2 seconds"),
        (59, "59 seconds"), (60, "1 minute"), (61, "2 minutes"),
        (3600, "1 hour"), (7200, "2 hours"),
    ])
    def test_it_rounds_up(self, seconds, expected):
        """Rounding down invites a retry that is refused for half a second."""
        assert limits.humanise(seconds) == expected
