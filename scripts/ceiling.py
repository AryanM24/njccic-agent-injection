#!/usr/bin/env python3
"""Structural ceiling (A9, doc 11 §3.9): the harm each arm permits, on the mock
model, at $0.

    ceiling.py [--workflows w1 w2 w3] [--adversary copy drop] [--per-base 1]
               [--arms ARM...] [--out logs/ceiling]

For each adversary × arm (`ceiling.ARMS`) × workflow, runs the task against
`ceiling.adversary` on the first `--per-base` artifacts of every base scenario
(manifest order), logging to OUT/<adversary>/<arm>/. Then it writes
OUT/ceiling.csv: one row per (adversary, arm, workflow) with the run count, the
unscored count and the mean of every score. The adversary reads only the
payload marker and the sample metadata, never the payload wording, so the
ceiling on the public corpus equals the ceiling on the canonical one. Rows are
per arm only, never per goal, channel or file type (doc 05). Nothing here
contacts a real model.
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from inspect_ai import eval
from inspect_ai.model import get_model

from eduinject.analysis import rows_from_log
from eduinject.ceiling import ADVERSARIES, ARMS, MOCK, TASKS, adversary, ceiling_rows
from eduinject.task import workflow


def sample_ids(manifest: Path, per_base: int) -> list[str]:
    """The first `per_base` artifact ids of each `base_id`, in manifest order."""
    taken: dict[str, int] = {}
    ids: list[str] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        base = str(entry.get("base_id", ""))
        if taken.get(base, 0) < per_base:
            taken[base] = taken.get(base, 0) + 1
            ids.append(entry["artifact_id"])
    return ids


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--workflows", nargs="+", default=list(TASKS), choices=list(TASKS)
    )
    parser.add_argument(
        "--adversary", nargs="+", default=list(ADVERSARIES), choices=list(ADVERSARIES)
    )
    parser.add_argument("--arms", nargs="+", default=list(ARMS), choices=list(ARMS))
    parser.add_argument("--per-base", type=int, default=1)
    parser.add_argument("--out", default="logs/ceiling")
    args = parser.parse_args(argv)
    if args.per_base < 1:
        parser.error("--per-base must be at least 1")
    out = Path(args.out)
    table: list[dict[str, Any]] = []
    for kind in args.adversary:
        for arm in args.arms:
            rows: list[dict[str, Any]] = []
            for code in args.workflows:
                ids = sample_ids(Path(workflow(code).manifest), args.per_base)
                (log,) = eval(
                    TASKS[code](**ARMS[arm]),
                    model=get_model(MOCK, custom_outputs=adversary(kind)),
                    log_dir=str(out / kind / arm),
                    sample_id=ids,
                    display="none",
                )
                if log.status != "success":
                    print(
                        f"{kind}/{arm}/{code}: {log.status} {log.error}",
                        file=sys.stderr,
                    )
                    return 1
                rows += rows_from_log(log)
            table += ceiling_rows(rows, kind, arm)
            print(f"{kind}/{arm}: {len(rows)} runs")
    write_csv(out / "ceiling.csv", table)
    print(f"-> {(out / 'ceiling.csv').resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
