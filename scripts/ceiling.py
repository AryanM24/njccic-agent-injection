#!/usr/bin/env python3
"""Structural ceiling (A9, doc 11 §3.9; doc 14 §6): the harm each arm permits,
on the mock model, at $0.

    ceiling.py [--workflows w1 w2 w3] [--adversary copy drop] [--arms ARM...]
               [--arm-json NAME='{"gate": true}' ...] [--split {dev,confirm,all}]
               [--per-base N] [--search] [--out logs/ceiling]

For each adversary × arm (`ceiling.ARMS`) × workflow, runs the task against
`ceiling.adversary` on every artifact of the split (default dev), logging to
OUT/<adversary>/<arm>/. Then it writes OUT/ceiling.csv: one row per (adversary,
arm, workflow, split) with the run count, the unscored count, the arm's task
arguments and the mean of every score. The adversary reads only the payload
marker and the sample metadata, never the payload wording, so the ceiling on the
public corpus equals the ceiling on the canonical one. Rows are per arm only,
never per goal, channel or file type (doc 05). Nothing here contacts a real
model.

`--per-base N` keeps the first N artifacts of every base scenario in manifest
order (0: every artifact). `--arm-json` runs an arm that is not registered:
NAME's JSON overrides the baseline's task arguments; given without `--arms`, only
the JSON arms run.

`--search` also runs every strategy of `ceiling_search.strategies` per arm, on
the first artifact of each base unless `--per-base` says otherwise (one epoch per
strategy, logged to OUT/search/<arm>/<workflow>/). It appends one `search` row
per (arm, workflow, split) to ceiling.csv and writes OUT/search_strategies.csv,
one row per strategy code: never commit it, so OUT must then be under the
repository's `logs/`.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

from inspect_ai import eval
from inspect_ai.model import get_model

from eduinject.analysis import rows_from_log
from eduinject.ceiling import (
    ADVERSARIES,
    ARMS,
    BASELINE,
    MOCK,
    TASKS,
    adversary,
    ceiling_rows,
)
from eduinject.ceiling_search import (
    search_policy,
    search_summary,
    strategies,
    strategy_rows,
)
from eduinject.task import workflow

LOGS = Path(__file__).resolve().parents[1] / "logs"


def sample_ids(manifest: Path, per_base: int | None, split: str = "all") -> list[str]:
    """The first `per_base` artifact ids of each `base_id` of the split, in
    manifest order; every id when `per_base` is None or 0."""
    taken: dict[str, int] = {}
    ids: list[str] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if split != "all" and entry["split"] != split:
            continue
        base = str(entry.get("base_id", ""))
        if not per_base or taken.get(base, 0) < per_base:
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


def arm_json(text: str) -> tuple[str, dict[str, Any]]:
    """`NAME={...}` as (NAME, the baseline's task arguments with it applied)."""
    name, _, body = text.partition("=")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or name in ARMS:
        raise argparse.ArgumentTypeError(f"{name!r} is not a new arm name")
    try:
        given = json.loads(body)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(f"{name}: not JSON ({ex})") from ex
    if not isinstance(given, dict):
        raise argparse.ArgumentTypeError(f"{name}: not a JSON object")
    return name, {**BASELINE, **given}


def run(
    code: str, arm: dict[str, Any], policy: Any, ids: list[str], log_dir: Path
) -> list[dict[str, Any]]:
    """The rows of one arm of one workflow on the mock model.

    Raises:
        SystemExit: If the eval did not finish.
    """
    (log,) = eval(
        TASKS[code](**arm),
        # Memoization keys on the policy's repr, which a freed policy can share.
        model=get_model(MOCK, custom_outputs=policy, memoize=False),
        log_dir=str(log_dir),
        log_realtime=False,
        sample_id=ids,
        display="none",
    )
    if log.status != "success":
        raise SystemExit(f"{log_dir}/{code}: {log.status} {log.error}")
    return rows_from_log(log)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--workflows", nargs="+", default=list(TASKS), choices=list(TASKS)
    )
    parser.add_argument(
        "--adversary", nargs="+", default=list(ADVERSARIES), choices=list(ADVERSARIES)
    )
    parser.add_argument("--arms", nargs="+", choices=list(ARMS))
    parser.add_argument(
        "--arm-json", action="append", type=arm_json, default=[], metavar="NAME=JSON"
    )
    parser.add_argument("--split", choices=["dev", "confirm", "all"], default="dev")
    parser.add_argument("--per-base", type=int, default=None)
    parser.add_argument("--search", action="store_true")
    parser.add_argument("--out", default="logs/ceiling")
    args = parser.parse_args(argv)
    if args.per_base is not None and args.per_base < 0:
        parser.error("--per-base must be at least 1, or 0 for every artifact")
    out = Path(args.out)
    if args.search and not out.resolve().is_relative_to(LOGS.resolve()):
        parser.error(f"--search writes strategy codes: --out must be under {LOGS}")
    names = args.arms or ([] if args.arm_json else list(ARMS))
    arms = {**{n: ARMS[n] for n in names}, **dict(args.arm_json)}

    def ids(code: str, per_base: int | None) -> list[str]:
        return sample_ids(Path(workflow(code).manifest), per_base, args.split)

    # An empty id list would select no sample: no row, not every sample.
    codes = [c for c in args.workflows if ids(c, 1)]
    table: list[dict[str, Any]] = []
    for kind in args.adversary:
        for name, arm in arms.items():
            rows: list[dict[str, Any]] = []
            for code in codes:
                rows += run(
                    code,
                    arm,
                    adversary(kind),
                    ids(code, args.per_base),
                    out / kind / name,
                )
            table += ceiling_rows(rows, kind, name)
            print(f"{kind}/{name}: {len(rows)} runs")
    if args.search:
        per_base = 1 if args.per_base is None else args.per_base
        found: list[dict[str, Any]] = []
        for name, arm in arms.items():
            rows = []
            for code in codes:
                space = strategies(code)
                rows += [
                    {**r, "strategy": space[r["epoch"] - 1].code()}
                    for r in run(
                        code,
                        {**arm, "epochs": len(space)},
                        search_policy(space),
                        ids(code, per_base),
                        out / "search" / name / code,
                    )
                ]
            table += search_summary(rows, name)
            found += strategy_rows(rows, name)
            print(f"search/{name}: {len(rows)} runs")
        write_csv(out / "search_strategies.csv", found)
    write_csv(out / "ceiling.csv", table)
    print(f"-> {(out / 'ceiling.csv').resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
