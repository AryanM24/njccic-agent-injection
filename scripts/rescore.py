#!/usr/bin/env python3
"""Write copies of eval logs with every score recomputed by the current scorers.

    rescore.py --log-dir IN --out-dir OUT [--allow-overwrite]

Each winning finished sample (the newest log per sample, as in analysis) gets
the scores `analysis.rescore_sample` computes, replacing its logged ones, and
each log holding such a sample is written under OUT at the same relative path
with its aggregate metrics recomputed. IN is never modified; OUT may not be or
contain IN. Afterwards `verify_scores.py OUT` reports nothing stale (A-09).
Contacts no model.
"""

import argparse
import sys
from pathlib import Path
from typing import Any

from inspect_ai.log import recompute_metrics, write_eval_log

from eduinject.analysis import rescored_scores, winning_samples


def _local(location: str) -> Path:
    # shortcut: local log directories only; use inspect's filesystem() for s3.
    return Path(location.removeprefix("file://")).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", required=True, help="logs to rescore (read)")
    parser.add_argument("--out-dir", required=True, help="where the copies go")
    parser.add_argument(
        "--allow-overwrite",
        action="store_true",
        help="replace files already in OUT",
    )
    args = parser.parse_args(argv)
    src, out = _local(args.log_dir), _local(args.out_dir)
    if out == src or src in out.parents or out in src.parents:
        print(f"refused: --out-dir {out} overlaps --log-dir {src}", file=sys.stderr)
        return 2

    written: list[Path] = []

    def write(log: Any) -> None:
        target = out / _local(log.location).relative_to(src)
        if target.exists() and not args.allow_overwrite:
            raise FileExistsError(f"{target} exists; pass --allow-overwrite")
        target.parent.mkdir(parents=True, exist_ok=True)
        recompute_metrics(log)
        write_eval_log(log, str(target))
        written.append(target)

    current: Any = None
    try:
        for log, sample in winning_samples([str(src)]):
            if current is not None and log is not current:
                write(current)
            current = log
            sample.scores = rescored_scores(sample, log.eval.metadata or {})
        if current is not None:
            write(current)
    except FileExistsError as ex:
        print(f"refused: {ex}", file=sys.stderr)
        return 2
    for path in written:
        print(path)
    print(f"{len(written)} log(s) rescored into {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
