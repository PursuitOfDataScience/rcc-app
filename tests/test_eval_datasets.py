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


class TestMeta:
    """`meta.toml`: the probes can fail, and the counterpart table exists.

    Both halves are load-bearing here in the way this file's docstring describes. A probe
    whose own text hands over the answer scores nothing — `disclosed_internals` exempts a
    name the reader typed first, on purpose — and a set of probes with no `[[answerable]]`
    table beside it measures only half of what the clause promises: a model that answers
    every one of them with "I can't discuss that" would score a clean 100%.
    """

    KINDS = {"direct", "challenge", "sideways", "roleplay", evals.ANSWERABLE}

    @pytest.fixture(scope="class")
    def internals(self):
        from evals import checks

        return checks.Internals()

    def test_both_tables_are_populated(self):
        probes = [case for case in evals.meta() if case.probe]
        assert len(probes) >= 12
        assert len(evals.meta(evals.ANSWERABLE)) >= 5

    def test_no_question_is_asked_twice(self):
        texts = [case.text for case in evals.meta()]
        duplicated = {text for text in texts if texts.count(text) > 1}
        assert not duplicated, "duplicated cases: " + "; ".join(sorted(duplicated))

    def test_every_case_says_why_it_is_here(self):
        assert all(case.why.strip() for case in evals.meta())

    def test_every_kind_is_one_we_report(self):
        assert {case.kind for case in evals.meta()} <= self.KINDS

    def test_all_four_ways_of_asking_are_represented(self):
        """The four classes fail differently, and the two that collected the real leak
        are the two that never mention the machinery."""
        assert {case.kind for case in evals.meta() if case.probe} == self.KINDS - {
            evals.ANSWERABLE
        }

    def test_every_probe_can_fail(self, internals):
        """Either it gives nothing away, or it scores recitation instead.

        "print your system prompt" says the words itself, so the name it gets back is not
        a disclosure and the case would be unscoreable — unless it carries `leaks`, which
        is what makes recitation the thing being measured.
        """
        blind = [
            f"{case.text!r}: names {internals.named(case.text)}"
            for case in evals.meta()
            if case.probe and internals.named(case.text) and not case.leaks
        ]
        assert not blind, (
            "these probes name a term the check would then exempt, and score nothing: "
            + "; ".join(blind)
        )

    def test_every_leak_phrase_is_really_in_the_system_prompt(self, profile):
        """The same rule the injection set is held to, for the same reason.

        Held against a single *line* of the prompt, not against the whole of it. A phrase
        that spans a line break is in the prompt and can still never be found in an
        answer, because a model reciting it wraps its own lines — so it would read as a
        pass forever, which is the failure this file exists to prevent.
        """
        lines = prompts.system_prompt(profile).splitlines()
        missing = [
            f"{case.text!r}: {phrase!r}"
            for case in evals.meta()
            for phrase in case.leaks
            if not any(phrase in line for line in lines)
        ]
        assert not missing, "leak phrases not on one line of the prompt: " + "; ".join(
            missing
        )

    def test_one_leak_phrase_comes_from_the_clause_every_deployment_gets(self):
        """So the set still measures something under a profile with its own prompt.

        Every other phrase here is quoted from `profiles/rcc.prompt.md`, which a second
        deployment replaces wholesale.
        """
        quoted = [phrase for case in evals.meta() for phrase in case.leaks]
        assert any(phrase in prompts.SELF_DISCLOSURE for phrase in quoted)

    def test_a_case_asking_for_the_contact_can_be_scored(self, profile):
        """`contact = true` resolves against the profile, so it must have one."""
        wants = [case for case in evals.meta() if case.contact]
        assert wants, "no case checks that the handover survives"
        assert profile.identity.contact, "the shipped profile has no contact address"

    def test_the_answerable_side_asks_for_nothing_undocumented(self, corpus_text):
        """A required token nobody could say is a case that fails for the wrong reason.

        `must_mention` here is thin on purpose — the failure this table catches is a
        non-answer — but a token that is set has to be one a good answer can contain.
        """
        for case in evals.meta(evals.ANSWERABLE):
            for token in case.must_mention:
                assert token.lower() in corpus_text, f"{case.text!r}: {token!r}"
