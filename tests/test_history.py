from sage import config, history
from sage.files import Attachment


def user(text, *attachments):
    """A user turn. Attachments are a list now — holding one is what made a second
    attached file look like a control that does nothing."""
    return {"role": "user", "text": text, "attachments": [a for a in attachments if a]}


def assistant(text):
    return {"role": "assistant", "text": text}


def test_system_prompt_leads():
    built = history.build([user("hi")], "SYSTEM")
    assert built[0] == {"role": "system", "content": "SYSTEM"}


def test_assistant_turns_are_kept_so_follow_ups_have_context():
    built = history.build([user("q1"), assistant("a1"), user("q2")], "S")
    assert [message["role"] for message in built] == [
        "system",
        "user",
        "assistant",
        "user",
    ]


def test_empty_turns_are_skipped():
    built = history.build([user("q"), assistant("")], "S")
    assert len(built) == 2


def test_the_latest_attachment_is_inlined():
    attachment = Attachment("paper.pdf", "pdf", "UNIQUE-BODY-TEXT", pages=3)
    built = history.build([user("summarise", attachment)], "S")
    assert "UNIQUE-BODY-TEXT" in built[-1]["content"]


def test_older_attachments_collapse_to_a_stub():
    """Asking three follow-ups about a PDF used to ship the PDF four times."""
    attachment = Attachment("paper.pdf", "pdf", "UNIQUE-BODY-TEXT", pages=3)
    messages = [
        user("summarise", attachment),
        assistant("Here is a summary."),
        user("and the conclusion?"),
    ]
    built = history.build(messages, "S")
    body = "\n".join(message["content"] for message in built)
    assert body.count("UNIQUE-BODY-TEXT") == 1

    messages.append(assistant("The conclusion is X."))
    messages.append(user("what about the method?"))
    later = history.build(messages, "S")
    joined = "\n".join(message["content"] for message in later)
    assert joined.count("UNIQUE-BODY-TEXT") == 1
    assert "paper.pdf" in joined


def test_only_the_most_recent_attachment_is_inlined():
    first = Attachment("one.txt", "text", "FIRST-BODY")
    second = Attachment("two.txt", "text", "SECOND-BODY")
    built = history.build(
        [user("a", first), assistant("ok"), user("b", second)], "S"
    )
    joined = "\n".join(message["content"] for message in built)
    assert "SECOND-BODY" in joined
    assert "FIRST-BODY" not in joined


