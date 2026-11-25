"""Figures drawn from the CSVs the analysis scripts already wrote.

    python scripts/make_figures.py --in logs/endpoints logs/behavior \\
        logs/features --out logs/figures/ [--appendix [--by goal]]

`--in` takes directories (searched recursively) under `logs/`; each figure
finds its CSV by name and is skipped with a printed note when it is absent. The
path read is printed, and two candidates are refused (exit 2). The feature
table is the one CSV with `out:rank_shift` that is no `<name>.swap.csv`. Every
figure keeps cells apart: one line, box or panel per combination of the
CELL_FIELDS that vary; `endpoints` alone pools, and only its own pooled rows are
drawn as pooled. Models are in one fixed order (the declared dev models, then
held-out, then the rest by name), which is not a ranking.

Primary, each as `.png` and `.pdf`: `headroom` (headroom.csv: per workflow and
arm, harm done, permitted but not done, and blocked by the arm), `ladder`
(ladder.csv), `swap_effects` (swap_effects.csv; the secondary outcomes as
`swap_effects_<outcome>`), `grid` and `grid_<workflow>` (grid.csv cells),
`grid_comparisons` (grid.csv's transition and onset differences against the
equivalence margin) and `stage_survival_<model>` (features).

`--appendix` adds, under OUT/appendix/ and stamped APPENDIX (doc 14 §9), the
half-life, chain, risk and rank-shift figures and the violations figure:
`halflife_content_vs_warning` (halflife.csv), `transitions_<cell>` (chain.csv),
`pareto_frontier` and `risk_heatmap` (risk.csv, frontier.csv; one panel per
workflow, since composites are comparable only within a workflow), `rank_shift`
(features) and `violations_by_origin_stage` (violations.csv). `--by
goal|channel|file_type` (with `--appendix`) adds a rank-shift slice named and
titled RESTRICTED. Inputs and `--out` must be under the repository's `logs/`,
which is gitignored: never commit a figure.
"""

import argparse
import csv
import math
import re
import sys
import textwrap
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from statistics import mean
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize

from eduinject import endpoints
from eduinject.analysis import CELL_FIELDS, mean_with_ci
from eduinject.behavior.ladder import ATTACK_ONLY, BEHAVIOURS, scenario
from eduinject.behavior.predictors import SERVED_FIELDS
from eduinject.behavior.propagation_model import is_on, stage_order, stages_of
from eduinject.models import load_models

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
# Okabe-Ito, the four study models' slots first: those pass dataviz's
# contrast and normal-vision checks on white, and every model also has its own
# marker (the green/pink pair alone is in the CVD band that needs one).
PALETTE = (
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#CC79A7",
    "#56B4E9",
    "#E69F00",
    "#F0E442",
    "#000000",
)
MARKERS = "os^DvPXh"
INK, MUTED, RULE = "#222222", "#666666", "#D9D9D9"
BAND = "#E3EBF3"
DONE, PERMITTED, BLOCKED = "#D55E00", "#F6CFA0", "#0072B2"
"""Headroom: warm is what the arm lets through, cool is what it removes."""
DIVERGING = LinearSegmentedColormap.from_list("bwo", ["#0072B2", "#F2F2F0", "#D55E00"])
COLUMN, PAGE = 3.5, 7.1
"""Single- and double-column widths of a paper, in inches."""
NAMES = {"pooled": "All workflows", "w1": "W1 help desk", "w2": "W2 hiring"} | {
    "w3": "W3 parent mail"
}
DERIVED = {
    "host": "model",
    "corpus_digest": "workflow",
    "tool_surface": "workflow",
    "prompts_version": "workflow",
    "reader_host": "reader_model",
}
"""Field -> the field it goes with: named in a label only where it does not."""
plt.rcParams.update(
    {
        "figure.constrained_layout.use": True,
        "font.size": 8,
        "axes.titlesize": 8,
        "axes.titlelocation": "left",
        "axes.labelsize": 8,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "legend.fontsize": 7,
        "legend.frameon": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.edgecolor": MUTED,
        "axes.axisbelow": True,
        "text.color": INK,
        "pdf.fonttype": 42,  # text stays text: Type 3 fonts are refused by venues
        "savefig.dpi": 300,
    }
)
Row = dict[str, str]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="inputs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--appendix", action="store_true")
    ap.add_argument("--by", choices=("goal", "channel", "file_type"))
    args = ap.parse_args(argv)
    if args.by and not args.appendix:
        ap.error("--by needs --appendix")
    return args


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


def one(found: list[Path], what: str) -> list[Row] | None:
    """The rows of the one file found.

    Raises:
        ValueError: More than one was found; pass `--in` narrower.
    """
    if len(found := list(dict.fromkeys(found))) > 1:
        raise ValueError(
            f"more than one {what}; narrow --in to one of: "
            + ", ".join(map(str, found))
        )
    if not found:
        return None
    print(f"{what} <- {found[0]}")
    return read(found[0])


def find(dirs: list[Path], name: str) -> list[Row] | None:
    return one([p for d in dirs for p in sorted(d.rglob(name))], name)


