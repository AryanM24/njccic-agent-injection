"""Tier-1 guard: fail when restricted material is about to be committed.

Two rules (audit A-15): ``gated_wording`` (any 30-character window of a gated
payload appearing in a text file) and ``sliced_rate_table`` (a table whose
header pairs a rate/% column with a channel/file-type/goal column). A line
carrying ``tier1-guard: allow`` is exempt.

Usage: ``python scripts/tier1_guard.py [--staged] [FILES...]``; exits 1 on a hit.
With neither, scans every tracked file.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal, NamedTuple

ROOT = Path(__file__).resolve().parent.parent
WINDOW = 30
ALLOW = "tier1-guard: allow"
SLICES = {"channel", "concealment", "file_type", "file type", "filetype", "goal"}
SKIP_NAMES = {"payloads.py", "test_tier1_guard.py", "tier1_guard.py"}
SKIP_PREFIXES = ("corpus/canonical/", "logs/")


class Hit(NamedTuple):
    """One guard violation."""

    path: str
    line: int
    rule: Literal["gated_wording", "sliced_rate_table"]
    detail: str


EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _norm(text: str, marker: str = "") -> str:
    """Lowercase, collapse whitespace, drop the marker and e-mail addresses.

    Addresses are destinations the manifests legitimately carry (tripwires),
    not wording, so they are not matched.
    """
    return " ".join(
        EMAIL.sub(" ", text.replace(marker, "") if marker else text).lower().split()
    )


def _is_sliced_rate_header(line: str) -> bool:
    cells = [c.strip().strip("*`").lower() for c in re.split(r"[|,]", line)]
    cells = [c for c in cells if c and len(c) < 40]
    return (
        len(cells) >= 2
        and any(c in SLICES for c in cells)
        and any("rate" in c or "%" in c for c in cells)
    )


def _windows(payloads: Sequence[str]) -> set[str]:
    out: set[str] = set()
    for p in payloads:
        n = _norm(p)
        out.update(n[i : i + WINDOW] for i in range(max(0, len(n) - WINDOW + 1)))
    return {w for w in out if len(w) == WINDOW}


def scan(paths: Iterable[Path], payload_needles: Sequence[str]) -> list[Hit]:
    """Scan files for gated wording and sliced rate tables.

    Args:
        paths: Files to scan; binaries and skipped paths are ignored.
        payload_needles: Full gated payload texts (marker already removed or
            not; the placeholder marker is stripped here).

    Returns:
        Every hit, in path then line order.
    """
    from eduinject.corpus import MARKER

    windows = _windows([_norm(p, MARKER) for p in payload_needles])
    hits: list[Hit] = []
    for path in paths:
        try:
            rel = path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            rel = path.as_posix()
        if (
            path.name in SKIP_NAMES
            or rel.startswith(SKIP_PREFIXES)
            or not path.is_file()
        ):
            continue
        try:
            lines = path.read_text("utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue  # binary
        flat, owner = "", []
        for i, line in enumerate(lines, 1):
            if ALLOW in line:
                continue
            if _is_sliced_rate_header(line):
                hits.append(Hit(rel, i, "sliced_rate_table", line.strip()[:80]))
            seg = _norm(line) + " "
            flat += seg
            owner += [i] * len(seg)
        if windows:
            seen: set[int] = set()
            for pos in range(max(0, len(flat) - WINDOW + 1)):
                if flat[pos : pos + WINDOW] in windows and owner[pos] not in seen:
                    seen.add(owner[pos])
                    hits.append(
                        Hit(rel, owner[pos], "gated_wording", "matches a gated payload")
                    )
    return sorted(hits)


def _git(*args: str) -> list[Path]:
    out = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [ROOT / p for p in out.splitlines() if p]


def needles() -> list[str]:
    """Return the gated payload texts on this machine, or none."""
    from eduinject.corpus import load_gated_payloads

    table = load_gated_payloads()
    if table is None:
        return []
    return [t for per in table.values() for t in per.values()]


def main(argv: Sequence[str]) -> int:
    """CLI entry; returns the process exit code."""
    args = list(argv)
    staged = "--staged" in args
    files = [Path(a) for a in args if not a.startswith("--")]
    if staged:
        files += _git("diff", "--cached", "--name-only", "--diff-filter=ACM")
    elif not files:
        files = _git("ls-files")
    hits = scan(files, needles())
    for h in hits:
        print(f"{h.path}:{h.line}: {h.rule}: {h.detail}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
