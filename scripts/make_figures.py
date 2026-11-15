"""E1: figures drawn from the CSVs the analysis scripts already wrote.

    python scripts/make_figures.py --in logs/features logs/behavior logs/risk \\
        logs/audit/<name> --out logs/figures/

`--in` takes directories (searched recursively) under `logs/`; each figure
finds its CSV by name and is skipped with a printed note when it is absent.
The feature table is the one CSV with `out:rank_shift`: its path is printed,
and two candidates are refused (exit 2). Every figure keeps cells apart: one
line, box or panel per combination of the CELL_FIELDS that vary.
Writes, per what exists: `stage_survival_<model>.png` (features),
`halflife_content_vs_warning.png` (halflife.csv), `transitions_<cell>.png`
(chain.csv), `pareto_frontier.png` and `risk_heatmap.png` (risk.csv,
frontier.csv; one panel per workflow, since composites are comparable only
within a workflow), `rank_shift.png` (features) and
`violations_by_origin_stage.png` (violations.csv). `--by goal|channel|file_type`
adds a rank-shift slice named and titled RESTRICTED. Inputs and `--out` must
be under the repository's `logs/`, which is gitignored: never commit a figure.
"""

import argparse
import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from eduinject.analysis import CELL_FIELDS
from eduinject.behavior.propagation_model import is_on, stage_order, stages_of

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
# Okabe-Ito: distinguishable under the common colour-vision deficiencies.
PALETTE = (
    "#0072B2",
    "#E69F00",
    "#009E73",
    "#CC79A7",
    "#56B4E9",
    "#D55E00",
    "#F0E442",
    "#000000",
)
Row = dict[str, str]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="inputs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--by", choices=("goal", "channel", "file_type"))
    return ap.parse_args(argv)


def num(v: str | None) -> float:
    try:
        return float(v) if v not in (None, "") else math.nan
    except ValueError:
        return math.nan


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "x"


def read(path: Path) -> list[Row]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def find(dirs: list[Path], name: str) -> list[Row] | None:
    for d in dirs:
        for p in sorted(d.rglob(name)):
            return read(p)
    return None


def find_features(dirs: list[Path]) -> list[Row] | None:
    """The one feature table under `dirs` (a CSV with `out:rank_shift`).

    Raises:
        ValueError: More than one feature table was found; pass `--in` narrower.
    """
    found = []
    for d in dirs:
        for p in sorted(d.rglob("*.csv")):
            with p.open(newline="", encoding="utf-8") as f:
                if "out:rank_shift" in (next(csv.reader(f), [])):
                    found.append(p)
    if len(found) > 1:
        raise ValueError(
            "more than one feature table; narrow --in to one of: "
            + ", ".join(map(str, found))
        )
    if not found:
        return None
    print(f"features <- {found[0]}")
    return read(found[0])


def label(row: Row, fields: tuple[str, ...]) -> str:
    return " | ".join(row.get(f, "") for f in fields if row.get(f, ""))


def labeller(rows: list[Row], skip: tuple[str, ...] = ("model",)) -> Any:
    """Row -> label naming every CELL_FIELD that varies across `rows` (bar `skip`).

    Cells differing in any field are never pooled, so each must get its own label.
    """
    varying = [
        f
        for f in CELL_FIELDS
        if f not in skip and len({r.get(f, "") for r in rows}) > 1
    ]
    return lambda r: ", ".join(f"{f}={r.get(f, '')}" for f in varying)


def save(fig: Any, out: Path, name: str) -> Path:
    fig.tight_layout()
    path = out / name
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"figure -> {path}")
    return path


def err(rows: list[Row], value: str, lo: str, hi: str) -> list[list[float]]:
    """Asymmetric error-bar half-widths, zero where the CI is missing."""
    low, high = [], []
    for r in rows:
        v, a, b = num(r.get(value)), num(r.get(lo)), num(r.get(hi))
        low.append(max(v - a, 0.0) if not math.isnan(a + v) else 0.0)
        high.append(max(b - v, 0.0) if not math.isnan(b + v) else 0.0)
    return [low, high]


