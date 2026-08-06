import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
