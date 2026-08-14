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
