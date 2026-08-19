#!/usr/bin/env python3
"""Sweep the pipeline across write scope and stage isolation.

Isolation is swept, not assumed: `--isolation both` runs the isolated
condition alongside its negative control, and a result that does not move
between them is a result about the workflow rather than about the injection.

Every cell is a separate task whose metadata carries `config_hash(...)`, so the
pinned extraction stack, the document versions and the run parameters behind
any number in the logs are recoverable without consulting this script.
"""

import argparse
import os
import sys
from pathlib import Path

from inspect_ai import eval_set

from eduinject.task import DEFAULT_MANIFEST, eduinject_w2
from eduinject.tools.ats import SCOPES

ISOLATION_CHOICES = {"isolated": [True], "control": [False], "both": [True, False]}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=os.environ.get("INSPECT_EVAL_MODEL"),
        help="Model to evaluate (defaults to $INSPECT_EVAL_MODEL).",
    )
    parser.add_argument(
        "--log-dir", default="logs/sweep", help="Directory for the eval set logs."
    )
    parser.add_argument(
        "--scopes",
        nargs="+",
        default=list(SCOPES),
        choices=list(SCOPES),
        help="Write scopes to sweep.",
    )
    parser.add_argument(
        "--isolation",
        default="both",
        choices=sorted(ISOLATION_CHOICES),
        help="Isolation conditions to sweep ('both' includes the negative control).",
    )
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit samples per task."
    )
    parser.add_argument(
        "--max-connections",
        type=int,
        default=None,
        help="Max concurrent model connections.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.model:
        print(
            "no model: pass --model or set INSPECT_EVAL_MODEL "
            "(see .env.example)",
            file=sys.stderr,
        )
        return 2

    isolation = ISOLATION_CHOICES[args.isolation]
    tasks = [
        eduinject_w2(scope=scope, isolated=isolated, manifest=args.manifest)
        for scope in args.scopes
        for isolated in isolation
    ]

    print(f"sweeping {len(tasks)} cell(s) on {args.model}")
    for task in tasks:
        print(
            f"  scope={task.metadata['scope']:<10} "
            f"isolated={str(task.metadata['isolated']):<5} "
            f"config_hash={task.metadata['config_hash']}"
        )

    success, logs = eval_set(
        tasks,
        log_dir=args.log_dir,
        model=args.model,
        limit=args.limit,
        max_connections=args.max_connections,
    )

    print(f"\n{'config_hash':<18}{'scope':<12}{'isolated':<10}{'status':<10}scores")
    for log in logs:
        metadata = log.eval.metadata or {}
        scores = []
        for score in (log.results.scores if log.results else []) or []:
            # A dict-valued Score becomes one EvalScore per key, all carrying
            # the same scorer name, so both are needed to identify a number.
            label = (
                score.name
                if score.name == score.scorer
                else f"{score.scorer}.{score.name}"
            )
            mean = score.metrics.get("mean")
            if mean is not None:
                scores.append(f"{label}={mean.value:g}")
        print(
            f"{str(metadata.get('config_hash')):<18}"
            f"{str(metadata.get('scope')):<12}"
            f"{str(metadata.get('isolated')):<10}"
            f"{log.status:<10}"
            f"{', '.join(scores)}"
        )

    print(f"\nlogs: {Path(args.log_dir).resolve()}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