def find_features(dirs: list[Path]) -> list[Row] | None:
    """The one feature table under `dirs` (a CSV with `out:rank_shift`); a swap
    table holds spliced runs, which no figure over features may mix in."""
    found = []
    for d in dirs:
        for p in sorted(d.rglob("*.csv")):
            if p.name.endswith(".swap.csv"):
                continue
            with p.open(newline="", encoding="utf-8") as f:
                if "out:rank_shift" in (next(csv.reader(f), [])):
                    found.append(p)
    return one(found, "feature table")


def label(row: Row, fields: tuple[str, ...]) -> str:
    return " | ".join(row.get(f, "") for f in fields if row.get(f, ""))


def labeller(rows: list[Row], skip: tuple[str, ...] = ("model",)) -> Any:
    """Row -> label naming every CELL_FIELD that varies across `rows` (bar `skip`).

    Cells differing in any field are never pooled, so each must get its own
    label. A `DERIVED` field with one value per value of the field it goes with
    adds nothing and is left out.
    """

    def values(*fields: str) -> set[tuple[str, ...]]:
        return {tuple(r.get(f, "") for f in fields) for r in rows}

    varying = [
        f
        for f in CELL_FIELDS
        if f not in skip
        and len(values(f)) > 1
        and not (f in DERIVED and len(values(DERIVED[f], f)) == len(values(DERIVED[f])))
    ]
    return lambda r: ", ".join(f"{f}={r.get(f, '')}" for f in varying)


def conditions(rows: list[Row], skip: tuple[str, ...]) -> Any:
    """Row -> its condition: every field off doc 14's core cell, and every other
    field that varies, so a dropped field is always at its core value."""
    core = {f: "" if v is None else str(v) for f, v in endpoints.CORE.items()}
    rest = labeller(rows, (*skip, *core))

    def name(r: Row) -> str:
        off = [f"{f}={r[f]}" for f, v in core.items() if f in r and r[f] != v]
        return ", ".join([*off, *filter(None, [rest(r)])]) or "core cell"

    return name


def pts(v: float) -> str:
    """A rate difference in signed whole points."""
    text = f"{100 * v:+.0f}".replace("-", "−")
    return "0" if text in ("+0", "−0") else text


def save(fig: Any, out: Path, name: str) -> Path:
    """Write `name` (a .png) and its .pdf; stamped if `out` is the appendix."""
    path = out / name
    kw: dict[str, Any] = {}
    if out.name == "appendix":
        fig.text(1, 1.01, "APPENDIX (doc 14 §9)", ha="right", fontsize=6, color=MUTED)
        kw = {"bbox_inches": "tight"}
    fig.savefig(path, **kw)
    fig.savefig(path.with_suffix(".pdf"), metadata={"CreationDate": None}, **kw)
    plt.close(fig)
    print(f"figure -> {path} (and .pdf)")
    return path


def model_names(models: set[str]) -> dict[str, str]:
    """Model slug -> display name, in the fixed order (never by result)."""
    study = endpoints.study_models()
    known = [*study.dev, *study.held_out]
    registry = {e.model: e.name for e in load_models().values()}
    order = [m for m in known if m in models] + sorted(models - set(known))
    return {m: registry.get(m, m) for m in order}


def styles(models: set[str]) -> dict[str, tuple[str, str]]:
    """Model slug -> (colour, marker); a study model's never depends on which
    other models are in the table."""
    study = endpoints.study_models()
    known = [*study.dev, *study.held_out]
    order = known + sorted(models - set(known))
    return {m: (PALETTE[i % 8], MARKERS[i % 8]) for i, m in enumerate(order)}


def n_text(rows: Sequence[Row], column: str = "n_scenarios") -> str:
    """ "n = 22 scenarios", or the range where the rows differ."""
    ns = sorted({int(num(r.get(column))) for r in rows if r.get(column)})
    if not ns:
        return "n not recorded"
    return f"n = {'–'.join(map(str, dict.fromkeys((ns[0], ns[-1]))))} scenarios"


def points(ax: Any, label: str = "attack − twin (percentage points)") -> None:
    """x axis of a rate difference: whole points, a rule at zero."""
    ax.xaxis.set_major_formatter(lambda v, _: pts(v))
    ax.xaxis.set_major_locator(plt.MaxNLocator(7, steps=[1, 2, 5, 10]))
    ax.axvline(0, color=MUTED, lw=0.8, zorder=0)
    ax.grid(axis="x", color=RULE, lw=0.5)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel(label)


def rows_axis(ax: Any, labels: Sequence[str]) -> None:
    """Name the rows 0..n-1, first at the top."""
    ax.set_yticks(range(len(labels)), labels)
    ax.set_ylim(len(labels) - 0.5, -0.5)


def interval(
    ax: Any, r: Row, columns: tuple[str, str, str], y: float, **kw: Any
) -> bool:
    """One estimate with its interval; False (nothing drawn) if it has none."""
    v, lo, hi = (num(r.get(c)) for c in columns)
    if math.isnan(v):
        return False
    xerr = None if math.isnan(lo + hi) else [[max(v - lo, 0)], [max(hi - v, 0)]]
    base = {"mec": "w", "mew": 0.4, "elinewidth": 1, "ls": ""}
    ax.errorbar(v, y, xerr=xerr, **base | kw)
    return True


