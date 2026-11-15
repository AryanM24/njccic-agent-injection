#!/usr/bin/env python3
"""Behaviour models over the A4 feature table (doc 11 §3.6).

    behavior_models.py chain    --features logs/features/<name>.csv --out logs/behavior/
    behavior_models.py halflife --features logs/features/<name>.csv --out logs/behavior/
    behavior_models.py predict  --features logs/features/<name>.csv --out logs/behavior/
    behavior_models.py profiles --features logs/features/<name>.csv --out logs/behavior/

`chain` writes `chain.csv` (transition and emission fractions) and
`decomposition.csv`; `halflife` writes `halflife.csv` (whole marker, each
component marker as content, flag language as the warning). Every estimate
is per experimental cell (`analysis.CELL_FIELDS`; half-lives pool relay depths
only) with a pair-bootstrap 95% interval and the count of bootstrap draws that
defined it. `predict` (A7, doc 11 §3.7) cross-validates L1 logistic and
depth-4 tree predictors from `pre_outcome` columns only, for harmful
completion, carry to the action stage and the five most violated rules:
`predictors.csv`, `calibration.csv`, `coefficients.csv`, `drop_column.csv`,
`trees.txt`. `profiles` writes `profile_<model>.md` per model, templated
sentences only. OUT must lie under the repository's `logs/`. Nothing here
contacts a model.
"""

import argparse
import csv
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from eduinject.analysis import N_BOOT
from eduinject.behavior.predictors import (
    TARGETS,
    cross_validate,
    explain,
    profile_stats,
    top_rule_targets,
    write_profile,
)
from eduinject.behavior.propagation_model import (
    GROUP_FIELDS,
    HALFLIFE_FIELDS,
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
    ap.add_argument("command", choices=("chain", "halflife", "predict", "profiles"))
    ap.add_argument("--features", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--n-boot",
        type=int,
        default=N_BOOT,
        help="pair resamples for predict/profiles coefficient CIs",
    )
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

                    ci = bootstrap_pairs(paths, stat)
                    chain_rows.append(
                        cell
                        | {"kind": kind, "from": frm, "to": to, "p": p, "lo": ci.lo}
                        | {"hi": ci.hi, "n_boot_kept": ci.kept, "n_runs": chain.n_runs}
                    )
        for i, (name, value) in enumerate(decompose(paths)._asdict().items()):

            def part(chosen: list[RunPath], i: int = i) -> float:
                return float(decompose(chosen)[i])

            ci = bootstrap_pairs(paths, part)
            decomp_rows.append(
                cell
                | {"quantity": name, "value": value, "lo": ci.lo, "hi": ci.hi}
                | {"n_boot_kept": ci.kept, "n_runs": len(paths)}
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
                    dict(zip(HALFLIFE_FIELDS, key)) | {"family": family} | fit._asdict()
                )
    return out


def _predict(rows: list[dict[str, Any]], out: Path, n_boot: int) -> None:
    cv_rows: list[dict[str, Any]] = []
    calib: list[dict[str, Any]] = []
    coefs: list[dict[str, Any]] = []
    drops: list[dict[str, Any]] = []
    trees: list[str] = []
    for target in (*TARGETS, *top_rule_targets(rows)):
        for model in ("l1", "tree"):
            for scheme in ("group_kfold", "leave_one_base_out"):
                cv = cross_validate(rows, target, model, scheme)  # type: ignore[arg-type]
                key = {"target": target, "model": model, "scheme": scheme}
                cv_rows.append(
                    key
                    | cv._asdict()
                    | {
                        "calibration": len(cv.calibration),
                        "fold_auroc": ";".join(f"{a:.4f}" for a in cv.fold_auroc),
                    }
                )
                calib += [
                    key | {"mean_predicted": p, "observed": o, "n": n}
                    for p, o, n in cv.calibration
                ]
        expl = explain(rows, target, n_boot)
        coefs += [{"target": target} | c._asdict() for c in expl.std_coefs]
        drops += [
            {"target": target, "column": c, "brier_increase": v}
            for c, v in expl.drop_column.items()
        ]
        trees.append(f"## {target} (n = {expl.n})\n{expl.tree_text}")
    _write(out / "predictors.csv", cv_rows)
    _write(out / "calibration.csv", calib)
    _write(out / "coefficients.csv", coefs)
    _write(out / "drop_column.csv", drops)
    (out / "trees.txt").write_text("\n".join(trees), encoding="utf-8")


def _profiles(rows: list[dict[str, Any]], out: Path, n_boot: int) -> None:
    for model in sorted({str(r.get("model", "")) for r in rows}):
        mine = [r for r in rows if str(r.get("model", "")) == model]
        path = out / f"profile_{re.sub(r'[^A-Za-z0-9._-]', '_', model)}.md"
        write_profile(model, profile_stats(mine, n_boot=n_boot), path)
        print(f"profile -> {path}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = Path(args.out).resolve()
    if not out.is_relative_to(LOGS):
        print(f"refused: --out {args.out} is not under {LOGS}", file=sys.stderr)
        return 2
    with open(args.features, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out.mkdir(parents=True, exist_ok=True)
    if args.command == "chain":
        chain_rows, decomp_rows = _chain(group_rows(rows))
        _write(out / "chain.csv", chain_rows)
        _write(out / "decomposition.csv", decomp_rows)
    elif args.command == "halflife":
        _write(out / "halflife.csv", _halflife(group_rows(rows, HALFLIFE_FIELDS)))
    elif args.command == "predict":
        _predict(rows, out, args.n_boot)
    else:
        _profiles(rows, out, args.n_boot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