def test_oldest_turns_are_dropped_when_over_budget():
    big = "x" * (config.HISTORY_CHAR_BUDGET // 3)
    messages = [user(f"{big}-{n}") for n in range(6)]
    built = history.build(messages, "S")
    total = sum(len(message["content"]) for message in built)
    assert total <= config.HISTORY_CHAR_BUDGET + len("S")
    # The newest question must survive trimming.
    assert built[-1]["content"].endswith("-5")


def test_a_single_oversized_turn_is_clipped_rather_than_dropped():
    messages = [user("y" * (config.HISTORY_CHAR_BUDGET * 2))]
    built = history.build(messages, "S")
    assert len(built) == 2
    assert len(built[1]["content"]) <= config.HISTORY_CHAR_BUDGET


def test_two_attachments_on_one_turn_both_reach_the_model():
    """One turn used to carry one file. Anything offered while a file was already
    attached was dropped, which from the outside was a control doing nothing."""
    log = Attachment("slurm-1.out", "text", "OOM-KILLED-LINE")
    script = Attachment("submit.sbatch", "text", "SBATCH-BODY")
    built = history.build([user("why did this die?", log, script)], "S")
    joined = "\n".join(str(message["content"]) for message in built)
    assert "OOM-KILLED-LINE" in joined
    assert "SBATCH-BODY" in joined


def test_an_image_is_offered_to_a_vision_model_as_a_picture():
    shot = Attachment(
        "pasted-image.png", "image", "", data=b"\x89PNG\r\n\x1a\nbody",
        mime="image/png",
    )
    built = history.build([user("what is this error?", shot)], "S", vision=True)
    parts = built[-1]["content"]
    assert isinstance(parts, list), "a vision turn is a list of parts"
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_an_image_is_not_offered_to_a_model_that_cannot_see():
    """An image sent to a text-only model is a 4xx, not a polite decline."""
    shot = Attachment(
        "pasted-image.png", "image", "", data=b"\x89PNG\r\n\x1a\nbody",
        mime="image/png",
    )
    built = history.build([user("what is this error?", shot)], "S", vision=False)
    assert isinstance(built[-1]["content"], str)
    assert "pasted-image.png" in built[-1]["content"]


# --- which models are offered the picture ----------------------------------
#
# `config.sees_images` is the switch every test above takes as given: `vision=` comes
# from it, and nothing else decides whether a screenshot travels as bytes or as a
# sentence. Kept here, beside what it switches, rather than left as the one input to
# these builds that nothing checks.


def test_a_model_that_can_see_is_recognised_from_its_id():
    assert config.sees_images("pixtral-12b-2409")
    assert config.sees_images("claude-sonnet-4-5")
    # Ids arrive spelled however a provider spells them, discovery included.
    assert config.sees_images("Pixtral-Large-Latest")


def test_a_model_that_cannot_see_is_never_guessed_at():
    """Conservative on purpose: an unlisted model gets the sentence, because the
    alternative is a 4xx on a question the user has already waited for."""
    assert not config.sees_images("mistral-small-latest")
    assert not config.sees_images("deepseek-v4-flash-free")
    assert not config.sees_images("")
    assert not config.sees_images(None)


def test_the_vision_list_is_a_deployment_setting(monkeypatch):
    """A free tier's lineup changes without notice, so learning that a model reads
    images must not need a code change."""
    monkeypatch.setattr(config, "VISION_MODELS", ("mimo",))
    assert config.sees_images("mimo-v2.5")
    assert not config.sees_images("pixtral-12b-2409")


def test_the_switch_is_what_decides_the_shape_of_the_turn():
    """The two halves wired together: what `sees_images` says about a model is what
    `build` does with the picture. Passing `vision=` by hand, as the tests above do,
    cannot catch the two disagreeing."""
    shot = Attachment(
        "pasted-image.png", "image", "", data=b"\x89PNG\r\n\x1a\nbody",
        mime="image/png",
    )
    for model, listed in (("pixtral-12b-2409", True), ("mistral-small-latest", False)):
        assert config.sees_images(model) is listed
        built = history.build(
            [user("what is this?", shot)], "S", vision=config.sees_images(model)
        )
        assert isinstance(built[-1]["content"], list) is listed, model


def test_a_screenshot_does_not_evict_the_conversation_from_the_budget():
    """Base64 image bytes are enormous. Counted against a character budget they
    would push every real turn out to make room for one screenshot."""
    huge = Attachment(
        "big.png", "image", "", data=b"\x89PNG\r\n\x1a\n" + b"x" * 200_000,
        mime="image/png",
    )
    messages = [user("first question"), assistant("first answer"),
                user("look at this", huge)]
    built = history.build(messages, "S", vision=True)
    joined = " ".join(
        part.get("text", "")
        for message in built
        for part in (message["content"] if isinstance(message["content"], list)
                     else [{"text": message["content"]}])
    )
    assert "first question" in joined, "one image evicted the whole conversation"


class TestTrimIsReported:
    """`build` used to return the message list alone, so the trim happened and the
    record of it was dropped on the next line — while the UI rendered every message.
    A long conversation showed twenty turns on screen with six sent upstream."""

    def test_a_short_conversation_reports_nothing_lost(self):
        built = history.build([user("hello"), assistant("hi")], "S")
        assert built.dropped == 0
        assert built.clipped == 0
        assert built.stubbed == ()
        assert built.dropped_upto == -1

    def test_dropped_turns_are_counted_and_located(self, monkeypatch):
        monkeypatch.setattr(config, "HISTORY_CHAR_BUDGET", 400)
        messages = []
        for index in range(12):
            messages.append(user(f"question {index} " + "x" * 120))
            messages.append(assistant(f"answer {index} " + "y" * 120))
        built = history.build(messages, "S")
        assert built.dropped > 0, "nothing was trimmed at a 400-char budget"
        # Points at a real position in the list the UI renders, so the fold marker
        # can be drawn where the loss actually happened.
        assert 0 <= built.dropped_upto < len(messages)
        # The newest turn always survives.
        assert "answer 11" in str(built.messages[-1]["content"])

    def test_a_clipped_final_turn_is_reported(self, monkeypatch):
        monkeypatch.setattr(config, "HISTORY_CHAR_BUDGET", 200)
        built = history.build([user("q " + "z" * 5000)], "S")
        assert built.clipped > 0, "an over-budget turn was silently truncated"

    def test_stubbed_attachments_are_reported(self, monkeypatch):
        """The most damaging trim in practice: MAX_FILE_TEXT_CHARS is 30k against a
        48k budget, so one attached .out plus a couple of turns evicts the file the
        user is asking about — and only the newest attachment turn ships full text."""
        monkeypatch.setattr(config, "ATTACHMENT_FULL_TEXT_TURNS", 1)
        first = Attachment(filename="run1.out", kind="text", text="early log")
        second = Attachment(filename="run2.out", kind="text", text="later log")
        messages = [
            user("look at this", first),
            assistant("ok"),
            user("and this", second),
        ]
        built = history.build(messages, "S")
        assert 0 in built.stubbed, "the earlier attachment turn was not flagged"
        assert 2 not in built.stubbed, "the newest attachment turn must ship in full"

    def test_the_payload_still_starts_with_the_system_prompt(self, monkeypatch):
        monkeypatch.setattr(config, "HISTORY_CHAR_BUDGET", 100)
        messages = [user("a" * 500), assistant("b" * 500), user("c" * 500)]
        built = history.build(messages, "SYSTEM")
        assert built.messages[0] == {"role": "system", "content": "SYSTEM"}