def stage_survival(feats: list[Row], out: Path) -> list[Path]:
    """Per model, one line per cell over every stage the runs had (relays too);
    each point's denominator is the runs that had that stage."""
    attacks = [
        r for r in feats if r.get("label") == "attack" and r.get("status") == "ok"
    ]
    arm = labeller(attacks, ())
    by_model: dict[str, dict[str, list[Row]]] = defaultdict(lambda: defaultdict(list))
    for r in attacks:
        by_model[r["model"]][arm(r)].append(r)
    paths = []
    for model, cells in sorted(by_model.items()):
        stages = sorted(
            {s for rows in cells.values() for r in rows for s in stages_of(r)},
            key=stage_order,
        )
        fig, ax = plt.subplots(figsize=(max(6, 1.1 * len(stages)), 4))
        for i, (cell, rows) in enumerate(sorted(cells.items())):
            xs, ys = [], []
            for x, s in enumerate(stages):
                had = [r[f"carry:{s}"] for r in rows if r.get(f"carry:{s}")]
                if had:
                    xs.append(x)
                    ys.append(sum(map(is_on, had)) / len(had))
            ax.plot(xs, ys, marker="o", color=PALETTE[i % 8], label=cell or "all")
        ax.set_xticks(range(len(stages)), stages, rotation=20)
        ax.set(
            ylim=(0, 1.02),
            xlabel="pipeline stage",
            ylabel="share of attack runs carrying the marker",
            title=f"Stage survival: {model}",
        )
        ax.legend(fontsize=7)
        paths.append(save(fig, out, f"stage_survival_{slug(model)}.png"))
    return paths


def halflife(rows: list[Row], out: Path) -> Path:
    name = labeller(rows, ())
    cells = sorted({name(r) for r in rows})
    fams = sorted({r["family"] for r in rows}, key=lambda f: (f != "warning", f))
    fig, ax = plt.subplots(figsize=(max(6, 1.2 * len(cells)), 4.5))
    w = 0.8 / max(len(fams), 1)
    for j, fam in enumerate(fams):
        mine = {name(r): r for r in rows if r["family"] == fam}
        if len(mine) != sum(r["family"] == fam for r in rows):
            raise ValueError(f"two cells share a half-life label: {fam}")
        sel = [mine[c] for c in cells if c in mine]
        xs = [cells.index(name(r)) + j * w for r in sel]
        ax.bar(
            xs,
            [num(r["half_life"]) for r in sel],
            w,
            yerr=err(sel, "half_life", "lo", "hi"),
            capsize=2,
            color=PALETTE[j % 8],
            label="warning" if fam == "warning" else fam,
        )
    ax.set_xticks(
        [i + 0.4 - w / 2 for i in range(len(cells))],
        cells,
        rotation=30,
        ha="right",
        fontsize=7,
    )
    ax.set(ylabel="half-life (stages)", title="Content vs warning half-life")
    ax.legend(fontsize=7)
    return save(fig, out, "halflife_content_vs_warning.png")


def transitions(rows: list[Row], out: Path) -> list[Path]:
    cells: dict[str, list[Row]] = defaultdict(list)
    rows = [r for r in rows if r.get("kind") == "transition"]
    name = labeller(rows, ())
    for r in rows:
        cells[name(r) or "all"].append(r)
    paths = []
    for cell, rs in sorted(cells.items()):
        frm = sorted({r["from"] for r in rs})
        to = sorted({r["to"] for r in rs})
        grid = [[math.nan] * len(to) for _ in frm]
        for r in rs:
            grid[frm.index(r["from"])][to.index(r["to"])] = num(r["p"])
        fig, ax = plt.subplots(figsize=(5, 4))
        im = ax.imshow(grid, vmin=0, vmax=1, cmap="cividis")
        ax.set_xticks(range(len(to)), to, rotation=30, ha="right")
        ax.set_yticks(range(len(frm)), frm)
        for i, row in enumerate(grid):
            for j, v in enumerate(row):
                if not math.isnan(v):
                    ax.text(
                        j,
                        i,
                        f"{v:.2f}",
                        ha="center",
                        va="center",
                        color="w" if v < 0.6 else "k",
                        fontsize=8,
                    )
        ax.set(xlabel="next state", ylabel="state", title=cell)
        fig.colorbar(im, ax=ax, label="transition probability")
        paths.append(save(fig, out, f"transitions_{slug(cell)}.png"))
    return paths


