"""Fixture generators: real CLIs, nothing written on --help or --dry-run, byte-deterministic."""

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
GENERATORS = [
    "make_fixtures_v2.py",
    "make_fixtures_w1.py",
    "make_fixtures_w3.py",
    "make_fixtures_controls.py",
]


def _run(script: str, *args: str, tz: str = "UTC") -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TZ": tz, "PYTHONPATH": str(ROOT / "src")}
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.mark.parametrize("script", GENERATORS)
def test_help_writes_nothing(script: str, tmp_path: Path) -> None:
    corpus_mtime = (ROOT / "corpus").stat().st_mtime_ns
    result = _run(script, "--help", "--out-root", str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert "--out-root" in result.stdout and "--dry-run" in result.stdout
    assert list(tmp_path.iterdir()) == []
    assert (ROOT / "corpus").stat().st_mtime_ns == corpus_mtime


@pytest.mark.parametrize("script", GENERATORS)
def test_dry_run_writes_nothing(script: str, tmp_path: Path) -> None:
    result = _run(script, "--dry-run", "--out-root", str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
    assert list(tmp_path.iterdir()) == []


def test_generation_is_byte_identical(tmp_path: Path) -> None:
    roots = {"UTC": tmp_path / "a", "Asia/Kolkata": tmp_path / "b"}
    for tz, root in roots.items():
        root.mkdir()
        for script in GENERATORS:
            result = _run(script, "--out-root", str(root), tz=tz)
            assert result.returncode == 0, result.stderr
    first, second = (_files(r) for r in roots.values())
    assert first.keys() == second.keys()
    assert any(k.endswith(".docx") for k in first)
    assert any(k.endswith(".pdf") for k in first)
    assert [k for k in first if first[k] != second[k]] == []
    assert not any(b"\r\n" in v for k, v in first.items() if k.endswith(".jsonl"))


def test_docx_dates_are_fixed(tmp_path: Path) -> None:
    result = _run("make_fixtures_v2.py", "--out-root", str(tmp_path))
    assert result.returncode == 0, result.stderr
    found = {"core": False, "comment": False}
    for p in sorted(tmp_path.rglob("*.docx")):
        with zipfile.ZipFile(p) as z:
            assert "2026-01-01" in z.read("docProps/core.xml").decode()
            found["core"] = True
            if "word/comments.xml" in z.namelist():
                comments = z.read("word/comments.xml").decode()
                assert 'w:date="2026-01-01T00:00:00Z"' in comments
                found["comment"] = True
    assert all(found.values())
