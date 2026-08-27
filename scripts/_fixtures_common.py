"""Shared .docx/.pdf/.txt/.md fixture-writer helpers for the corpus generators.

The channel set here is a property of extraction.py (which channels the
pinned parser stack actually exposes), not of any one workflow's content, so
make_fixtures_v2.py (W2), make_fixtures_w1.py, and make_fixtures_w3.py all
build on these instead of each re-implementing channel writing.
"""

import io
import json
import struct
import zlib
from collections.abc import Callable
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType
from docx.shared import Inches
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

CHANNELS: dict[str, list[str]] = {
    "docx": ["visible", "core_property", "comment", "alt_text"],
    "pdf": ["visible", "pdf_metadata"],
    "txt": ["visible"],
    "md": ["visible"],
}
"""File type -> concealment channels extraction.py can expose for that type."""


def small_png() -> io.BytesIO:
    """Build a minimal valid 4x4 white PNG, in-memory.

    Returns:
        A PNG file's bytes, for use as an embedded image's picture data.
    """

    def chunk(ctype: bytes, data: bytes) -> bytes:
        c = ctype + data
        return (
            struct.pack(">I", len(data))
            + c
            + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        )

    w = h = 4
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * w for _ in range(h))
    idat = zlib.compress(raw)
    return io.BytesIO(
        sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    )


def write_docx(
    path: Path,
    channel: str | None,
    payload: str | None,
    build_body: Callable[[DocumentType], None],
) -> None:
    """Write a .docx fixture, optionally carrying a payload in one channel.

    Args:
        path: Output file path.
        channel: One of CHANNELS["docx"], or None for a clean twin.
        payload: Text to place in the channel. Ignored if channel is None.
        build_body: Fills in the document's visible body content (the part
            shared by the attack file and its twin).
    """
    document = Document()
    build_body(document)
    if channel == "visible":
        document.add_paragraph(payload)
    elif channel == "core_property":
        document.core_properties.comments = payload
    elif channel == "comment":
        anchor = document.paragraphs[1]
        document.add_comment(
            runs=anchor.runs, text=payload, author="A. Reviewer", initials="AR"
        )
    elif channel == "alt_text":
        shape = document.add_picture(small_png(), width=Inches(1))
        docPr = shape._inline.find(
            "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr"
        )
        if docPr is not None:
            docPr.set("descr", payload)
    document.save(str(path))


def write_pdf(
    path: Path, channel: str | None, payload: str | None, text_lines: list[str]
) -> None:
    """Write a .pdf fixture, optionally carrying a payload in one channel.

    Args:
        path: Output file path.
        channel: One of CHANNELS["pdf"], or None for a clean twin.
        payload: Text to place in the channel. Ignored if channel is None.
        text_lines: Visible body lines, one per line of the rendered page.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 720
    for line in text_lines:
        c.drawString(72, y, line[:95])
        y -= 15
    if channel == "visible":
        c.drawString(72, y - 15, payload)
    c.save()
    buf.seek(0)
    reader = PdfReader(buf)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    if channel == "pdf_metadata":
        writer.add_metadata({"/Subject": payload})
    with open(path, "wb") as f:
        writer.write(f)


def write_text(path: Path, channel: str | None, payload: str | None, text: str) -> None:
    """Write a .txt or .md fixture, optionally appending a visible payload.

    Args:
        path: Output file path.
        channel: "visible" or None for a clean twin.
        payload: Text to append. Ignored if channel is None.
        text: The clean body text.
    """
    content = text
    if channel == "visible":
        content = content + "\n" + payload
    path.write_text(content, encoding="utf-8")


def upsert_manifest_line(manifest: Path, entry: dict) -> str:
    """Insert or update one manifest line, keyed by artifact_id.

    Args:
        manifest: Path to the manifest .jsonl file.
        entry: The manifest entry to write.

    Returns:
        "unchanged" if an identical line already existed, "updated" if a line
        with this artifact_id existed but differed, "appended" if it's new.
    """
    lines: list[str] = []
    if manifest.exists():
        lines = [
            ln for ln in manifest.read_text(encoding="utf-8").splitlines() if ln.strip()
        ]
    serialized = json.dumps(entry)
    for index, line in enumerate(lines):
        if json.loads(line)["artifact_id"] == entry["artifact_id"]:
            if line == serialized:
                return "unchanged"
            lines[index] = serialized
            manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return "updated"
    lines.append(serialized)
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "appended"
