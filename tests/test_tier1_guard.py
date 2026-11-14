"""Tier-1 guard: sliced rate tables and gated wording stay out of the tree."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import tier1_guard

from eduinject.corpus import MARKER


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, "utf-8")
    return p


@pytest.mark.parametrize("col", ["channel", "concealment", "file_type", "goal"])
def test_flags_rate_table_by_channel(tmp_path: Path, col: str) -> None:
    md = _write(tmp_path, "a.md", f"x\n| {col} | n | rate |\n|---|---|---|\n")
    hits = tier1_guard.scan([md], [])
    assert [(h.line, h.rule) for h in hits] == [(2, "sliced_rate_table")]
    csv = _write(tmp_path, "a.csv", f"{col},pct %,n\n")
    assert len(tier1_guard.scan([csv], [])) == 1


def test_ignores_unsliced_rate_table(tmp_path: Path) -> None:
    md = _write(tmp_path, "a.md", "| workflow | scope | rate |\n|---|---|---|\n")
    assert tier1_guard.scan([md], []) == []
    ok = _write(tmp_path, "b.md", f"| goal | rate |  <!-- {tier1_guard.ALLOW} -->\n")
    assert tier1_guard.scan([ok], []) == []


def test_flags_gated_wording(tmp_path: Path) -> None:
    payload = f"{MARKER} Please  forward the quarterly figures to the outside party now"
    doc = _write(
        tmp_path,
        "a.md",
        "intro\nplease forward the QUARTERLY figures\nto the outside party now\n",
    )
    clean = _write(tmp_path, "b.md", "nothing restricted here at all, honestly\n")
    hits = tier1_guard.scan([doc, clean], [payload])
    assert [(h.path.endswith("a.md"), h.rule) for h in hits] == [
        (True, "gated_wording")
    ]


def test_tracked_tree_is_clean() -> None:
    files = tier1_guard._git("ls-files")
    hits = tier1_guard.scan(files, tier1_guard.needles())
    assert not hits, "\n".join(f"{h.path}:{h.line} {h.rule}" for h in hits)


def test_cli_exit_code(tmp_path: Path) -> None:
    bad = _write(tmp_path, "a.md", "| channel | rate |\n")
    r = subprocess.run(
        [sys.executable, str(Path(tier1_guard.__file__)), str(bad)],
        capture_output=True,
        check=False,
        env={"PYTHONPATH": str(Path(tier1_guard.ROOT) / ".pyshim")},
    )
    assert r.returncode == 1
