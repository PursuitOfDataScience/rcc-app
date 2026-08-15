"""Reading settings out of the environment — the module every knob passes through.

It had no tests of its own, which is how `nan` got through. `float("nan")` parses, and
every comparison with `nan` is False, so the `minimum` guard waved it past and so does
every threshold it is later compared against: `SAGE_MIN_CONFIDENT_SCORE=nan` makes
`top_score < min_confident_score` False for every query, which switches the refusal gate
off in silence. A mistyped variable must not be able to disable a guard.

The rule these all share: anything unusable keeps the shipped default, because a
deployment that fat-fingers a setting should behave like one that never set it.
"""

from __future__ import annotations

import math

import pytest

from sage import env

DEFAULT_INT = 10
DEFAULT_FLOAT = 20.0


@pytest.fixture
def value(monkeypatch):
    def set_to(raw: str | None):
        if raw is None:
            monkeypatch.delenv("SAGE_PROBE", raising=False)
        else:
            monkeypatch.setenv("SAGE_PROBE", raw)
    return set_to


class TestNumber:
    def read(self, minimum: float | None = 0.0) -> float:
        return env.number("SAGE_PROBE", DEFAULT_FLOAT, minimum=minimum)

    @pytest.mark.parametrize("raw", ["nan", "NaN", "-nan", "inf", "-inf", "Infinity", "1e999"])
    def test_a_non_finite_value_keeps_the_default(self, value, raw):
        """The one that matters: `nan` compares False against every threshold."""
        value(raw)
        assert self.read() == DEFAULT_FLOAT

    def test_nan_would_have_defeated_the_minimum_guard(self, value):
        """Stated as arithmetic so the reason is not merely asserted."""
        assert not (float("nan") < 0.0)
        value("nan")
        assert math.isfinite(self.read())

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("2.5", 2.5), ("0", 0.0), ("1e-3", 0.001), ("  2 ", 2.0), ("+3.5", 3.5)],
    )
    def test_a_usable_value_is_read(self, value, raw, expected):
        value(raw)
        assert self.read() == expected

    @pytest.mark.parametrize("raw", ["", "   ", "abc", "1,5", "20%"])
    def test_an_unusable_value_keeps_the_default(self, value, raw):
        value(raw)
        assert self.read() == DEFAULT_FLOAT

    def test_below_the_minimum_keeps_the_default(self, value):
        value("-1")
        assert self.read() == DEFAULT_FLOAT

    def test_no_minimum_allows_a_negative(self, value):
        value("-1")
        assert self.read(minimum=None) == -1.0

    def test_unset_keeps_the_default(self, value):
        value(None)
        assert self.read() == DEFAULT_FLOAT


class TestInteger:
    def read(self, minimum: int | None = 1) -> int:
        return env.integer("SAGE_PROBE", DEFAULT_INT, minimum=minimum)

    @pytest.mark.parametrize(("raw", "expected"), [("5", 5), (" 7 ", 7), ("+7", 7)])
    def test_a_usable_value_is_read(self, value, raw, expected):
        value(raw)
        assert self.read() == expected

    @pytest.mark.parametrize("raw", ["", "abc", "3.7", "1e3", "0x10", "nan", "inf"])
    def test_an_unusable_value_keeps_the_default(self, value, raw):
        """`int()` rejects all of these, which is why the float reader needed help."""
        value(raw)
        assert self.read() == DEFAULT_INT

    def test_a_negative_max_tokens_is_a_typo_not_a_choice(self, value):
        value("-1")
        assert self.read() == DEFAULT_INT

    def test_zero_is_allowed_where_zero_means_off(self, value):
        value("0")
        assert env.integer("SAGE_PROBE", DEFAULT_INT, minimum=0) == 0


class TestFlag:
    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on", " 1 "])
    def test_the_true_spellings(self, value, raw):
        value(raw)
        assert env.flag("SAGE_PROBE", False) is True

    @pytest.mark.parametrize("raw", ["0", "false", "no", "off", ""])
    def test_the_false_spellings(self, value, raw):
        value(raw)
        assert env.flag("SAGE_PROBE", True) is False

    @pytest.mark.parametrize("raw", ["maybe", "2", "y"])
    def test_a_word_it_does_not_know_keeps_the_default(self, value, raw):
        """Both directions, so an unrecognised word cannot silently read as off."""
        value(raw)
        assert env.flag("SAGE_PROBE", True) is True
        assert env.flag("SAGE_PROBE", False) is False

    def test_unset_keeps_the_default(self, value):
        value(None)
        assert env.flag("SAGE_PROBE", True) is True


class TestItems:
    def test_a_comma_separated_list(self, value):
        value("a,b")
        assert env.items("SAGE_PROBE", ()) == ("a", "b")

    def test_whitespace_and_empty_parts_are_dropped(self, value):
        value(" a , , b ")
        assert env.items("SAGE_PROBE", ()) == ("a", "b")

    def test_an_empty_value_clears_the_list(self, value):
        """`SAGE_EXCLUDE_HOSTS=` is how a deployment indexes everything again."""
        value("")
        assert env.items("SAGE_PROBE", ("kept",)) == ()

    def test_unset_keeps_the_default(self, value):
        value(None)
        assert env.items("SAGE_PROBE", ("kept",)) == ("kept",)

    def test_only_commas_clears_the_list(self, value):
        value(",,")
        assert env.items("SAGE_PROBE", ("kept",)) == ()


class TestText:
    def test_it_returns_the_raw_value_including_whitespace(self, value):
        value("  spaced  ")
        assert env.text("SAGE_PROBE", "default") == "  spaced  "

    def test_an_empty_value_is_not_the_default(self, value):
        """Deliberate: `SAGE_FEEDBACK_LOG=` means "no sink", not "the built-in one"."""
        value("")
        assert env.text("SAGE_PROBE", "default") == ""

    def test_unset_is_the_default(self, value):
        value(None)
        assert env.text("SAGE_PROBE", "default") == "default"
