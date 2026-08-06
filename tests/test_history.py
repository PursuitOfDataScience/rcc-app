from sage import config, history
from sage.files import Attachment


def user(text, attachment=None):
    return {"role": "user", "text": text, "attachment": attachment}


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
    messages.append(user("what about the method?", None))
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
