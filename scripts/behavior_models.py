#!/usr/bin/env python3
"""Behaviour models over the A4 feature table (doc 11 §3.6).

    behavior_models.py chain    --features logs/features/<name>.csv --out logs/behavior/
    behavior_models.py halflife --features logs/features/<name>.csv --out logs/behavior/

`chain` writes `chain.csv` (transition and emission fractions) and
`decomposition.csv`; `halflife` writes `halflife.csv` (whole marker, each
component marker as content, flag language as the warning). Every estimate
is per (model, workflow, isolated, handoff_mode, gate) with a pair-bootstrap
95% interval. OUT must lie under the repository's `logs/`. Nothing here
contacts a model.
"""

import argparse
import csv
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from eduinject.behavior.propagation_model import (
    GROUP_FIELDS,
    RunPath,
    bootstrap_pairs,
    decompose,
    fit_chain,
    group_rows,
    paths_from_features,
    survival,
)

LOGS = Path(__file__).resolve().parents[1] / "logs"
_COMPONENT = re.compile(r"carry:analysis:(?P<c>[^:]+)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("command", choices=("chain", "halflife"))
    ap.add_argument("--features", required=True)
    ap.add_argument("--out", required=True)
    return ap.parse_args(argv)


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = list(dict.fromkeys(c for r in rows for c in r)) or list(GROUP_FIELDS)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} row(s) -> {path}")


def _chain(
    groups: Mapping[tuple[str, ...], Sequence[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chain_rows: list[dict[str, Any]] = []
    decomp_rows: list[dict[str, Any]] = []
    for key, rows in groups.items():
        cell = dict(zip(GROUP_FIELDS, key))
        paths = paths_from_features(rows)
        if not paths:
            continue
        chain = fit_chain(paths)
        for kind in ("transition", "emission"):
            for frm, row in getattr(chain, kind).items():
                for to, p in row.items():

                    def stat(
                        chosen: list[RunPath],
                        kind: str = kind,
                        frm: str = frm,
                        to: str = to,
                    ) -> float:
                        fitted = getattr(fit_chain(chosen), kind)
                        return float(fitted[frm][to]) if frm in fitted else float("nan")

                    lo, hi = bootstrap_pairs(paths, stat)
                    chain_rows.append(
                        cell
                        | {"kind": kind, "from": frm, "to": to, "p": p, "lo": lo}
                        | {"hi": hi, "n_runs": chain.n_runs}
                    )
        for i, (name, value) in enumerate(decompose(paths)._asdict().items()):

            def part(chosen: list[RunPath], i: int = i) -> float:
                return float(decompose(chosen)[i])

            lo, hi = bootstrap_pairs(paths, part)
            decomp_rows.append(
                cell
                | {"quantity": name, "value": value, "lo": lo, "hi": hi}
                | {"n_runs": len(paths)}
            )
    return chain_rows, decomp_rows


def _halflife(
    groups: Mapping[tuple[str, ...], Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, rows in groups.items():
        components = sorted(
            {m["c"] for r in rows for k in r if (m := _COMPONENT.fullmatch(k))}
        )
        families = {"marker": "carry", "warning": "flag"} | {
            f"content:{c}": f"carry:{c}" for c in components
        }
        for family, column in families.items():
            fit = survival(rows, column)
            if fit.n:
                out.append(
                    dict(zip(GROUP_FIELDS, key)) | {"family": family} | fit._asdict()
                )
    return out


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = Path(args.out).resolve()
    if not out.is_relative_to(LOGS):
        print(f"refused: --out {args.out} is not under {LOGS}", file=sys.stderr)
        return 2
    with open(args.features, newline="", encoding="utf-8") as f:
        groups = group_rows(csv.DictReader(f))
    out.mkdir(parents=True, exist_ok=True)
    if args.command == "chain":
        chain_rows, decomp_rows = _chain(groups)
        _write(out / "chain.csv", chain_rows)
        _write(out / "decomposition.csv", decomp_rows)
    else:
        _write(out / "halflife.csv", _halflife(groups))
    return 0


if __name__ == "__main__":
    sys.exit(main())
