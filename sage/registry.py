"""A named-factory registry, and the error a bad name produces.

Four things in this package are chosen by name at runtime rather than by import:
how a file becomes documents (`corpus.readers`), how a document becomes a URL
(`corpus.urls`), how a query becomes results (`retrieval`), and how a provider talks
to its endpoint (`providers`). Each of those is a place a deployment substitutes its
own implementation, so each needs the same two operations — register under a name,
look up by name — and the same error when the name is wrong.

Written once here rather than four times, because the fourth copy is where they start
to disagree about whether an unknown name raises or returns None. It raises: a corpus
built with a reader nobody registered is an empty index, and an empty index is an
assistant that politely answers "the documentation does not appear to cover it" to
every question ever asked of it.
"""

from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._entries: dict[str, T] = {}

    def register(self, name: str, entry: T) -> T:
        """Add an implementation. Re-registering a name replaces it.

        Replacement is allowed on purpose: it is how a deployment overrides a
        built-in — import the package, register your own `markdown`, and every
        source that asks for one gets yours.
        """
        self._entries[name] = entry
        return entry

    def get(self, name: str) -> T:
        try:
            return self._entries[name]
        except KeyError:
            raise LookupError(
                f"Unknown {self._kind}: {name!r}. Registered: "
                f"{', '.join(sorted(self._entries)) or '(none)'}"
            ) from None

    def remove(self, name: str) -> None:
        """Forget an implementation. Unknown names are not an error.

        Here for the caller that registered one temporarily — a test, or a process
        rebuilding itself for a second profile — so that undoing a registration does
        not mean reaching into the dictionary.
        """
        self._entries.pop(name, None)

    def has(self, name: str) -> bool:
        return name in self._entries

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def __contains__(self, name: object) -> bool:
        return name in self._entries
