"""Extraction-stack and fixture-integrity checks.

These guard the two things every later measurement rests on: that the parsers
are the pinned ones, and that each attack/twin pair differs by the payload and
nothing else.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from eduinject.config import assert_extraction_pinned
from eduinject.extraction import extract

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "corpus" / "manifest_w2.jsonl"


def _manifest_entries() -> list[dict[str, Any]]:
    lines = MANIFEST.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


MANIFEST_ENTRIES = _manifest_entries()


def test_stack_is_pinned() -> None:
    assert_extraction_pinned()


@pytest.mark.parametrize(
    "entry", MANIFEST_ENTRIES, ids=[e["artifact_id"] for e in MANIFEST_ENTRIES]
)
def test_attack_and_twin(entry: dict[str, Any]) -> None:
    marker = entry["payload_marker"]
    attack = extract(ROOT / entry["artifact_path"])
    twin = extract(ROOT / entry["twin_path"])

    assert marker in attack, "payload marker did not survive extraction"
    assert marker not in twin, "benign twin is contaminated with the marker"

    # A twin that drifted by more than the payload would silently corrupt every
    # difference-based outcome, so bound how far apart the pair may be.
    ratio = len(twin) / len(attack)
    assert 0.85 < ratio < 1.0, f"twin/attack length ratio {ratio:.4f} out of range"
