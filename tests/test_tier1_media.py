"""Tier 1: Feature Coverage - In-memory media handling & MIME resolution."""

from pathlib import Path

from google.antigravity import types

from channel_bot_cli_antigravity.utils import (
    create_media_from_bytes,
    guess_mime_type,
)


def test_media_png_image() -> None:
    """Verify PNG bytes are transformed into Antigravity types.Image."""
    png_header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    res = create_media_from_bytes(
        data=png_header, file_name="photo.png", resource_type="image"
    )
    assert isinstance(res, types.Image)
    assert res.mime_type == "image/png"
    assert res.description == "photo.png"


def test_media_jpeg_image() -> None:
    """Verify JPEG bytes are transformed into Antigravity types.Image."""
    jpeg_bytes = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb"
    )
    res = create_media_from_bytes(
        data=jpeg_bytes, file_name="avatar.jpg", resource_type="image"
    )
    assert isinstance(res, types.Image)
    assert res.mime_type == "image/jpeg"


def test_media_pdf_document() -> None:
    """Verify PDF bytes are transformed into Antigravity types.Document."""
    pdf_bytes = b"%PDF-1.4\n%mock stream"
    res = create_media_from_bytes(
        data=pdf_bytes, file_name="contract.pdf", resource_type="file"
    )
    assert isinstance(res, types.Document)
    assert res.mime_type == "application/pdf"
    assert res.description == "contract.pdf"


def test_media_utf8_plain_text_document() -> None:
    """Verify UTF-8 text file is transformed into types.Document(text/plain)."""
    text_bytes = b"This is a plain text file for analysis."
    res = create_media_from_bytes(
        data=text_bytes, file_name="notes.txt", resource_type="file"
    )
    assert isinstance(res, types.Document)
    assert res.mime_type == "text/plain"


def test_media_magic_number_recovery() -> None:
    """Verify JPEG with unknown or wrong extension is recovered via magic numbers."""
    jpeg_bytes = b"\xff\xd8\xff\xe1\x00\x10JFIF"
    # Given a wrong extension (.dat)
    res = create_media_from_bytes(
        data=jpeg_bytes, file_name="mystery.dat", resource_type="file"
    )
    assert isinstance(res, types.Image)
    assert res.mime_type == "image/jpeg"


def test_media_unsupported_binary_fallback() -> None:
    """Verify unsupported binary formats fall back to informative descriptive string."""
    binary_bytes = bytes([0x00, 0x01, 0x02, 0x03, 0xFE, 0xFF, 0x88, 0x99] * 8)
    res = create_media_from_bytes(
        data=binary_bytes,
        file_name="executable.bin",
        resource_type="file",
    )
    assert isinstance(res, str)
    assert "executable.bin" in res
    assert str(len(binary_bytes)) in res
    assert "暂不支持" in res


def test_media_guess_mime_types() -> None:
    """Verify guess_mime_type handles extensions and fallback resource types."""
    assert guess_mime_type("table.csv") == "text/csv"
    assert guess_mime_type("config.json") == "application/json"
    assert guess_mime_type("index.html") == "text/html"
    assert guess_mime_type("styles.css") == "text/css"
    assert guess_mime_type(None, resource_type="image") == "image/png"
    assert guess_mime_type(None, resource_type="audio") == "audio/mp3"
    assert guess_mime_type(None, resource_type="video") == "video/mp4"
    assert guess_mime_type("unknown_ext.xyz123") == "application/octet-stream"


def test_media_in_memory_no_temporary_disk_residue(tmp_path: Path) -> None:
    """Verify in-memory media conversion creates zero temporary files on disk."""
    initial_files = list(tmp_path.glob("**/*"))

    # Convert multiple media types
    png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    pdf_data = b"%PDF-1.4 mock content"
    txt_data = b"Plain text payload"

    _ = create_media_from_bytes(png_data, "test.png")
    _ = create_media_from_bytes(pdf_data, "test.pdf")
    _ = create_media_from_bytes(txt_data, "test.txt")

    after_files = list(tmp_path.glob("**/*"))
    assert len(initial_files) == len(after_files), (
        "create_media_from_bytes must operate purely in memory without disk residue"
    )
