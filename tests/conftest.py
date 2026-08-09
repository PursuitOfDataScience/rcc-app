import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Cleared before `sage` is imported, because sage/config.py reads every setting at
# import time — a fixture cannot walk that back, it can only affect the settings read
# per call. Anyone who has actually run the app has these exported, and the suite
# answered differently for them than it did for CI: with OPENCODE_API_KEY set,
# `test_missing_api_key_stops_with_a_clear_message` deleted MISTRAL_API_KEY, found the
# app still had a usable provider, and failed. A developer's shell is not a test
# fixture.
_APP_ENV_PREFIXES = ("SAGE_", "RCC_")
_APP_ENV_NAMES = (
    "MISTRAL_API_KEY",
    "OPENCODE_API_KEY",
    "OPENCODE_BASE_URL",
    "LOG_LEVEL",
)


def _clear_app_env() -> None:
    for name in list(os.environ):
        if name.startswith(_APP_ENV_PREFIXES) or name in _APP_ENV_NAMES:
            del os.environ[name]


_clear_app_env()

from sage import corpus as corpus_mod  # noqa: E402
from sage.search import Index  # noqa: E402


@pytest.fixture(autouse=True)
def neutral_environment():
    """Every test starts from the defaults, whatever the developer exports.

    Import-time settings are already handled above; this covers the ones read per
    call — `config.api_key()` among them — and undoes anything a test leaves behind.
    """
    _clear_app_env()
    yield
    _clear_app_env()


@pytest.fixture(scope="session")
def real_corpus():
    """The bundled docs/ + web/ snapshot. Skips if the trees are absent."""
    built = corpus_mod.build()
    if not built.chunks:
        pytest.skip("no documentation trees available")
    return built


@pytest.fixture(scope="session")
def real_index(real_corpus):
    return Index(real_corpus)