def by_workflow(rows: list[Row]) -> dict[str, list[Row]]:
    d: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        d[r.get("workflow", "")].append(r)
    return dict(sorted(d.items()))


def pareto(risk: list[Row], front: list[Row] | None, out: Path) -> Path:
    optimal = {
        label(r, CELL_FIELDS): r.get("pareto_optimal") == "True" for r in front or []
    }
    groups = by_workflow(risk)
    fig, axes = plt.subplots(
        1, len(groups), figsize=(5 * len(groups), 4.2), squeeze=False
    )
    for ax, (wf, rows) in zip(axes[0], groups.items(), strict=True):
        rows = [r for r in rows if not math.isnan(num(r["risk"]) + num(r["utility"]))]
        models = sorted({r["model"] for r in rows})
        for r in rows:
            k = label(r, CELL_FIELDS)
            ax.errorbar(
                num(r["utility"]),
                num(r["risk"]),
                yerr=err([r], "risk", "risk_lo", "risk_hi"),
                fmt="D" if optimal.get(k) else "o",
                color=PALETTE[models.index(r["model"]) % 8],
                mfc="none" if not optimal.get(k) else None,
                capsize=2,
            )
        ax.set(
            xlabel="twin utility (higher is better)",
            ylabel="severity-weighted risk (lower is better)",
            title=f"{wf}: diamonds are Pareto-optimal",
        )
        ax.legend(
            [
                plt.Line2D([], [], marker="o", ls="", color=PALETTE[i % 8])
                for i in range(len(models))
            ],
            models,
            fontsize=7,
        )
    return save(fig, out, "pareto_frontier.png")


def heatmap(risk: list[Row], out: Path) -> Path:
    groups = by_workflow(risk)
    fig, axes = plt.subplots(
        1, len(groups), figsize=(6 * len(groups), 4.5), squeeze=False
    )
    for ax, (wf, rows) in zip(axes[0], groups.items(), strict=True):
        arm = labeller(rows, ("model", "scope", "workflow"))
        acc: dict[tuple[str, str], float] = {}
        for r in rows:
            v = num(r["risk"])
            if math.isnan(v):
                continue
            key = (r["model"], f"{r.get('scope', '')} / {arm(r)}")
            if key in acc:
                raise ValueError(f"two cells map to one heatmap square: {key}")
            acc[key] = v
        models = sorted({m for m, _ in acc})
        cols = sorted({c for _, c in acc})
        grid = [[acc.get((m, c), math.nan) for c in cols] for m in models]
        im = ax.imshow(grid, cmap="cividis_r")
        ax.set_xticks(range(len(cols)), cols, rotation=40, ha="right", fontsize=7)
        ax.set_yticks(range(len(models)), models, fontsize=8)
        for i, row in enumerate(grid):
            for j, v in enumerate(row):
                if not math.isnan(v):
                    ax.text(
                        j,
                        i,
                        f"{v:.2f}",
                        ha="center",
                        va="center",
                        fontsize=7,
                        color="k",
                    )
        ax.set(xlabel="scope / arm", ylabel="model", title=f"Risk: {wf}")
        fig.colorbar(im, ax=ax, label="severity-weighted risk")
    return save(fig, out, "risk_heatmap.png")