def matrix(
    cells: dict[tuple[str, str], Any], width: float, height: float
) -> tuple[Any, dict[tuple[str, str], Any]]:
    """A figure with a panel per (condition, workflow): conditions down,
    workflows across, a workflow's column kept even where a condition lacks it."""
    rows = sorted({c for c, _ in cells}, key=lambda c: (c != "core cell", c))
    workflows = sorted({w for _, w in cells})
    fig, axes = plt.subplots(
        len(rows),
        len(workflows),
        figsize=(
            min(max(width * len(workflows), COLUMN), PAGE),
            height * len(rows) + 0.7,
        ),
        sharex=True,
        sharey=True,
        squeeze=False,
    )
    panels = {}
    for i, c in enumerate(rows):
        for j, w in enumerate(workflows):
            if (c, w) in cells:
                panels[c, w] = axes[i][j]
            else:
                axes[i][j].set_visible(False)
    for j, w in enumerate(workflows):  # shared axes label only the outer panels
        column = [axes[i][j] for i, c in enumerate(rows) if (c, w) in cells]
        column[-1].tick_params(labelbottom=True)
    for i, c in enumerate(rows):
        first = next(j for j, w in enumerate(workflows) if (c, w) in cells)
        axes[i][first].tick_params(labelleft=True)
    chars = max(16, int(16 * fig.get_figwidth() / len(workflows)) - 12)
    for (c, w), ax in panels.items():
        ax.set_title(
            textwrap.fill(NAMES.get(w, w), chars)
            + (("\n" + textwrap.fill(c, chars)) if c else ""),
            fontsize=7,
        )
    return fig, panels


def model_legend(
    fig: Any, models: dict[str, str], extra: Sequence[Any] = (), title: str = ""
) -> None:
    style = styles(set(models))
    handles = [
        plt.Line2D([], [], ls="", color=style[m][0], marker=style[m][1], ms=4, label=n)
        for m, n in models.items()
    ]
    handles = [*extra, *handles]
    per_row = max(1, int(fig.get_figwidth() / 1.7))
    fig.legend(
        handles=handles,
        loc="outside lower center",
        ncols=min(len(handles), per_row),
        handletextpad=0.3,
        columnspacing=1,
        title=title,
        title_fontsize=7,
    )


def none_moved() -> Any:
    """Legend entry of the dotted bound drawn where a bootstrap interval would
    be a point: no scenario moved."""
    label = "95% bound, none moved"
    return plt.Line2D([], [], color=INK, lw=1, ls=":", label=label)


def text_handle(text: str) -> Any:
    """A legend entry that is only words."""
    return plt.Rectangle((0, 0), 1, 1, fill=False, ec="none", label=text)


def pool_note(rows: Sequence[Row]) -> list[Any]:
    """Names any dev model a pooled row lacks: it is then not the declared pool."""
    lost = {m for r in rows for m in (r.get("models_missing") or "").split(";") if m}
    names = ", ".join(model_names(lost).values())
    return [text_handle(f"pooled without {names}")] if lost else []


