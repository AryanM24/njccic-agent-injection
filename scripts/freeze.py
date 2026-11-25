#!/usr/bin/env python3
"""Write and check the freeze (doc 14 §10). Contacts no model.

    freeze.py write --candidate ARM... --reference ARM... --note TEXT
                    [--date YYYY-MM-DD]
    freeze.py check

`write` appends an entry to `configs/freeze.json`: the digest of the frozen
tree, the commit, the arm names and the registry's held-out models. It refuses
(exit 2) while a frozen path has an uncommitted change, and never changes or
removes an entry. `check` exits 5 and prints why when the working tree is not
the last frozen one. Commit the file after writing it.
"""

import argparse
import json
import subprocess
import sys
from datetime import UTC, date, datetime

from eduinject.freeze import (
    FREEZE_FILE,
    FREEZE_PATHS,
    ROOT,
    VERSION,
    FreezeEntry,
    freeze_problems,
    load_freeze,
    tree_digest,
)
from eduinject.models import load_models


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    wr = sub.add_parser("write", help="append an entry for the current tree")
    wr.add_argument("--candidate", nargs="+", required=True, metavar="ARM")
    wr.add_argument("--reference", nargs="+", required=True, metavar="ARM")
    wr.add_argument("--note", required=True, help="why this tree is frozen")
    wr.add_argument("--date", type=date.fromisoformat, default=datetime.now(UTC).date())
    sub.add_parser("check", help="compare the tree to the last entry")
    return ap.parse_args(argv)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def cmd_write(args: argparse.Namespace) -> int:
    try:
        entries = load_freeze(FREEZE_FILE)
        dirty = _git(
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            *(f":(glob){p}" for p in FREEZE_PATHS),
            ":(exclude)configs/freeze.json",
        )
        commit = _git("rev-parse", "HEAD").strip()
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as e:
        print(f"refused: git failed: {e.stderr.strip()}", file=sys.stderr)
        return 2
    if dirty:
        print(f"refused: uncommitted frozen files:\n{dirty}", file=sys.stderr)
        return 2
    entry = FreezeEntry(
        digest=tree_digest(ROOT),
        commit=commit,
        date=args.date.isoformat(),
        candidates=tuple(args.candidate),
        references=tuple(args.reference),
        held_out=tuple(n for n, e in load_models().items() if e.held_out),
        note=args.note,
    )
    rows = [e._asdict() for e in (*entries, entry)]
    FREEZE_FILE.write_text(
        json.dumps({"version": VERSION, "entries": rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"entry {len(rows)}: {entry.digest} -> {FREEZE_FILE}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.cmd == "write":
        return cmd_write(args)
    problems = freeze_problems(ROOT, FREEZE_FILE)
    print("\n".join(problems) or "freeze: ok")
    return 5 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
