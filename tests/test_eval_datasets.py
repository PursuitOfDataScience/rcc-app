"""The evaluation sets are well-formed, and each one can actually fail.

A dataset is code with no assertions in it. The two failure modes are a case that is
wrong (a "nonexistent" partition that exists — eight of those, caught by
`tools/gate_check.py --audit`) and a case that cannot fail: a canary the corpus already
contains, a leak phrase that is not in the system prompt, a gold page that is not
indexed. The second kind is worse, because it reads as a pass forever.
"""

from __future__ import annotations

import pytest

import evals
from sage import prompts


@pytest.fixture(scope="module")
def corpus_text(real_corpus):
    return "\n".join(chunk.text for chunk in real_corpus.chunks).lower()


class TestShape:
    def test_all_four_sets_are_populated(self):
        assert len(evals.questions()) >= 60
        assert len(evals.negatives()) >= 35
        assert len(evals.identifiers()) >= 5
        assert len(evals.conversations()) >= 4
        assert len(evals.injections()) >= 4

    @pytest.mark.parametrize(
        "loader", [evals.questions, evals.negatives, evals.identifiers]
    )
    def test_no_question_is_asked_twice(self, loader):
        texts = [case.text for case in loader()]
        duplicated = {text for text in texts if texts.count(text) > 1}
        assert not duplicated, "duplicated cases: " + "; ".join(sorted(duplicated))

    def test_every_kind_is_one_of_the_two_we_report(self):
        kinds = {case.kind for case in evals.questions()}
        assert kinds <= {"asked", "faq"}, kinds

    def test_the_faq_split_is_marked_as_the_easy_one(self):
        """Both splits must exist, because they measure different things.

        A question lifted from its own page is trivially retrievable from that page and
        scores near 100%: a ceiling check. Only the `asked` split discriminates.
        """
        assert evals.questions("faq")
        assert evals.questions("asked")


class TestTheGoldLabels:
    """The answerable sets' own labels, which only the conversation set was holding.

    `TestConversations.test_every_gold_page_is_indexed` does this for
    `conversations.toml` and stops there — so the 78 labels that produce the recall
    figure on the card were unchecked. Each failure here is silent in the direction that
    reads as a pass:

    A gold page with a typo in it can never be matched, so that question is a permanent
    miss and recall@5 is understated forever with nothing to show why. A `must_mention`
    token that appears nowhere on its own gold pages is a requirement no correct answer
    can meet, so every model is charged a `missing-required-token` defect it had no way
    to avoid — the dataset's version of a check that always fires. And a question in two
    sets at once is labelled both answerable and unanswerable, and scored both ways.
    """

    def answerable(self):
        return [*evals.questions(), *evals.identifiers()]

    def test_every_gold_page_is_indexed(self, real_corpus):
        known = {chunk.path for chunk in real_corpus.chunks}
        missing = [
            f"{case.text[:48]!r} -> {page}"
            for case in self.answerable()
            for page in getattr(case, "pages", ()) or ()
            if page not in known
        ]
        assert not missing, "gold pages that are not indexed: " + "; ".join(missing)

    def test_every_required_token_is_obtainable_from_its_own_gold_pages(
        self, real_corpus
    ):
        by_page: dict[str, list[str]] = {}
        for chunk in real_corpus.chunks:
            by_page.setdefault(chunk.path, []).append(chunk.text)

        unobtainable = []
        for case in self.answerable():
            required = getattr(case, "must_mention", ()) or ()
            pages = getattr(case, "pages", ()) or ()
            if not required or not pages:
                continue
            blob = " ".join(
                text for page in pages for text in by_page.get(page, [])
            ).lower()
            unobtainable += [
                f"{token!r} is on none of {list(pages)} ({case.text[:40]!r})"
                for token in required
                if token.lower() not in blob
            ]
        assert not unobtainable, (
            "required tokens no correct answer could produce: " + "; ".join(unobtainable)
        )

    def test_no_question_is_in_two_sets_at_once(self):
        """Across the sets, not within one — which is what `TestShape` already covers.

        A question in both `questions.toml` and `negatives.toml` is labelled answerable
        and unanswerable, counts in both denominators, and is scored both ways.
        """
        def normalise(text: str) -> str:
            return " ".join(text.lower().split()).rstrip("?.")

        sets = {
            "questions": evals.questions(),
            "negatives": evals.negatives(),
            "identifiers": evals.identifiers(),
        }
        texts = {name: {normalise(case.text) for case in cases}
                 for name, cases in sets.items()}
        for first in sorted(texts):
            for second in sorted(texts):
                if first >= second:
                    continue
                shared = texts[first] & texts[second]
                assert not shared, (
                    f"in both {first} and {second}: {sorted(shared)[:3]}"
                )

    # A fourth test was written here and deleted: "no negative carries a gold page".
    # `Negative` has no `pages` field, so `replace(case, pages=...)` is a TypeError and
    # nothing could ever make it fail — which is the exact failure mode named at the top
    # of this file, written into the file that warns about it. The dataclass is the
    # guarantee; a test restating it would read as coverage and be none.


class TestConversations:
    def test_every_case_has_at_least_two_turns(self):
        """One turn is not a conversation, and this set exists for the follow-up."""
        short = [case.name for case in evals.conversations() if len(case.turns) < 2]
        assert not short, "single-turn conversations: " + "; ".join(short)

    def test_every_turn_has_text(self):
        empty = [
            case.name for case in evals.conversations()
            for turn in case.turns
            if not str(turn.get("text", "")).strip()
        ]
        assert not empty

    def test_every_gold_page_is_indexed(self, real_corpus):
        known = {chunk.path for chunk in real_corpus.chunks}
        missing = [
            f"{case.name}: {page}"
            for case in evals.conversations()
            for turn in case.turns
            for page in turn.get("pages", ())
            if page not in known
        ]
        assert not missing, "gold pages that are not indexed: " + "; ".join(missing)

    def test_one_case_expects_a_caveat(self):
        """A conversation that starts well must not license a wrong answer later."""
        expectations = {
            str(turn.get("expect", "answer"))
            for case in evals.conversations()
            for turn in case.turns
        }
        assert "caveat" in expectations


class TestInjections:
    def test_no_canary_is_already_in_the_corpus(self, corpus_text):
        """Otherwise a compliant answer and a documented fact are indistinguishable."""
        present = [
            f"{case.name}: {case.canary}"
            for case in evals.injections()
            if case.canary.lower() in corpus_text
        ]
        assert not present, "canaries the corpus contains: " + "; ".join(present)

    def test_every_leak_phrase_is_really_in_the_system_prompt(self, profile):
        """The check for a recited prompt cannot fire on a phrase the prompt lacks."""
        prompt = prompts.system_prompt(profile).lower()
        missing = [
            f"{case.name}: {phrase!r}"
            for case in evals.injections()
            for phrase in case.leaks
            if phrase.lower() not in prompt
        ]
        assert not missing, "leak phrases not in the prompt: " + "; ".join(missing)

    def test_the_question_is_not_about_the_file(self):
        """Asked "what does this file say?", quoting the injection is the right answer.

        The question has to be about something else, or the check cannot tell obedience
        from an accurate summary. Approximated by requiring the question to name a
        documentation topic rather than the attachment.
        """
        for case in evals.injections():
            lowered = case.question.lower()
            assert "file" not in lowered and "attach" not in lowered, case.name

    def test_every_case_carries_content_and_a_canary(self):
        for case in evals.injections():
            assert case.content.strip(), case.name
            assert case.canary.strip(), case.name
            assert case.filename.strip(), case.name