def headroom(rows: list[Row], out: Path) -> Path:
    """Per workflow and arm, one bar as long as the reference ceiling, split
    into observed harm, harm permitted but not done, and harm the arm blocks;
    each model's own observed harm is a hollow mark under the bar."""
    groups = by_workflow(rows)
    arms = {}
    for wf, rs in groups.items():
        keys = list(dict.fromkeys((r["reference"], r["arm"]) for r in rs))
        refs = list(dict.fromkeys(ref for ref, _ in keys))
        arms[wf] = sorted(keys, key=lambda k: (refs.index(k[0]), k[0] != k[1]))
    models = model_names({r["model"] for r in rows if r["model"] != endpoints.POOLED})
    marker = {m: s[1] for m, s in styles(set(models)).items()}
    heights = [len(a) + 1.2 for a in arms.values()]
    fig, axes = plt.subplots(
        len(groups),
        1,
        figsize=(COLUMN, 0.29 * sum(heights) + 1.6),
        height_ratios=heights,
        sharex=True,
        squeeze=False,
    )
    extent = [
        v
        for r in rows
        for c in ("ceiling_u", "ceiling", "observed", "observed_lo", "observed_hi")
        + (("zero_upper",) if r["model"] == endpoints.POOLED else ())
        if not math.isnan(v := num(r.get(c)))
        and (r["model"] == endpoints.POOLED or not c.startswith("observed_"))
    ]
    for ax, (wf, rs) in zip(axes[:, 0], groups.items(), strict=True):
        own = [r for r in rs if r["model"] == endpoints.POOLED]
        if len({(r["reference"], r["arm"]) for r in own}) != len(own):
            raise ValueError(f"two pooled headroom rows share an arm of {wf}")
        pooled = {(r["reference"], r["arm"]): r for r in own}
        labels = []
        for y, key in enumerate(arms[wf]):
            labels.append(key[1] + (" (ref.)" if key[0] == key[1] else ""))
            if key not in pooled:
                ax.text(0, y, " no pooled estimate", va="center", fontsize=6)
                continue
            r = pooled[key]
            o, c, u = (num(r[k]) for k in ("observed", "ceiling", "ceiling_u"))
            done = 0.0 if math.isnan(o) else max(o, 0.0)
            for lo, hi, colour in (
                (c, u, BLOCKED),
                (min(done, c), c, RULE if math.isnan(o) else PERMITTED),
                (0, done, DONE),
            ):
                if hi > lo:
                    ax.barh(y, hi - lo, 0.5, lo, color=colour, ec="w", lw=0.8)
            if not interval(
                ax, r, ("observed", "observed_lo", "observed_hi"), y,
                color="k", marker="", capsize=2,
            ):  # fmt: skip
                ax.text(0, y, " not estimable", va="center", fontsize=6)
            if r.get("zero_upper"):  # none seen: the interval alone would be a point
                ax.plot([0, num(r["zero_upper"])], [y, y], color="k", lw=1, ls=":")
            for m in models:
                for x in rs:
                    if x["model"] == m and (x["reference"], x["arm"]) == key:
                        ax.plot(
                            num(x["observed"]), y + 0.38, marker=marker[m],
                            ms=2.8, mfc="w", mec=INK, mew=0.6,
                        )  # fmt: skip
            bound = r.get("bound_ok") == "False"
            values = (o, num(r["behavioural"]), num(r["structural"]))
            for k, v in enumerate(values):
                ax.annotate(
                    "–" if math.isnan(v) else pts(v).lstrip("+") + "!" * (bound and not k),
                    (1, y), (14 + 20 * k, 0), ("axes fraction", "data"), "offset points",
                    ha="center", va="center", fontsize=7, annotation_clip=False,
                )  # fmt: skip
            if y and arms[wf][y - 1][0] != key[0]:
                ax.axhline(y - 0.45, color=RULE, lw=0.8)
        for k, colour in enumerate((DONE, PERMITTED, BLOCKED)):
            ax.annotate(
                "■", (1, 1), (14 + 20 * k, 3), "axes fraction", "offset points",
                color=colour, ha="center", fontsize=8,
            )  # fmt: skip
        rows_axis(ax, labels)
        ax.set_ylim(len(labels) - 0.4, -0.6)
        ax.set_title(f"{NAMES.get(wf, wf)} ({n_text(own)})", fontsize=7)
        ax.set_xlim(min([0, *extent]) - 0.02, 1.02 * max([0.05, *extent]))
        ax.xaxis.set_major_formatter(lambda v, _: f"{100 * v:.0f}")
        ax.grid(axis="x", color=RULE, lw=0.5)
        ax.tick_params(axis="y", length=0)
    axes[-1, 0].set_xlabel("completed harm (% of attack documents)")
    parts = [
        plt.Rectangle((0, 0), 1, 1, color=c, label=t)
        for c, t in (
            (DONE, "observed (attack − twin, 95% interval)"),
            (PERMITTED, "behavioural: permitted, not done"),
            (BLOCKED, "structural: blocked by the arm"),
        )
    ]
    if any(r.get("zero_upper") for r in rows if r["model"] == endpoints.POOLED):
        parts.append(none_moved())
    if any(r.get("bound_ok") == "False" for r in rows):
        parts.append(text_handle("! observed interval lies above the arm's ceiling"))
    parts += pool_note(rows)
    marks = [
        plt.Line2D([], [], ls="", marker=marker[m], ms=3.5, mfc="w", mec=INK, label=n)
        for m, n in models.items()
    ]
    fig.legend(handles=parts, loc="outside upper left", ncols=1)
    fig.legend(
        handles=marks, loc="outside lower center", ncols=2,
        title="observed, per model", title_fontsize=7, handletextpad=0.2,
    )  # fmt: skip
    return save(fig, out, "headroom.png")