def rank_shift(feats: list[Row], out: Path, by: str | None) -> Path:
    """One box per cell (every varying CELL_FIELD, model included), split by
    `by` within each cell for the RESTRICTED slice."""
    attacks = [
        r
        for r in feats
        if r.get("label") == "attack" and not math.isnan(num(r.get("out:rank_shift")))
    ]
    cell = labeller(attacks, ())
    groups: dict[str, list[float]] = defaultdict(list)
    for r in attacks:
        key = cell(r) or "all"
        if by:
            key += f" | {by}={r.get(by, '')}"
        groups[key].append(num(r["out:rank_shift"]))
    fig, ax = plt.subplots(figsize=(max(5, 1.3 * len(groups)), 4.5))
    if groups:
        names = sorted(groups)
        ax.boxplot([groups[n] for n in names], tick_labels=names)
        ax.tick_params(axis="x", labelrotation=30, labelsize=7)
    ax.set(ylabel="rank shift of the attacker's candidate (positions)", xlabel="cell")
    ax.set_title(
        ("RESTRICTED: " if by else "")
        + f"Rank shift by cell{f' and {by}' if by else ''}"
    )
    name = f"rank_shift_RESTRICTED_by_{by}.png" if by else "rank_shift.png"
    return save(fig, out, name)


def violations(rows: list[Row], out: Path) -> Path:
    """One panel per cell; bars stack by run label within a panel."""
    cell = labeller(rows, ())
    cells: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        cells[cell(r) or "all"].append(r)
    fig, axes = plt.subplots(1, len(cells), figsize=(5 * len(cells), 4), squeeze=False)
    for ax, (name, rs) in zip(axes[0], sorted(cells.items()), strict=True):
        stages = sorted(
            {r.get("origin_stage") or "unknown" for r in rs},
            key=lambda s: stage_order(s) if s != "unknown" else 10_000,
        )
        labels = sorted({r.get("label", "") for r in rs})
        bottom = [0] * len(stages)
        for i, lab in enumerate(labels):
            counts = [
                sum(
                    1
                    for r in rs
                    if (r.get("origin_stage") or "unknown") == s
                    and r.get("label", "") == lab
                )
                for s in stages
            ]
            ax.bar(
                stages, counts, bottom=bottom, color=PALETTE[i % 8], label=lab or "all"
            )
            bottom = [b + c for b, c in zip(bottom, counts, strict=True)]
        ax.set(
            xlabel="stage where the violation originated",
            ylabel="violations",
            title=name,
        )
        ax.legend(fontsize=7)
    fig.suptitle("Violations by origin stage")
    return save(fig, out, "violations_by_origin_stage.png")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = Path(args.out).resolve()
    dirs = [Path(p).resolve() for p in args.inputs]
    for p in (out, *dirs):
        if not p.is_relative_to(LOGS):
            print(f"refused: {p} is not under {LOGS}", file=sys.stderr)
            return 2
    out.mkdir(parents=True, exist_ok=True)

    def need(name: str, rows: list[Row] | None) -> list[Row] | None:
        if not rows:
            print(f"skipped {name}: input CSV missing or empty")
            return None
        return rows

    try:
        feats = need("stage_survival, rank_shift", find_features(dirs))
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    if feats:
        stage_survival(feats, out)
        rank_shift(feats, out, None)
        if args.by:
            rank_shift(feats, out, args.by)
    if rows := need("halflife", find(dirs, "halflife.csv")):
        halflife(rows, out)
    if rows := need("transitions", find(dirs, "chain.csv")):
        transitions(rows, out)
    risk = need("pareto_frontier, risk_heatmap", find(dirs, "risk.csv"))
    if risk:
        pareto(risk, find(dirs, "frontier.csv"), out)
        heatmap(risk, out)
    if rows := need("violations_by_origin_stage", find(dirs, "violations.csv")):
        violations(rows, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
