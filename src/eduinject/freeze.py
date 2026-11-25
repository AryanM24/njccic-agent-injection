"""The freeze (doc 14 §10): a digest of the frozen tree and the entries it must match.

Confirm scenarios and the held-out model may run only while the working tree
hashes to the last entry of `configs/freeze.json`. Every doubt is a problem: a
missing, empty or malformed file counts as no freeze. Stdlib only.
"""

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[2]
FREEZE_FILE = ROOT / "configs" / "freeze.json"
FREEZE_PATHS: tuple[str, ...] = (
    "src/eduinject/**/*.py",
    "configs/**/*.json",
    "scripts/run_sweep.py",
    "scripts/ceiling.py",
    "scripts/analyze.py",
    "scripts/build_features.py",
    "scripts/behavior_models.py",
    "scripts/_corpus_bases*.py",
    "scripts/_fixtures_common.py",
    "scripts/make_fixtures_*.py",
    "corpus/manifest_w*.jsonl",
    "corpus/benign/**/*",
    "corpus/controls/**/*",
    "corpus/canonical/**/*",
)
"""Glob patterns, relative to the repository root, of everything a confirm
result depends on. The gated payload module and the canonical corpus are
included where present, so an entry is tied to the machine that holds them."""

VERSION = "1"


class FreezeEntry(NamedTuple):
    """One freeze: what was frozen, when, and what it will be used to test."""

    digest: str
    commit: str
    date: str
    candidates: tuple[str, ...]
    references: tuple[str, ...]
    held_out: tuple[str, ...]
    note: str


LISTS = ("candidates", "references", "held_out")


def tree_digest(root: Path = ROOT, patterns: Sequence[str] = FREEZE_PATHS) -> str:
    """Hex sha256 over the path and bytes of every file matching `patterns`.

    `configs/freeze.json`, `__pycache__` and hidden files (macOS metadata) are
    left out.
    """
    files: dict[str, Path] = {}
    for pattern in patterns:
        for path in root.glob(pattern):
            rel = path.relative_to(root)
            skip = any(p == "__pycache__" or p.startswith(".") for p in rel.parts)
            if path.is_file() and not skip:
                files[rel.as_posix()] = path
    files.pop("configs/freeze.json", None)
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode() + b"\0" + files[name].read_bytes() + b"\0")
    return digest.hexdigest()


def _entry(row: Any) -> FreezeEntry:
    if not isinstance(row, dict) or set(row) != set(FreezeEntry._fields):
        raise ValueError(f"a freeze entry needs exactly {FreezeEntry._fields}")
    for field, value in row.items():
        items = value if field in LISTS and isinstance(value, list) else [value]
        if (field in LISTS) != isinstance(value, list) or not all(
            isinstance(i, str) for i in items
        ):
            raise ValueError(f"freeze entry field {field!r} has the wrong type")
    if not re.fullmatch(r"[0-9a-f]{64}", row["digest"]):
        raise ValueError("freeze entry digest is not a sha256")
    return FreezeEntry(**{**row, **{f: tuple(row[f]) for f in LISTS}})


def load_freeze(path: Path = FREEZE_FILE) -> list[FreezeEntry]:
    """The freeze entries, oldest first.

    Raises:
        ValueError: If the file is missing or malformed.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ValueError(f"{path} is missing") from e
    if (
        not isinstance(data, dict)
        or data.get("version") != VERSION
        or not isinstance(data.get("entries"), list)
    ):
        raise ValueError(f"{path} is not a version {VERSION} freeze file")
    return [_entry(row) for row in data["entries"]]


def freeze_problems(root: Path = ROOT, path: Path = FREEZE_FILE) -> list[str]:
    """Why the working tree is not the last frozen one; [] only when it is."""
    try:
        entries = load_freeze(path)
    except (ValueError, OSError) as e:
        return [f"no usable freeze file: {e}"]
    if not entries:
        return ["no freeze entry"]
    last, now = entries[-1], tree_digest(root)
    if now == last.digest:
        return []
    return [
        (
            f"tree digest {now} differs from the frozen {last.digest} "
            f"(entry of {last.date})"
        )
    ]
