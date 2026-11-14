#!/usr/bin/env python3
"""A dated record of what changed and what ran, for the ISEF data book.

    python scripts/data_book.py [--logs logs] [--since 2026-08-01] [--out FILE]

Merges two sources into one chronological Markdown log, grouped by day:

- every commit (date, short hash, subject) from `git log`;
- every eduinject eval log under `--logs`: when it ran, the workflow and cell
  (scope, isolation, identity mode, defense, baseline or attack), the model,
  its config hash, and how many samples finished.

It reads log *headers* only, so it never opens a trace, and prints no document
or payload text: dates, hashes, conditions and counts. The output is safe for
the data book; the logs themselves stay Tier 1.
"""

import argparse
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def commits(since: str | None) -> list[tuple[str, str]]:
    """(ISO date, line) for each commit, oldest first."""
    cmd = ["git", "log", "--reverse", "--date=short", "--pretty=%ad%x09%h %s"]
    if since:
        cmd.append(f"--since={since}")
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True)
    entries = []
    for line in out.stdout.splitlines():
        date, _, rest = line.partition("\t")
        entries.append((date, f"commit {rest}"))
    return entries


def runs(log_dir: str, since: str | None) -> list[tuple[str, str]]:
    """(ISO date, line) for each eduinject eval log, from its header."""
    from inspect_ai.log import list_eval_logs, read_eval_log

    from eduinject.analysis import cell_from_log, cell_kind

    entries: list[tuple[str, str]] = []
    if not Path(log_dir).exists():
        return entries
    for info in list_eval_logs(log_dir, recursive=True):
        if not info.task.split("/")[-1].startswith("eduinject"):
            continue
        header = read_eval_log(info, header_only=True)
        date = str(header.eval.created)[:10]
        if since and date < since:
            continue
        cell = cell_from_log(header)
        done = header.results.completed_samples if header.results else 0
        line = (
            f"run {cell['workflow']} {cell_kind(cell)} scope={cell['scope']} "
            f"iso={'on' if cell['isolated'] else 'off'} "
            f"identity={cell['identity_mode']} "
            f"defense={cell['defense']} "
            f"model={cell['model']} "
            f"hash={(header.eval.metadata or {}).get('config_hash')} samples={done} "
            f"status={header.status}"
        )
        entries.append((date, line))
    return entries


def render(entries: list[tuple[str, str]]) -> str:
    by_day: dict[str, list[str]] = defaultdict(list)
    for date, line in entries:
        by_day[date].append(line)
    lines = ["# EduInject data book: changes and runs by date", ""]
    for day in sorted(by_day):
        lines += [f"## {day}", ""]
        lines += [f"- {line}" for line in by_day[day]]
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--logs", default=str(ROOT / "logs"))
    ap.add_argument("--since", default=None, help="ISO date, e.g. 2026-08-01")
    ap.add_argument("--out", default=None, help="write here instead of stdout")
    args = ap.parse_args(argv)
    text = render(commits(args.since) + runs(args.logs, args.since))
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"-> {Path(args.out).resolve()}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
