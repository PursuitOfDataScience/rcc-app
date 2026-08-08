import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Pin the profile before anything imports `sage`. Most of this suite asserts RCC
# behaviour — its URLs, its synonyms, its welcome copy — and `SAGE_PROFILE` in a
# developer's shell or a CI job would otherwise decide, silently, whether those
# tests are checking the thing they name. Tests that care about another profile
# pass it explicitly (`profiles.get("site")`) or set the variable themselves.
os.environ["SAGE_PROFILE"] = "rcc"

from sage import corpus as corpus_mod  # noqa: E402
from sage.search import Index  # noqa: E402


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
