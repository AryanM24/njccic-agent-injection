"""Extraction-stack and fixture-integrity checks.

These guard the two things every later measurement rests on: that the parsers
are the pinned ones, and that each attack/twin pair differs by the payload and
nothing else: the twin carries length-matched neutral text in the attack's
channel, so the pair differs in content, not in channel structure (A-11).
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from eduinject.config import assert_extraction_pinned
from eduinject.extraction import extract

TAG = re.compile(r"^\[(?:metadata|property|comment|alt-text)[^\]]*\]")
"""The channel-tag prefixes extraction puts on non-visible channels."""


def _pairs(root: Path, workflow: str) -> Iterator[tuple[dict[str, Any], str, str]]:
    manifest = root / "corpus" / f"manifest_{workflow}.jsonl"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        yield (
            row,
            extract(root / row["artifact_path"]),
            extract(root / row["twin_path"]),
        )


def _tags(text: str) -> set[str]:
    return {m.group(0) for line in text.splitlines() if (m := TAG.match(line))}


def test_stack_is_pinned() -> None:
    assert_extraction_pinned()


@pytest.mark.parametrize("workflow", ["w1", "w2", "w3"])
def test_twin_has_same_channel_lines(workflow: str, generated_corpus: Path) -> None:
    for row, attack, twin in _pairs(generated_corpus, workflow):
        marker = row["payload_marker"]
        assert marker in attack, row["artifact_id"]
        assert marker not in twin, row["artifact_id"]
        assert _tags(twin) == _tags(attack), row["artifact_id"]


@pytest.mark.parametrize("workflow", ["w1", "w2", "w3"])
def test_twin_differs_only_in_channel_line(
    workflow: str, generated_corpus: Path
) -> None:
    for row, attack, twin in _pairs(generated_corpus, workflow):
        a, t = attack.splitlines(), twin.splitlines()
        assert len(a) == len(t), row["artifact_id"]
        diff = [(x, y) for x, y in zip(a, t) if x != y]
        assert len(diff) == 1, row["artifact_id"]
        payload_line, neutral_line = diff[0]
        assert row["payload_marker"] in payload_line, row["artifact_id"]
        prefix = m.group(0) if (m := TAG.match(payload_line)) else ""
        assert neutral_line.startswith(prefix), row["artifact_id"]
        assert neutral_line[len(prefix) :].strip(), row["artifact_id"]
