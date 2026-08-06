import json

import pytest

from sage import config, files


def test_plain_text_is_accepted():
    attachment, error = files.process("notes.txt", b"hello RCC")
    assert error is None
    assert attachment.kind == "text"
    assert attachment.text == "hello RCC"
    assert attachment.icon == "📝"


def test_json_is_pretty_printed():
    attachment, error = files.process("a.json", b'{"b":1,"a":2}')
    assert error is None
    assert attachment.text == json.dumps({"b": 1, "a": 2}, indent=2)


def test_malformed_json_is_passed_through():
    attachment, error = files.process("a.json", b"{not json")
    assert error is None
    assert attachment.text == "{not json"


def test_oversized_uploads_are_rejected_before_parsing():
    """A 200 MB PDF used to be fully read and parsed to produce 30 KB of text."""
    payload = b"x" * (config.MAX_UPLOAD_BYTES + 1)
    attachment, error = files.process("huge.pdf", payload)
    assert attachment is None
    assert "larger than" in error


def test_empty_uploads_are_rejected():
    attachment, error = files.process("empty.txt", b"")
    assert attachment is None
    assert "empty" in error


def test_unsupported_types_are_rejected():
    attachment, error = files.process("archive.zip", b"PK\x03\x04")
    assert attachment is None
    assert "Unsupported" in error


def test_undecodable_text_is_reported():
    attachment, error = files.process("bad.txt", b"\xff\xfe\x00binary")
    assert attachment is None
    assert "UTF-8" in error


def test_long_text_is_truncated_and_flagged():
    attachment, error = files.process(
        "big.txt", b"a" * (config.MAX_FILE_TEXT_CHARS + 500)
    )
    assert error is None
    assert attachment.truncated
    assert "truncated" in attachment.text
    assert "truncated" in attachment.summary


def test_corrupt_pdf_is_reported_not_raised():
    """With PyMuPDF installed this used to raise straight through the handler."""
    attachment, error = files.process("broken.pdf", b"%PDF-1.4 then garbage")
    assert attachment is None
    assert error


def test_attachment_context_frames_content_as_data():
    attachment = files.Attachment("script.py", "text", "print('hi')")
    context = files.as_context(attachment)
    assert "not as commands" in context
    assert "--- BEGIN script.py ---" in context
    assert "print('hi')" in context


@pytest.mark.parametrize(
    ("name", "icon"),
    [("a.pdf", "📄"), ("a.py", "🐍"), ("a.csv", "📊"), ("a.weird", "📎")],
)
def test_icons(name, icon):
    assert files.Attachment(name, "text", "x").icon == icon