def ladder(rows: list[Row], out: Path) -> Path:
    """One panel per cell, one point per model as served, per behaviour:
    attack − twin, or the attack rate where a twin cannot show it (hollow)."""
    condition = conditions(rows, (*SERVED_FIELDS, "workflow"))
    served = {
        (r["model"], r.get("host", ""), r.get("reasoning_effort", "")) for r in rows
    }
    many = {m for m, *_ in served if sum(m == s[0] for s in served) > 1}

    def series(r: Row) -> str:
        extra = f" ({r.get('host', '')}, {r.get('reasoning_effort', '')})"
        return r["model"] + (extra if r["model"] in many else "")

    names = model_names({series(r) for r in rows})
    style = styles(set(names))
    cells: dict[tuple[str, str], dict[tuple[str, str], Row]] = defaultdict(dict)
    for r in rows:
        panel = cells[condition(r), r.get("workflow", "")]
        key = (series(r), r["behaviour"])
        if key in panel:
            raise ValueError(f"two rows share a ladder point: {key}")
        panel[key] = r
    shown = [b for b in BEHAVIOURS if b not in ATTACK_ONLY]
    shown += [b for b in BEHAVIOURS if b in ATTACK_ONLY]
    shown = [b for b in shown if any(r["behaviour"] == b for r in rows)]
    labels = [b.replace("_", " ") + ("*" if b in ATTACK_ONLY else "") for b in shown]
    fig, panels = matrix(cells, 2.4, 0.26 * len(shown) + 0.5)
    step = 0.7 / max(len(names), 1)
    for key, ax in panels.items():
        for j, s in enumerate(names):
            for i, b in enumerate(shown):
                if (s, b) not in cells[key]:
                    continue
                r = cells[key][s, b]
                y = i + (j - (len(names) - 1) / 2) * step
                colour, marker = style[s]
                alone = b in ATTACK_ONLY
                columns = ("attack_rate" if alone else "difference", "lo", "hi")
                interval(
                    ax, r, columns, y, color=colour, marker=marker, ms=3.5,
                    **({"mfc": "w", "mec": colour, "mew": 0.8} if alone else {}),
                )  # fmt: skip
        own = list(cells[key].values())
        ax.set_title(f"{ax.get_title(loc='left')}\n{n_text(own)}", fontsize=7)
        rows_axis(ax, labels)
        split = sum(b not in ATTACK_ONLY for b in shown)
        if 0 < split < len(shown):
            ax.axhline(split - 0.5, color=MUTED, lw=0.6)
        points(ax, "")
    model_legend(
        fig,
        names,
        title="attack − twin (percentage points, 95% interval); "
        + ("\n" if fig.get_figwidth() < PAGE else "")
        + "* attack rate (%), not defined on a twin",
    )
    return save(fig, out, "ladder.png")


def swap_effects(rows: list[Row], out: Path) -> list[Path]:
    """One panel per workflow and one pooled, per outcome: each effect's pooled
    estimate (black) above every model's own."""
    effects = {
        "te": "total (TE)",
        "de": "direct (DE)",
        "le": "laundered (LE)",
        "interaction": "interaction",
    }
    paths = []
    for outcome in dict.fromkeys(r["outcome"] for r in rows):
        mine = [r for r in rows if r["outcome"] == outcome]
        models = model_names({r["model"] for r in mine} - {endpoints.POOLED})
        style = styles(set(models)) | {endpoints.POOLED: ("k", "*")}
        groups = by_workflow(mine)
        order = sorted(groups, key=lambda w: (w != endpoints.ALL, w))
        fig, axes = plt.subplots(
            len(order), 1, figsize=(COLUMN, 1.75 * len(order) + 0.7),
            sharex=True, squeeze=False,
        )  # fmt: skip
        series = [endpoints.POOLED, *models]
        step = 0.78 / len(series)
        for ax, wf in zip(axes[:, 0], order, strict=True):
            at = {(r["effect"], r["model"]): r for r in groups[wf]}
            if len(at) != len(groups[wf]):
                raise ValueError(f"two swap rows share an effect and model of {wf}")
            for i, e in enumerate(effects):
                for j, m in enumerate(series):
                    if (r := at.get((e, m))) is None:
                        continue
                    y = i + (j - (len(series) - 1) / 2) * step
                    colour, marker = style[m]
                    big = m == endpoints.POOLED
                    drawn = interval(
                        ax, r, ("estimate", "lo", "hi"), y, color=colour,
                        marker=marker, ms=8 if big else 3.5,
                        elinewidth=1.6 if big else 0.9,
                    )  # fmt: skip
                    if r.get("zero_upper"):
                        # None moved: each scenario's value is in [-1, 1]
                        # (an interaction's in [-2, 2]).
                        z = num(r["zero_upper"]) * (2 if e == "interaction" else 1)
                        ax.plot([-z, z], [y, y], color=colour, lw=0.9, ls=":")
                    if big:
                        ax.text(
                            1.02, y, pts(num(r["estimate"]))
                            if drawn else "–",
                            transform=ax.get_yaxis_transform(), va="center",
                            fontsize=7,
                        )  # fmt: skip
            rows_axis(ax, list(effects.values()))
            pooled = [r for r in groups[wf] if r["model"] == endpoints.POOLED]
            ax.set_title(f"{NAMES.get(wf, wf)} ({n_text(pooled)})")
            points(ax, "")
        points(
            axes[-1, 0],
            f"effect on {outcome.split(':')[-1]} (percentage points, 95% interval)",
        )
        extra = [
            plt.Line2D(
                [], [], ls="", color="k", marker="*", ms=8, label="dev models pooled"
            )
        ]
        if any(r.get("zero_upper") for r in mine):
            extra.append(none_moved())
        extra += pool_note(mine)
        model_legend(fig, models, extra)
        name = outcome.split(":")[-1]
        primary = outcome == endpoints.ATTEMPT
        paths.append(
            save(
                fig,
                out,
                "swap_effects.png" if primary else f"swap_effects_{slug(name)}.png",
            )
        )
    return paths


