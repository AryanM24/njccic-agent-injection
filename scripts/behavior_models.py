#!/usr/bin/env python3
"""Behaviour models over the A4 feature table (doc 11 §3.6, doc 14 §3).

    behavior_models.py ladder   --features logs/features/<name>.csv --out logs/behavior/
    behavior_models.py chain    --features logs/features/<name>.csv --out logs/behavior/
    behavior_models.py halflife --features logs/features/<name>.csv --out logs/behavior/
    behavior_models.py predict  --features logs/features/<name>.csv --out logs/behavior/
    behavior_models.py profiles --features logs/features/<name>.csv --out logs/behavior/
    behavior_models.py transfer --features logs/features/<name>.csv --out logs/behavior/
                       --held-out MODEL [MODEL ...] [--train-split dev] [--test-split confirm]

`ladder` writes `ladder.csv` (per cell and behaviour: attack rate, twin rate and
their within-pair difference, pairs averaged within a base scenario and
scenarios equally weighted, with a scenario-bootstrap interval) and
`transitions.csv` (P(next state | state) per cell and label, with counts, and on
attack runs the same standardised to the pooled pair mix over the pairs where
every model of the cell has the conditioning event). `chain` writes `chain.csv` (transition and emission fractions) and
`decomposition.csv`; `halflife` writes `halflife.csv` (whole marker, each
component marker as content, flag language as the warning; appendix). Every estimate
is per experimental cell (`analysis.CELL_FIELDS`; half-lives pool relay depths
only) with a pair-bootstrap 95% interval and the count of bootstrap draws that
defined it. `predict` (A7, doc 11 §3.7) cross-validates L1 logistic and
depth-4 tree predictors from `pre_outcome` columns only, grouped by pair,
by base scenario and by model (leave one model out: does a predictor transfer
to a model it never saw?), for harmful completion, carry to the action stage and the five most violated rules:
`predictors.csv`, `calibration.csv`, `coefficients.csv`, `drop_column.csv`,
`trees.txt`. `profiles` writes `profile_<model>.md` per model (appendix),
templated sentences only. `transfer` (doc 14 §5) fits the L1 predictor on the
other models' `--train-split` runs, scores it on each held-out model's
`--test-split` runs and writes `transfer.csv`, one row per target and held-out
model, with the training models' own leave-one-model-out mean AUROC beside it.
It uses runs in which one model served every stage (no `reader_model`). OUT must lie under the repository's `logs/` (exit 2), and a
feature table whose `<name>.roles.json` is missing or names another
`FEATURES_VERSION` is refused as stale (exit 4). Nothing here contacts a model.
"""

import argparse
import csv
import math
import re
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import mean
from typing import Any, get_args

from eduinject.analysis import N_BOOT, mean_with_ci
from eduinject.behavior.ladder import ATTACK_ONLY, BEHAVIOURS, num
from eduinject.behavior.predictors import (
    SERVED_FIELDS,
    TARGETS,
    Scheme,
    cross_validate,
    explain,
    profile_stats,
    top_rule_targets,
    transfer,
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
from eduinject.features import stale_features
from eduinject.stats import scenario_key

LOGS = Path(__file__).resolve().parents[1] / "logs"
_COMPONENT = re.compile(r"carry:analysis:(?P<c>[^:]+)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "command",
        choices=("ladder", "chain", "halflife", "predict", "profiles", "transfer"),
    )
    ap.add_argument("--features", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--n-boot",
        type=int,
        default=N_BOOT,
        help="resamples for the ladder intervals (scenarios) and the "
        "predict/profiles coefficient CIs (pairs)",
    )
    ap.add_argument("--train-split", choices=("dev", "confirm"), default="dev")
    ap.add_argument("--test-split", choices=("dev", "confirm"), default="confirm")
    ap.add_argument(
        "--held-out", nargs="+", default=[], metavar="MODEL", help="model slugs"
    )
    args = ap.parse_args(argv)
    if args.command == "transfer" and not args.held_out:
        ap.error("transfer needs --held-out")
    return args


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = list(dict.fromkeys(c for r in rows for c in r)) or list(GROUP_FIELDS)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} row(s) -> {path}")


