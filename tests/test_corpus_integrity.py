"""Corpus-level guards: shape, marker-only policy, controls, and the gated file.

These run the same validator the maintainers run by hand, so a corpus that
passes here is one `scripts/validate_manifest.py` accepts.
"""

import collections
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from eduinject.corpus import GOALS, MARKER
from eduinject.extraction import extract

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_manifest import marker_only_violations, validate_manifest

PUBLIC = {w: ROOT / "corpus" / f"manifest_{w}.jsonl" for w in ("w1", "w2", "w3")}
CONTROLS = {
    w: ROOT / "corpus" / f"manifest_{w}_controls.jsonl" for w in ("w1", "w2", "w3")
}
EXPECTED_PAIRS = {
    "w1": 48,
    "w2": 48,
    "w3": 48,
}  # 32 + 8 + 8 (W2 also has the pilot pair)


def _rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text("utf-8").splitlines()
        if line.strip()
    ]


@pytest.mark.parametrize("workflow", sorted(PUBLIC))
def test_public_manifest_validates_clean(workflow: str) -> None:
    count, errors = validate_manifest(PUBLIC[workflow])
    assert count == EXPECTED_PAIRS[workflow]
    assert not errors, "\n".join(errors[:10])


@pytest.mark.parametrize("workflow", sorted(CONTROLS))
def test_controls_manifest_validates_clean(workflow: str) -> None:
    count, errors = validate_manifest(CONTROLS[workflow])
    assert count == 4
    assert not errors, "\n".join(errors[:10])


@pytest.mark.parametrize("workflow", sorted(PUBLIC))
def test_each_workflow_has_three_bases_with_the_intended_matrix(workflow: str) -> None:
    rows = _rows(PUBLIC[workflow])
    by_base = collections.Counter(r["base_id"] for r in rows)
    assert by_base["b1"] == 32 and len(rows) == 48
    assert by_base["b2"] == 8 and by_base["b3"] == 8
    for base in ("b2", "b3"):
        cells = {
            (r["goal"], r["file_type"], r["concealment"])
            for r in rows
            if r["base_id"] == base
        }
        assert cells == {(g, "docx", c) for g in GOALS for c in ("visible", "comment")}


def test_primary_base_covers_every_file_type_goal_and_channel() -> None:
    from eduinject.extraction import (
        extract as _,  # noqa: F401  (imports the pinned stack)
    )

    channels = {"docx": 4, "pdf": 2, "txt": 1, "md": 1}
    rows = [r for r in _rows(PUBLIC["w1"]) if r["base_id"] == "b1"]
    cells = collections.Counter((r["file_type"], r["concealment"]) for r in rows)
    assert sum(cells.values()) == 32
    assert {ft: len({c for f, c in cells if f == ft}) for ft in channels} == channels


@pytest.mark.parametrize("workflow", sorted(PUBLIC))
def test_public_corpus_is_marker_only(workflow: str) -> None:
    """The release policy: public attack files differ from their twins by the
    marker and nothing else (README C3)."""
    for row in _rows(PUBLIC[workflow]):
        attack = extract(ROOT / row["artifact_path"])
        twin = extract(ROOT / row["twin_path"])
        assert marker_only_violations(attack, twin, MARKER) == [], row["artifact_id"]
        if "payload_class" in row:
            assert row["payload_class"] == "placeholder"


def test_marker_only_check_catches_instruction_wording() -> None:
    twin = "Heading\nBody line"
    assert marker_only_violations(f"Heading\nBody line\n{MARKER}", twin, MARKER) == []
    # Wording beside the marker is wording (audit #3); this used to pass.
    assert marker_only_violations(
        f"Heading\nBody line\n{MARKER} do something", twin, MARKER
    ) == [f"{MARKER} do something"]
    assert marker_only_violations(
        f"Heading\nBody line\n{MARKER}\nDo something else", twin, MARKER
    ) == ["Do something else"]


def test_generators_do_not_embed_payload_tables() -> None:
    for script in (ROOT / "scripts").glob("make_fixtures*.py"):
        assert "PAYLOADS = {" not in script.read_text("utf-8"), script.name
    assert "PAYLOADS" not in (ROOT / "scripts" / "_corpus_bases.py").read_text("utf-8")
