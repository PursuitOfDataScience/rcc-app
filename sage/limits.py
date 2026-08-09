"""Usage limits: a token bucket per person, and a budget for the whole deployment.

Two limits rather than one, because they protect different things and the numbers
that matter are not the same:

* **The bucket** bounds one person's *turns*. It exists so a single reader cannot
  monopolise a shared deployment, and so a runaway client cannot loop.
* **The budget** bounds the deployment's *provider calls*. It exists so the shared
  API key survives the day. This is the one that matters: a spent key does not
  degrade the app, it ends it, for everybody, until someone notices.

They are not interchangeable. One turn is up to `MAX_TOOL_ROUNDS + 1` provider calls
— search, then a read per round, then the answer — so a limit counted in messages
says almost nothing about what the key is being charged. Counting turns for the
person and calls for the budget is the whole reason this module has two mechanisms.

A token bucket rather than a fixed window, for the per-person limit. A window is
worse at both ends: it lets someone spend the whole allowance at 11:59 and the whole
next one at 12:00, and it refuses a legitimate quick follow-up that happens to land
just inside a boundary. A bucket answers the question actually being asked — "has
this person been going faster than the sustained rate, for long enough to matter" —
with two parameters instead of a cliff.

No Streamlit and no wall clock in here. `now` is a parameter, so the tests run a day
of traffic in a millisecond, and the arithmetic is checkable without a browser.
Callers pass `time.monotonic()`, which is immune to the clock being adjusted under
a long-running deployment.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Verdict:
    """Whether a turn may start, and what to tell the reader if not."""

    allowed: bool
    retry_after: float = 0.0
    message: str = ""


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def humanise(seconds: float) -> str:
    """A wait a reader can act on. Rounded up, because rounding down invites a
    retry that is refused again for the sake of half a second."""
    seconds = max(1, int(seconds + 0.999))
    if seconds < 60:
        return f"{_plural(seconds, 'second')}"
    minutes = (seconds + 59) // 60
    if minutes < 60:
        return f"{_plural(minutes, 'minute')}"
    return f"{_plural((minutes + 59) // 60, 'hour')}"


@dataclass
class _Bucket:
    tokens: float
    updated: float


@dataclass
class _Window:
    """A fixed window, which is the right shape for a daily cap.

    The cliff a fixed window has at its boundary is exactly what the bucket above is
    for; doubling up on rolling windows here would cost a timestamp per turn for an
    accuracy nobody can perceive in a per-day number.
    """

    used: int = 0
    started: float = 0.0

    def roll(self, now: float, window: float) -> None:
        if now - self.started >= window:
            self.used = 0
            self.started = now


@dataclass
class Limiter:
    """Per-identity turn limits and one deployment-wide call budget.

    Every setting is disabled by passing 0 or less, so a deployment can adopt one
    limit without the others and this module stays inert until asked for.
    """

    burst: int = 5
    refill_seconds: float = 15.0
    daily_turns: int = 100
    daily_window: float = 86_400.0
    call_budget: int = 0
    budget_window: float = 86_400.0

    _buckets: dict[str, _Bucket] = field(default_factory=dict)
    _days: dict[str, _Window] = field(default_factory=dict)
    _budget: _Window = field(default_factory=_Window)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # Streamlit serves every session from one process and gives each its own thread,
    # so two readers really can land in here at the same moment. The critical
    # sections are a few microseconds of arithmetic; one lock is simpler to reason
    # about than per-identity locking and cannot deadlock.

    def check(self, who: str, now: float) -> Verdict:
        """May `who` start a turn now? Consumes a token when the answer is yes.

        Deliberately one call rather than a check followed by a commit: two calls
        race, and the failure mode of that race is the limit silently not applying.
        """
        with self._lock:
            if self.call_budget > 0:
                self._budget.roll(now, self.budget_window)
                if self._budget.used >= self.call_budget:
                    left = self.budget_window - (now - self._budget.started)
                    return Verdict(
                        False,
                        left,
                        "Sage has reached the usage limit set for this deployment. "
                        f"It resets in {humanise(left)}.",
                    )

            if self.daily_turns > 0:
                day = self._days.setdefault(who, _Window(started=now))
                day.roll(now, self.daily_window)
                if day.used >= self.daily_turns:
                    left = self.daily_window - (now - day.started)
                    return Verdict(
                        False,
                        left,
                        f"That is {self.daily_turns} questions today, which is the "
                        f"per-person limit here. It resets in {humanise(left)}.",
                    )

            if self.burst > 0 and self.refill_seconds > 0:
                bucket = self._buckets.get(who)
                if bucket is None:
                    bucket = _Bucket(tokens=float(self.burst), updated=now)
                    self._buckets[who] = bucket
                gained = (now - bucket.updated) / self.refill_seconds
                bucket.tokens = min(self.burst, bucket.tokens + gained)
                bucket.updated = now
                if bucket.tokens < 1.0:
                    wait = (1.0 - bucket.tokens) * self.refill_seconds
                    return Verdict(
                        False,
                        wait,
                        "You are asking faster than Sage answers here. Try again in "
                        f"{humanise(wait)}.",
                    )
                bucket.tokens -= 1.0

            if self.daily_turns > 0:
                self._days[who].used += 1
            return Verdict(True)

    def record_calls(self, count: int, now: float) -> None:
        """Charge the deployment budget for provider calls a turn actually made.

        Charged after the fact rather than reserved up front, because the number is
        not knowable in advance — a question answered from one search costs two calls
        and one that walks six documents costs seven. A turn already running is never
        interrupted for the budget, so the cap can overshoot by at most one turn's
        worth of calls. That is the right trade: a half-written answer cut off
        mid-sentence is a worse failure than a slightly soft limit.
        """
        if self.call_budget <= 0 or count <= 0:
            return
        with self._lock:
            self._budget.roll(now, self.budget_window)
            self._budget.used += count

    def snapshot(self, now: float) -> dict:
        """Counters for logging and for an operator asking "how close are we?"."""
        with self._lock:
            if self.call_budget > 0:
                self._budget.roll(now, self.budget_window)
            return {
                "calls_used": self._budget.used,
                "call_budget": self.call_budget,
                "identities": len(self._buckets),
            }

    def prune(self, now: float) -> int:
        """Forget identities that have not been seen for two windows.

        Without this the dictionaries are a slow leak on a long-running deployment:
        one entry per person who ever visited, kept for the life of the process.
        """
        horizon = 2 * max(self.daily_window, self.refill_seconds * max(self.burst, 1))
        with self._lock:
            stale = [
                key for key, bucket in self._buckets.items()
                if now - bucket.updated > horizon
            ]
            for key in stale:
                self._buckets.pop(key, None)
                self._days.pop(key, None)
            return len(stale)