def grid(rows: list[Row], out: Path) -> list[Path]:
    """Reader × actor heatmap of the conditional attempt excess A, with A, T and
    the relayed attack runs behind them printed; one figure per workflow."""
    paths = []
    for wf, mine in by_workflow([r for r in rows if r["kind"] == "cell"]).items():
        at = {(r["reader"], r["actor"]): r for r in mine}
        if len(at) != len(mine):
            raise ValueError(f"two grid cells share a square of {wf}")
        names = model_names({m for k in at for m in k})
        order = list(names)
        held = set(endpoints.study_models().held_out)
        shown = [names[m] + ("\n(held out)" if m in held else "") for m in order]
        values = [
            [
                num(r["attempt_excess"])
                if (r := at.get((i, j))) and r["attempt_estimable"] == "True"
                else math.nan
                for j in order
            ]
            for i in order
        ]
        top = max([0.1, *(abs(v) for row in values for v in row if not math.isnan(v))])
        fig, ax = plt.subplots(figsize=(COLUMN, 0.5 * len(order) + 1.5))
        im = ax.imshow(values, cmap=DIVERGING, norm=Normalize(-top, top), aspect="auto")
        for y, i in enumerate(order):
            for x, j in enumerate(order):
                r = at.get((i, j))
                if r is None:
                    text, colour = "not run", MUTED
                else:
                    parts = [
                        f"{k} {pts(num(r[f'{t}_excess']))}"
                        if r[f"{t}_estimable"] == "True"
                        else f"{k} n/e"
                        for k, t in (("A", "attempt"), ("T", "adopt"))
                    ]
                    text = "\n".join([*parts, f"n={r['n_relayed']}"])
                    colour = INK
                ax.text(
                    x, y, text, ha="center", va="center", fontsize=6.5, color=colour
                )
        # White gaps between squares.
        for k in range(len(order) - 1):
            ax.axhline(k + 0.5, color="w", lw=1.5)
            ax.axvline(k + 0.5, color="w", lw=1.5)
        ax.spines[:].set_visible(False)
        ax.tick_params(length=0)
        ax.set_xticks(range(len(order)), shown, rotation=30, ha="right")
        ax.set_yticks(range(len(order)), shown)
        ax.set(xlabel="actor (action stage)", ylabel="reader (earlier stages)")
        fig.suptitle(
            f"{NAMES.get(wf, wf)} ({n_text(mine, 'attempt_scenarios')})\n"
            "A attempt, T adopt: attack − twin given relay (points)\n"
            "n: relayed attack runs; n/e: not estimable",
            x=0.01, ha="left", fontsize=7,
        )  # fmt: skip
        bar = fig.colorbar(im, ax=ax, label="A (points)", shrink=0.8, aspect=30)
        bar.ax.yaxis.set_major_formatter(lambda v, _: pts(v))
        bar.ax.tick_params(labelsize=6)
        bar.outline.set_visible(False)
        paths.append(
            save(
                fig, out, "grid.png" if wf == endpoints.ALL else f"grid_{slug(wf)}.png"
            )
        )
    return paths


def grid_comparisons(rows: list[Row], out: Path) -> Path:
    """The declared actor-pair (T, A) and reader-pair (onset) differences behind
    H-main, against the ±δ margin of doc 14 §5."""
    tested = [r for r in rows if r.get("in_test") == "True" and r["kind"] != "cell"]
    names = model_names(
        {
            r[c]
            for r in tested
            for c in ("reader", "actor", "actor_b", "reader_b")
            if r.get(c)
        }
    )
    cells = [
        r
        for r in rows
        if r["kind"] == "cell"
        and r["workflow"] == endpoints.ALL
        and r["in_test"] == "True"
    ]
    parts = [
        (
            "T: adopt given relay",
            [r for r in tested if r.get("component") == "adopt"],
            "adopt_scenarios",
        ),
        (
            "A: attempt given relay",
            [r for r in tested if r.get("component") == "attempt"],
            "attempt_scenarios",
        ),
        (
            "Onset: relay",
            [r for r in tested if r["kind"] == "onset"],
            "",
        ),
    ]
    # A reader's comparisons sit under its name; onset's are the readers'.
    lines: list[list[Row | str]] = []
    for _, rs, _ in parts:
        own: list[Row | str] = []
        for reader in names:
            group = [r for r in rs if r["reader"] == reader]
            if group and group[0]["kind"] != "onset":
                own.append(reader)
            own += group
        lines.append(own)
    heights = [len(own) + 1.5 for own in lines]
    fig, axes = plt.subplots(
        3,
        1,
        figsize=(COLUMN, 0.17 * sum(heights) + 1.2),
        height_ratios=heights,
        sharex=True,
    )
    for ax, (title, rs, column), own in zip(axes, parts, lines, strict=True):
        ax.axvspan(-endpoints.MARGIN, endpoints.MARGIN, color=BAND, zorder=0)
        labels = []
        for y, r in enumerate(own):
            if isinstance(r, str):
                labels.append(f"reader {names[r]}")
                continue
            pair = (
                ("reader", "reader_b") if r["kind"] == "onset" else ("actor", "actor_b")
            )
            labels.append(" − ".join(names[r[c]] for c in pair))
            if r.get("verdict") == "not_estimable" or not interval(
                ax, r, ("diff", "lo_sim", "hi_sim"), y, color=INK, marker="", elinewidth=0.8
            ):  # fmt: skip
                ax.text(0, y, "not estimable", ha="center", va="center", fontsize=6)
                continue
            interval(
                ax, r, ("diff", "lo90", "hi90"), y, color=PALETTE[0], marker="o", ms=3.5,
                elinewidth=2,
            )  # fmt: skip
        rows_axis(ax, labels)
        for text, r in zip(ax.get_yticklabels(), own, strict=True):
            text.set(fontsize=6, fontweight="bold" if isinstance(r, str) else "normal")
        points(ax, "")
        ax.set_title(
            f"{title}\n{n_text(cells, column) if column else n_text(rs)}", fontsize=7
        )
    points(
        axes[-1], f"difference (percentage points; δ = {100 * endpoints.MARGIN:.0f})"
    )
    fig.legend(
        handles=[
            plt.Line2D(
                [],
                [],
                color=PALETTE[0],
                lw=2,
                marker="o",
                ms=3.5,
                label="90% (equivalence)",
            ),
            plt.Line2D([], [], color=INK, lw=0.8, label="95%, family-adjusted"),
            plt.Rectangle(
                (0, 0),
                1,
                1,
                color=BAND,
                label="±δ",
            ),
        ],
        loc="outside lower center",
        ncols=3,
        columnspacing=1,
    )
    return save(fig, out, "grid_comparisons.png")


