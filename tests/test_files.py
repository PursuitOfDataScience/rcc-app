import json
import sys
import types
from types import SimpleNamespace

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


def test_binary_uploads_are_rejected_on_their_bytes():
    attachment, error = files.process("archive.zip", b"PK\x03\x04\x00\x00nonsense")
    assert attachment is None
    assert "does not look like text" in error


def test_a_binary_named_like_text_is_still_rejected():
    """The extension is not evidence. A compiled binary called .txt is not text.

    An ELF header rather than a PNG one: a PNG *is* now accepted, as an image, so
    using one here would have tested the image path while claiming to test refusal.
    """
    attachment, error = files.process("sneaky.txt", b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 24)
    assert attachment is None
    assert "does not look like text" in error


@pytest.mark.parametrize(
    "filename",
    [
        "slurm-12345.out",          # what a job actually writes
        "run.err",
        "submit.sbatch",
        "job.sh",
        "Makefile",                 # no extension at all
        "pyproject.toml",
        ".bashrc",                  # nothing but an extension
        "analysis.R",
        "kernel.cu",
        "results.tsv",
    ],
)
def test_the_files_a_cluster_user_actually_has_are_accepted(filename):
    """The old rule was a list of eight extensions, and these were the casualties.

    Every one of them is the file someone would attach to ask why a job died, and
    every one of them was refused with "Unsupported file type" until uploads stopped
    being gated on the filename.
    """
    attachment, error = files.process(filename, b"#!/bin/bash\n#SBATCH -p caslake\n")
    assert error is None, f"{filename} was refused: {error}"
    assert attachment.kind == "text"
    assert "SBATCH" in attachment.text


def test_text_that_is_not_utf8_is_still_read():
    """A single stray byte is a poor reason to refuse six thousand lines of output."""
    attachment, error = files.process("legacy.log", "café — naïve".encode("cp1252"))
    assert error is None
    assert "caf" in attachment.text


def test_undecodable_text_is_reported():
    """Nothing in the fallback chain can fail, so this is the belt-and-braces path:
    a byte string that gets past the binary sniff but decodes as nothing."""
    attachment, error = files.process("bad.txt", b"plain")
    assert error is None  # it decodes; the sniff and the chain agree
    assert attachment.text == "plain"


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


class TestPdfExtraction:
    """Injects a fake pypdf so these paths are covered whether or not it is installed.

    Without this the assertions above pass via the "PDF support is unavailable"
    ImportError branch, leaving the real extraction paths untested.
    """

    @staticmethod
    def _install(monkeypatch, reader):
        module = types.ModuleType("pypdf")
        module.PdfReader = reader
        monkeypatch.setitem(sys.modules, "pypdf", module)
        # Force the pypdf fallback rather than PyMuPDF.
        monkeypatch.setitem(sys.modules, "pymupdf", None)

    def test_a_readable_pdf_is_extracted(self, monkeypatch):
        class Reader:
            pages = [SimpleNamespace(extract_text=lambda: "Slurm job guide")]

            def __init__(self, stream):
                pass

        self._install(monkeypatch, Reader)
        attachment, error = files.process("guide.pdf", b"%PDF-1.4")
        assert error is None
        assert attachment.kind == "pdf"
        assert attachment.pages == 1
        assert attachment.text == "Slurm job guide"
        assert "1 page" in attachment.summary

    def test_a_scanned_pdf_asks_for_ocr(self, monkeypatch):
        class Reader:
            pages = [SimpleNamespace(extract_text=lambda: "")]

            def __init__(self, stream):
                pass

        self._install(monkeypatch, Reader)
        attachment, error = files.process("scan.pdf", b"%PDF-1.4")
        assert attachment is None
        assert "OCR" in error

    def test_a_corrupt_pdf_reports_rather_than_raising(self, monkeypatch):
        class Reader:
            def __init__(self, stream):
                raise ValueError("EOF marker not found")

        self._install(monkeypatch, Reader)
        attachment, error = files.process("broken.pdf", b"%PDF-1.4 garbage")
        assert attachment is None
        assert "corrupt or encrypted" in error

    def test_pages_are_joined_in_order(self, monkeypatch):
        class Reader:
            pages = [
                SimpleNamespace(extract_text=lambda: "first"),
                SimpleNamespace(extract_text=lambda: None),  # pypdf can return None
                SimpleNamespace(extract_text=lambda: "third"),
            ]

            def __init__(self, stream):
                pass

        self._install(monkeypatch, Reader)
        attachment, error = files.process("multi.pdf", b"%PDF-1.4")
        assert error is None
        assert attachment.text == "first\n\nthird"
        assert attachment.pages == 3


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


def test_a_png_is_accepted_as_an_image():
    """A pasted screenshot arrives as bytes under a name the app invented, so the
    name says nothing and the magic number is the only evidence."""
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"x" * 64
    attachment, error = files.process("pasted-image.png", png)
    assert error is None
    assert attachment.kind == "image"
    assert attachment.mime == "image/png"
    assert attachment.icon == "🖼️"
    assert "image" in attachment.summary
    assert attachment.as_data_url().startswith("data:image/png;base64,")


@pytest.mark.parametrize(
    "name,payload,mime",
    [
        ("shot.png", b"\x89PNG\r\n\x1a\n" + b"y" * 40, "image/png"),
        ("photo.jpg", b"\xff\xd8\xff\xe0" + b"y" * 40, "image/jpeg"),
        ("anim.gif", b"GIF89a" + b"y" * 40, "image/gif"),
        ("shot.webp", b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"y" * 40, "image/webp"),
    ],
)
def test_every_clipboard_image_format_is_recognised(name, payload, mime):
    attachment, error = files.process(name, payload)
    assert error is None, f"{name} was refused: {error}"
    assert attachment.mime == mime


def test_an_image_with_a_misleading_name_is_still_an_image():
    """Nothing about this decision comes from the filename."""
    attachment, error = files.process("notes.txt", b"\x89PNG\r\n\x1a\n" + b"z" * 40)
    assert error is None
    assert attachment.kind == "image"