Rows = Sequence[Mapping[str, Any]]


def _per_scenario(values: Mapping[str, list[float]], rows: Rows) -> dict[Any, float]:
    """Pair values (mean over epochs) averaged within each base scenario."""
    of = {str(r["artifact_id"]): scenario_key(r) for r in rows}
    groups: dict[Any, list[float]] = defaultdict(list)
    for pair, v in values.items():
        groups[of[pair]].append(mean(v))
    return {s: mean(v) for s, v in groups.items()}


def _ladder(
    groups: Mapping[tuple[str, ...], Rows], n_boot: int
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, rows in groups.items():
        for name in BEHAVIOURS:
            blocks: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
            for r in rows:
                if not math.isnan(y := num(r.get(f"beh:{name}"))):
                    block = (str(r["artifact_id"]), str(r["epoch"]))
                    blocks[block][str(r["label"])] = y
            alone = name in ATTACK_ONLY
            need = {"attack"} if alone else {"attack", "twin"}
            sides: dict[str, dict[str, list[float]]] = {
                "attack": defaultdict(list),
                "twin": defaultdict(list),
                "diff": defaultdict(list),
            }
            for (pair, _), run in blocks.items():
                if not need <= set(run):
                    continue
                sides["attack"][pair].append(run["attack"])
                if not alone:
                    sides["twin"][pair].append(run["twin"])
                    sides["diff"][pair].append(run["attack"] - run["twin"])
            if not sides["attack"]:
                continue
            attack = _per_scenario(sides["attack"], rows)
            twin = _per_scenario(sides["twin"], rows)
            # A behaviour only an attack run can show has its own rate's interval.
            per_pair = sides["attack" if alone else "diff"]
            ci = mean_with_ci(_per_scenario(per_pair, rows), n_boot)
            out.append(
                dict(zip(GROUP_FIELDS, key))
                | {"behaviour": name, "attack_rate": mean(attack.values())}
                | {"twin_rate": mean(twin.values()) if twin else ""}
                | {"difference": ci.diff if ci and not alone else ""}
                | {"lo": ci.lo if ci else "", "hi": ci.hi if ci else ""}
                | {"n_pairs": len(sides["attack"]), "n_scenarios": len(attack)}
            )
    return out


TRANSITIONS = (
    ("uptake", "relay"),
    ("relay", "adopt"),
    ("relay", "attempt_strict"),
    ("adopt", "attempt"),
    ("adopt", "attempt_strict"),
    ("attempt", "harm"),
)
"""Doc 14 §3. P(attempt | adopt) is partly by definition (misdirection), so
`attempt_strict` is reported beside it; P(harm | attempt) is the arm's."""


def _hits(rows: Rows, label: str, frm: str, to: str) -> dict[str, list[float]]:
    """Per pair: `state:to` on its `label` runs where `state:frm` holds."""
    hits: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        y = num(r.get(f"state:{to}"))
        if math.isnan(y) or r["label"] != label:
            continue
        if num(r.get(f"state:{frm}")) == 1.0:
            hits[str(r["artifact_id"])].append(y)
    return hits


def _transitions(groups: Mapping[tuple[str, ...], Rows]) -> list[dict[str, Any]]:
    # Cells that differ only in the model as served are the compared models.
    families: dict[tuple[str, ...], list[tuple[str, ...]]] = defaultdict(list)
    for key in groups:
        cell = dict(zip(GROUP_FIELDS, key))
        families[tuple(v for f, v in cell.items() if f not in SERVED_FIELDS)].append(
            key
        )
    out: list[dict[str, Any]] = []
    for keys in families.values():
        for label in ("attack", "twin"):
            for frm, to in TRANSITIONS:
                hits = {k: _hits(groups[k], label, frm, to) for k in keys}
                common = set.intersection(*(set(h) for h in hits.values()))
                weight = {p: sum(len(h[p]) for h in hits.values()) for p in common}
                for key, h in hits.items():
                    ys = [y for v in h.values() for y in v]
                    std = sum(w * mean(h[p]) for p, w in weight.items())
                    standard = label == "attack" and len(keys) > 1 and bool(common)
                    out.append(
                        dict(zip(GROUP_FIELDS, key))
                        | {"label": label, "from": frm, "to": to}
                        | {"k": int(sum(ys)), "n": len(ys)}
                        | {"p": mean(ys) if ys else ""}
                        | {
                            "p_standardised": std / sum(weight.values())
                            if standard
                            else "",
                            "n_pairs_common": len(common) if len(keys) > 1 else "",
                        }
                    )
    return out


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
                    {"section": "appendix"}
                    | dict(zip(HALFLIFE_FIELDS, key))
                    | {"family": family}
                    | fit._asdict()
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
            for scheme in get_args(Scheme):
                cv = cross_validate(rows, target, model, scheme)  # type: ignore[arg-type]
                key = {"target": target, "model": model, "scheme": scheme}
                cv_rows.append(
                    key
                    | cv._asdict()
                    | {
                        "calibration": len(cv.calibration),
                        "fold_auroc": ";".join(f"{a:.4f}" for a in cv.fold_auroc),
                        "fold_groups": ";".join(cv.fold_groups),
                    }
                )
                calib += [
                    key | {"mean_predicted": p, "observed": o, "n": n}
                    for p, o, n in cv.calibration
                ]
        expl = explain(rows, target, n_boot)
        coefs += [
            {"target": target} | c._asdict() | {"n_boot_kept": expl.n_boot_kept}
            for c in expl.std_coefs
        ]
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


def _transfer(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[Any]:
    own = [r for r in rows if not r.get("reader_model")]
    missing = set(args.held_out) - {r.get("model") for r in own}
    if missing:
        raise ValueError(f"no runs of held-out model(s) {sorted(missing)}")
    train = [
        r
        for r in own
        if r.get("split") == args.train_split and r.get("model") not in args.held_out
    ]
    out = []
    for target in TARGETS:
        dev = cross_validate(train, target, "l1", "leave_one_model_out")
        for held in args.held_out:
            test = [
                r
                for r in own
                if r.get("split") == args.test_split and r.get("model") == held
            ]
            result = transfer(train, test, target, n_boot=args.n_boot)
            out.append(
                {"target": target, "held_out": held, "n_train": len(train)}
                | result._asdict()
                | {
                    "dev_lomo_auroc": dev.auroc,
                    "auroc_minus_dev_lomo": result.auroc - dev.auroc,
                }
            )
    return out


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
    if stale := stale_features(args.features):
        print(f"refused: {stale}", file=sys.stderr)
        return 4
    with open(args.features, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out.mkdir(parents=True, exist_ok=True)
    if args.command == "ladder":
        _write(out / "ladder.csv", _ladder(group_rows(rows), args.n_boot))
        _write(out / "transitions.csv", _transitions(group_rows(rows)))
    elif args.command == "chain":
        chain_rows, decomp_rows = _chain(group_rows(rows))
        _write(out / "chain.csv", chain_rows)
        _write(out / "decomposition.csv", decomp_rows)
    elif args.command == "halflife":
        _write(out / "halflife.csv", _halflife(group_rows(rows, HALFLIFE_FIELDS)))
    elif args.command == "predict":
        _predict(rows, out, args.n_boot)
    elif args.command == "transfer":
        _write(out / "transfer.csv", _transfer(rows, args))
    else:
        _profiles(rows, out, args.n_boot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