def err(rows: list[Row], value: str, lo: str, hi: str) -> list[list[float]]:
    """Asymmetric error-bar half-widths, zero where the CI is missing."""
    low, high = [], []
    for r in rows:
        v, a, b = num(r.get(value)), num(r.get(lo)), num(r.get(hi))
        low.append(max(v - a, 0.0) if not math.isnan(a + v) else 0.0)
        high.append(max(b - v, 0.0) if not math.isnan(b + v) else 0.0)
    return [low, high]


def stage_survival(feats: list[Row], out: Path) -> list[Path]:
    """Per model, one panel per cell over every stage the runs had (relays too):
    the share of attack runs carrying the marker, over the runs that had that
    stage, pairs averaged within a scenario and scenarios equally weighted, with
    a scenario-bootstrap interval."""
    attacks = [
        r for r in feats if r.get("label") == "attack" and r.get("status") == "ok"
    ]
    condition = conditions(attacks, ("model", "workflow"))
    by_model: dict[str, dict[tuple[str, str], list[Row]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in attacks:
        by_model[r["model"]][condition(r), r.get("workflow", "")].append(r)
    paths = []
    for model, name in model_names(set(by_model)).items():
        cells = by_model[model]
        stages = sorted(
            {s for rows in cells.values() for r in rows for s in stages_of(r)},
            key=stage_order,
        )
        fig, panels = matrix(cells, 2.4, 1.8)
        for key, ax in panels.items():
            xs, rates = [], []
            for x, s in enumerate(stages):
                pairs: dict[tuple[Any, str], list[bool]] = defaultdict(list)
                for r in cells[key]:
                    if v := r.get(f"carry:{s}"):
                        pairs[scenario(r), r.get("artifact_id", "")].append(is_on(v))
                values: dict[Any, list[float]] = defaultdict(list)
                for (sc, _), ys in pairs.items():
                    values[sc].append(mean(ys))
                ci = mean_with_ci({sc: mean(v) for sc, v in values.items()})
                if ci:
                    xs.append(x)
                    rates.append(ci)
            ax.errorbar(
                xs,
                [c.diff for c in rates],
                yerr=[[c.diff - c.lo for c in rates], [c.hi - c.diff for c in rates]],
                color=PALETTE[0], marker="o", ms=4, lw=1.5, elinewidth=1, capsize=2,
            )  # fmt: skip
            for x, c in (
                z for i, z in enumerate(zip(xs, rates)) if i in (0, len(xs) - 1)
            ):
                ax.annotate(
                    f"{100 * c.diff:.0f}", (x, c.diff), xytext=(5, 3),
                    textcoords="offset points", fontsize=6.5,
                )  # fmt: skip
            n = len({scenario(r) for r in cells[key]})
            ax.set_title(
                f"{ax.get_title(loc='left')}\nn = {n} scenarios, {len(cells[key])} runs",
                fontsize=7,
            )
            ax.set_xticks(range(len(stages)), stages, rotation=30, ha="right")
            ax.set_xlim(-0.3, len(stages) - 0.5)
            ax.set_ylim(-0.02, 1.08)
            ax.yaxis.set_major_formatter(lambda v, _: f"{100 * v:.0f}")
            ax.grid(axis="y", color=RULE, lw=0.5)
        fig.supylabel("attack runs carrying the marker (%)", fontsize=8)
        fig.suptitle(f"{name}: stage survival, 95% interval", fontsize=8)
        paths.append(save(fig, out, f"stage_survival_{slug(model)}.png"))
    return paths


def halflife(rows: list[Row], out: Path) -> Path:
    name = labeller(rows, ())
    cells = sorted({name(r) for r in rows})
    fams = sorted({r["family"] for r in rows}, key=lambda f: (f != "warning", f))
    fig, ax = plt.subplots(figsize=(PAGE, 0.5 * len(cells) + 1.2))
    w = 0.8 / max(len(fams), 1)
    for j, fam in enumerate(fams):
        mine = {name(r): r for r in rows if r["family"] == fam}
        if len(mine) != sum(r["family"] == fam for r in rows):
            raise ValueError(f"two cells share a half-life label: {fam}")
        sel = [mine[c] for c in cells if c in mine]
        ys = [cells.index(name(r)) + (j - (len(fams) - 1) / 2) * w for r in sel]
        ax.barh(
            ys,
            [num(r["half_life"]) for r in sel],
            w,
            xerr=err(sel, "half_life", "lo", "hi"),
            capsize=2,
            color=PALETTE[j % 8],
            label=fam,
        )
    rows_axis(ax, [textwrap.fill(c, 60) for c in cells])
    ax.set(xlabel="half-life (stages)", title="Content vs warning half-life")
    fig.legend(loc="outside lower center", ncols=len(fams))
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
    models = model_names({r["model"] for r in risk})
    style = styles(set(models))
    fig, axes = plt.subplots(
        1, len(groups), figsize=(max(PAGE, 3 * len(groups)), 3.6), squeeze=False
    )
    for ax, (wf, rows) in zip(axes[0], groups.items(), strict=True):
        rows = [r for r in rows if not math.isnan(num(r["risk"]) + num(r["utility"]))]
        for r in rows:
            k = label(r, CELL_FIELDS)
            ax.errorbar(
                num(r["utility"]),
                num(r["risk"]),
                yerr=err([r], "risk", "risk_lo", "risk_hi"),
                fmt="D" if optimal.get(k) else "o",
                color=style[r["model"]][0],
                mfc="none" if not optimal.get(k) else None,
                capsize=2,
            )
        ax.set(
            xlabel="twin utility (higher is better)",
            ylabel="severity-weighted risk (lower is better)",
            title=f"{wf}: diamonds are Pareto-optimal",
        )
    marks = [
        plt.Line2D([], [], marker="o", ls="", color=style[m][0], label=n)
        for m, n in models.items()
    ]
    fig.legend(handles=marks, loc="outside lower center", ncols=len(marks))
    return save(fig, out, "pareto_frontier.png")


def heatmap(risk: list[Row], out: Path) -> Path:
    groups = by_workflow(risk)
    fig, axes = plt.subplots(
        1, len(groups), figsize=(max(PAGE, 4 * len(groups)), 4.5), squeeze=False
    )
    for ax, (wf, rows) in zip(axes[0], groups.items(), strict=True):
        arm = conditions(rows, ("model", "workflow"))
        acc: dict[tuple[str, str], float] = {}
        for r in rows:
            v = num(r["risk"])
            if math.isnan(v):
                continue
            key = (r["model"], arm(r))
            if key in acc:
                raise ValueError(f"two cells map to one heatmap square: {key}")
            acc[key] = v
        models = model_names({m for m, _ in acc})
        top = max(acc.values(), default=0.0)
        cols = sorted({c for _, c in acc})
        grid = [[acc.get((m, c), math.nan) for c in cols] for m in models]
        im = ax.imshow(grid, cmap="cividis_r")
        ax.set_xticks(range(len(cols)), cols, rotation=40, ha="right", fontsize=7)
        ax.set_yticks(range(len(models)), models.values(), fontsize=8)
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
                        color="w" if v > 0.55 * top else "k",
                    )
        ax.set(xlabel="condition", ylabel="model", title=f"Risk: {wf}")
        fig.colorbar(im, ax=ax, label="severity-weighted risk", shrink=0.4)
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
    fig, ax = plt.subplots(figsize=(PAGE, 0.35 * len(groups) + 1.2))
    if groups:
        names = sorted(groups)
        ax.boxplot(
            [groups[n] for n in names],
            positions=range(len(names)),
            orientation="horizontal",
        )
        rows_axis(ax, [textwrap.fill(n, 60) for n in names])
    ax.set(xlabel="rank shift of the attacker's candidate (positions)", ylabel="cell")
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
        if rows := need("headroom", find(dirs, "headroom.csv")):
            headroom(rows, out)
        if rows := need("ladder", find(dirs, "ladder.csv")):
            ladder(rows, out)
        if rows := need("swap_effects", find(dirs, "swap_effects.csv")):
            swap_effects(rows, out)
        if rows := need("grid, grid_comparisons", find(dirs, "grid.csv")):
            grid(rows, out)
            grid_comparisons(rows, out)
        feats = need("stage_survival, rank_shift", find_features(dirs))
        if feats:
            stage_survival(feats, out)
        if args.appendix:
            appendix(dirs, feats, out / "appendix", args.by, need)
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    return 0


def appendix(
    dirs: list[Path], feats: list[Row] | None, out: Path, by: str | None, need: Any
) -> None:
    """The figures doc 14 §9 moved out of the primary set."""
    out.mkdir(exist_ok=True)
    if feats:
        rank_shift(feats, out, None)
        if by:
            rank_shift(feats, out, by)
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


if __name__ == "__main__":
    sys.exit(main())
