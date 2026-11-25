#!/usr/bin/env python3
"""Build the per-run feature table (doc 11 §3.4, A4).

    build_features.py --log-dir DIR [DIR ...] --out logs/features/<name>.csv
                      [--split dev|confirm] [--swap] [--allow-stale]

Writes `<name>.csv` (one row per recorded run) and `<name>.roles.json`
(`features_version`, and column -> `pre_outcome` | `outcome`). `--swap` also
writes `<name>.swap.csv` (and its roles): the four message-swap runs of every
swap sample (doc 14 §4), with the swap cell in the column `swap`. OUT must
lie under the repository's `logs/`: features hold Tier 1 coordinates. Refuses logs
whose scores are stale. Nothing here contacts a model.
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from eduinject.analysis import refuse_stale
from eduinject.features import (
    FEATURES_VERSION,
    feature_row,
    feature_rows,
    role_of,
)
from eduinject.records import records_from_logs, swap_records_from_logs

LOGS = Path(__file__).resolve().parents[1] / "logs"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--log-dir", nargs="+", required=True, dest="log_dirs")
    ap.add_argument("--out", required=True)
    ap.add_argument("--split", choices=("dev", "confirm"), default=None)
    ap.add_argument("--swap", action="store_true")
    ap.add_argument("--allow-stale", action="store_true")
    return ap.parse_args(argv)


def _write(out: Path, rows: list[dict[str, Any]]) -> None:
    columns = list(dict.fromkeys(c for r in rows for c in r))
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    roles = {c: role_of(c) for c in columns}
    out.with_suffix(".roles.json").write_text(
        json.dumps({"features_version": FEATURES_VERSION, "roles": roles}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"{len(rows)} run(s), {len(columns)} column(s) -> {out}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = Path(args.out)
    if not out.resolve().is_relative_to(LOGS) or out.suffix != ".csv":
        print(f"refused: --out {out} is not a .csv under {LOGS}", file=sys.stderr)
        return 2
    if refuse_stale(args.log_dirs, args.allow_stale):
        return 4
    out.parent.mkdir(parents=True, exist_ok=True)
    _write(out, feature_rows(records_from_logs(args.log_dirs, split=args.split)))
    if args.swap:
        # No `pair`: a swap run has three counterparts, so the pair-level
        # columns (rank shift, substitution) are undefined.
        rows = [
            feature_row(r, None) | {"swap": r.swap}
            for r in swap_records_from_logs(args.log_dirs, split=args.split)
        ]
        _write(out.with_suffix(".swap.csv"), rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
