#!/usr/bin/env python3
"""Severity-weighted risk and the security–utility frontier (A8, doc 11 §3.8).

    risk_report.py --features logs/features/<name>.csv \
                   [--weights configs/severity_weights.json] --out logs/risk/

Per experimental cell (`analysis.CELL_FIELDS`, never pooled) writes
`risk.csv` (composite risk with its pair-bootstrap 95% interval, every ΔP_h
and every weight beside it, twin utility), `sensitivity.csv` (Kendall τ of
the cell ranking per Dirichlet weight draw) and `frontier.csv` (risk, utility
and whether the cell is Pareto-optimal). A composite is a weighted share over
the harms its cell can exhibit, which differ by workflow, so composites are
comparable only within a workflow: the frontier and the sensitivity ranking
are computed per workflow, and `risk.csv` lists each cell's `harms_defined`.
Refuses an OUT outside the
repository's `logs/` (exit 2) and a feature table whose `<name>.roles.json`
is missing or names another `FEATURES_VERSION` (stale; exit 4). Nothing here
contacts a model.
"""

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from eduinject.analysis import CELL_FIELDS, N_BOOT
from eduinject.behavior.propagation_model import group_rows
from eduinject.features import FEATURES_VERSION
from eduinject.risk import cell_risk, load_weights, pareto_front, weight_sensitivity

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--features", required=True)
    ap.add_argument(
        "--weights", default=str(ROOT / "configs" / "severity_weights.json")
    )
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-boot", type=int, default=N_BOOT)
    ap.add_argument("--n-draws", type=int, default=N_BOOT)
    ap.add_argument("--kappa", type=float, default=50.0)
    return ap.parse_args(argv)


def _write(path: Path, rows: list[dict[str, Any]], fallback: list[str]) -> None:
    columns = list(dict.fromkeys(c for r in rows for c in r)) or fallback
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} row(s) -> {path}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = Path(args.out).resolve()
    if not out.is_relative_to(LOGS):
        print(f"refused: --out {args.out} is not under {LOGS}", file=sys.stderr)
        return 2
    roles = Path(args.features).with_suffix(".roles.json")
    version = (
        json.loads(roles.read_text(encoding="utf-8")).get("features_version")
        if roles.exists()
        else None
    )
    if version != FEATURES_VERSION:
        print(
            f"refused: {args.features} was built at features_version {version}, "
            f"not {FEATURES_VERSION}; rebuild it with build_features.py",
            file=sys.stderr,
        )
        return 4
    weights = load_weights(args.weights)
    with open(args.features, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out.mkdir(parents=True, exist_ok=True)

    risks = {
        cell: cell_risk(cell_rows, weights.weights, args.n_boot)
        for cell, cell_rows in group_rows(rows, CELL_FIELDS).items()
    }
    wf = CELL_FIELDS.index("workflow")
    by_workflow: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for cell in risks:
        by_workflow[cell[wf]].append(cell)
    front = set().union(
        *(
            pareto_front({c: (risks[c].risk, risks[c].utility) for c in cells})
            for cells in by_workflow.values()
        )
    )
    risk_rows, frontier_rows = [], []
    for cell, r in risks.items():
        key = dict(zip(CELL_FIELDS, cell, strict=True))
        risk_rows.append(
            key
            | {
                "weights_version": weights.version,
                "n_pairs": r.n_pairs,
                "risk": r.risk,
                "risk_lo": r.lo,
                "risk_hi": r.hi,
                "n_boot_kept": r.n_boot_kept,
                "utility": r.utility,
                "harms_defined": ";".join(
                    h for h, d in r.delta.items() if not math.isnan(d)
                ),
            }
            | {f"delta:{h}": d for h, d in r.delta.items()}
            | {f"weight:{h}": w for h, w in r.weights.items()}
        )
        frontier_rows.append(
            key
            | {"risk": r.risk, "utility": r.utility, "pareto_optimal": cell in front}
        )
    _write(out / "risk.csv", risk_rows, list(CELL_FIELDS))
    _write(out / "frontier.csv", frontier_rows, list(CELL_FIELDS))
    sens_rows: list[dict[str, Any]] = []
    for workflow, cells in sorted(by_workflow.items()):
        n_cells = sum(not math.isnan(risks[c].risk) for c in cells)
        taus = weight_sensitivity(
            {c: risks[c].delta for c in cells},
            weights.weights,
            n_draws=args.n_draws,
            kappa=args.kappa,
        )
        sens_rows += [
            {
                "workflow": workflow,
                "draw": i,
                "kappa": args.kappa,
                "n_cells": n_cells,
                "kendall_tau": t,
            }
            for i, t in enumerate(taus)
        ]
        if taus:
            print(
                f"{workflow}: Kendall tau median {statistics.median(taus):.3f}, "
                f"min {min(taus):.3f} over {n_cells} cells"
            )
    _write(
        out / "sensitivity.csv",
        sens_rows,
        ["workflow", "draw", "kappa", "n_cells", "kendall_tau"],
    )
    print(
        "composites are comparable only within a workflow "
        "(frontier and sensitivity are per workflow)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
