"""Fixture-writer regressions.

The PDF writer once cut every line at 95 characters and never paginated, so PDF
fixtures silently lost content that docx/txt/md kept -- making file type, an
independent variable, change what the model saw.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _fixtures_common import write_pdf

from eduinject.extraction import extract


def test_pdf_wraps_long_lines_instead_of_truncating(tmp_path: Path) -> None:
    long_line = " ".join(f"word{i:03d}" for i in range(60))  # ~480 chars
    write_pdf(tmp_path / "a.pdf", None, None, ["Heading", long_line, "Last"])
    text = " ".join(extract(tmp_path / "a.pdf").split())
    assert long_line in text


def test_pdf_paginates_instead_of_running_off_the_page(tmp_path: Path) -> None:
    lines = [f"line number {i:03d}" for i in range(120)]  # > 44 lines per page
    write_pdf(tmp_path / "b.pdf", "visible", "ZZPAYLOADZZ", lines)
    text = extract(tmp_path / "b.pdf")
    assert "line number 000" in text and "line number 119" in text
    assert "ZZPAYLOADZZ" in text


def test_pdf_keeps_tokens_intact(tmp_path: Path) -> None:
    write_pdf(tmp_path / "c.pdf", None, None, ["x " * 40 + "j.alvarez@example-student.k12.nj.us"])
    assert "j.alvarez@example-student.k12.nj.us" in extract(tmp_path / "c.pdf")
