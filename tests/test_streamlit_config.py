"""What `.streamlit/config.toml` has to agree with.

Two settings in there are not free-standing preferences: each one is half of a pair,
and both halves shipped broken because nothing held them together.
"""

from __future__ import annotations

import os

import tomllib

from sage import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def settings() -> dict:
    with open(os.path.join(ROOT, ".streamlit", "config.toml"), "rb") as handle:
        return tomllib.load(handle)


def stylesheet() -> str:
    with open(os.path.join(ROOT, "static", "app.css"), encoding="utf-8") as handle:
        return handle.read()


class TestUploadCeiling:
    """Streamlit's cap must stay above the app's, so the app is the one that speaks.

    Streamlit refuses an oversized upload itself and renders the reason *inside* the
    file-uploader widget — which app.css hides, because uploads are driven from the
    paperclip in the composer. With the two limits set to the same number, an 11 MB
    file was refused by Streamlit and the explanation went with it: no chip, no
    warning, nothing on the page at all. Above it, `files.process` does the refusing
    and says so where the reader is looking.
    """

    def test_streamlit_cap_is_above_the_app_cap(self):
        megabytes = settings()["server"]["maxUploadSize"]
        assert megabytes * 1024 * 1024 > config.MAX_UPLOAD_BYTES, (
            "server.maxUploadSize must exceed SAGE_MAX_UPLOAD_BYTES, or Streamlit "
            "refuses the file first and its message is hidden with the uploader"
        )

    def test_the_headroom_is_not_unbounded(self):
        """The bytes still arrive before anything can refuse them."""
        megabytes = settings()["server"]["maxUploadSize"]
        assert megabytes * 1024 * 1024 <= 4 * config.MAX_UPLOAD_BYTES


class TestTheme:
    """The app's palette and Streamlit's own have to move together.

    app.css keys its dark palette off `prefers-color-scheme`. Streamlit only follows
    the browser while it has no custom theme — and setting *any* `[theme]` value makes
    one, whose `base` defaults to light. That combination put the dark palette on a
    white page for every dark-mode reader: source links at 1.9:1, a near-black popover
    panel, pale grey control text.

    So either both schemes are stated, or Streamlit is pinned to one and app.css must
    be too. Anything else is the desync coming back.
    """

    def test_the_stylesheet_still_follows_the_browser(self):
        assert "@media (prefers-color-scheme: dark)" in stylesheet()

    def test_both_schemes_are_configured(self):
        theme = settings().get("theme", {})
        if not theme:
            return  # no custom theme at all: Streamlit follows the browser
        assert "base" not in theme, (
            "a pinned base stops Streamlit following the browser while app.css "
            "still does — state [theme.light] and [theme.dark] instead"
        )
        assert "light" in theme and "dark" in theme, (
            "any [theme] value makes the theme custom, and a custom theme renders "
            "light unless [theme.dark] exists — so a dark-mode reader gets app.css's "
            "dark palette on Streamlit's white page"
        )

    def test_the_dark_primary_is_not_the_light_one(self):
        """#800000 on Streamlit's near-black page is 1.73:1."""
        theme = settings().get("theme", {})
        if "light" in theme and "dark" in theme:
            light = theme["light"].get("primaryColor")
            dark = theme["dark"].get("primaryColor")
            if light and dark:
                assert light.lower() != dark.lower()
