"""Where the parts are put together, and the only place that knows all of them.

    from sage import runtime
    sage = runtime.build()          # profile -> corpus -> retriever -> tools -> prompt

Every module under `sage/` does one job and takes what it needs as an argument. That
only works if something assembles them, and this is it: one function, top to bottom,
readable as a list of the decisions a deployment gets to make.

The UI holds a `Runtime` and asks it for things. It does not import the corpus
builder, the retrieval engine or the tool registry, which is what keeps "swap the
documentation" from meaning "edit the view".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from . import corpus as corpus_module
from . import prompts, retrieval, tools
from .corpus import Corpus
from .profile import Profile
from .profile import active as _active
from .retrieval import Retriever
from .tools import Toolset

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Runtime:
    """One assembled assistant: what it is, what it has read, how it searches."""

    profile: Profile
    corpus: Corpus
    retriever: Retriever
    toolset: Toolset
    system_prompt: str

    @property
    def identity(self):
        return self.profile.identity

    @property
    def copy(self):
        return self.profile.copy

    @property
    def examples(self):
        return self.profile.examples

    @property
    def tool_schemas(self) -> list[dict]:
        return self.toolset.schemas

    def summary(self) -> str:
        return corpus_module.summarize(self.corpus)


def build(profile: Profile | None = None) -> Runtime:
    """Read the documents, index them, and bind the tools to that index."""
    chosen = profile or _active()
    built = corpus_module.build(chosen.sources)
    if not built.chunks:
        # Not fatal — the app still answers, and says the documentation does not
        # cover it, every single time. That is a confusing thing to debug from the
        # answers, so it is said once, here, in the log.
        logger.error(
            "No documents were indexed from %s. Check the paths in %s.",
            ", ".join(source.path for source in chosen.sources) or "(no sources)",
            chosen.origin or "the built-in profile",
        )
    retriever = retrieval.build(built, chosen.retrieval, chosen.identity.documentation)
    logger.info(
        "%s ready: %s, %s retrieval",
        chosen.identity.name,
        corpus_module.summarize(built),
        chosen.retrieval.engine,
    )
    return Runtime(
        profile=chosen,
        corpus=built,
        retriever=retriever,
        toolset=tools.build(retriever, chosen.identity),
        system_prompt=prompts.system_prompt(chosen),
    )
