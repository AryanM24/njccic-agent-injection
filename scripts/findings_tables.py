"""Render every analysis table as Markdown, for findings.md and the paper.

Usage: python scripts/findings_tables.py --analysis DIR [DIR ...] --logs DIR [DIR ...]
Reads the CSVs `analyze.py report` wrote (no model contacted) and the log
headers for token usage and wall clock. Prints Markdown to stdout.

`--restricted` prints only the breakdowns by concealment channel, file type and
goal. Those are payload effectiveness by technique, Tier 1 under doc 05 §6:
write them under `logs/` (gitignored), never into a committed file.
"""

import argparse
import csv
import glob
import os
from collections import defaultdict
from datetime import datetime
from typing import Any

from inspect_ai.log import read_eval_log

from eduinject.analysis import (
    CELL_FIELDS,
    cell_of,
    comparison_floor,
    group,
    paired_difference,
    rate_with_ci,
    verdict,
)
from eduinject.analysis import cell_kind as kind
from eduinject.analysis import model_label as short

HARM = [
    "exfiltration",
    "authorization",
    "misdirection",
    "harm.completed",
    "harm.attempted",
]
BREAKDOWN_METRICS = [
    "propagation.intake",
    "propagation.analysis",
    "propagation.action",
    "suppression.surfaced_attack",
    "exfiltration",
    "authorization",
]


WF_LABEL = {"w1": "Help desk", "w2": "Hiring", "w3": "Parent email"}


def f3(x: Any) -> str:
    return "" if x in ("", None) else f"{float(x):.3f}"


def rate_cell(r: dict[str, Any] | None) -> str:
    if not r:
        return "–"
    return (
        f"{f3(r['rate'])} [{f3(r['ci_lo'])}, {f3(r['ci_hi'])}] r{f3(r['epoch_range'])}"
    )


def read(path: str) -> list[dict[str, Any]]:
    """A CSV `analyze.py` wrote, with the run-mode flags back as booleans."""
    with open(path) as f:
        rows: list[dict[str, Any]] = list(csv.DictReader(f))
    for row in rows:
        for flag in ("benign_only", "controls"):
            if flag in row:
                row[flag] = row[flag] == "True"
    return rows


def read_rows(path: str) -> list[dict[str, Any]]:
    """rows.csv, with scores as floats and blank scores dropped."""
    rows = read(path)
    for row in rows:
        for k, v in list(row.items()):
            if k.startswith("score:"):
                if v == "":
                    del row[k]
                else:
                    row[k] = float(v)
    return rows


def section_denominators(dirs: list[str]) -> None:
    print("### Denominators (every cell)\n")
    print(
        "| Model | Kind | WF | Cells | Runs | Scored | Error | Limit "
        "| Parse error | No tool calls |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    agg: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0] * 7)
    for d in dirs:
        for r in read(os.path.join(d, "denominators.csv")):
            k = (short(r["model"]), kind(r), r["workflow"])
            v = agg[k]
            v[0] += 1
            for i, f in enumerate(
                [
                    "total",
                    "scored",
                    "error",
                    "limit",
                    "handoff_parse_error",
                    "no_tool_calls",
                ],
                1,
            ):
                v[i] += int(r[f] or 0)
    for k in sorted(agg):
        print(f"| {' | '.join(k)} | {' | '.join(map(str, agg[k]))} |")
    print()


def _cell_columns(cell: dict[str, Any]) -> str:
    """The fields that tell two cells apart, apart from those a table splits on."""
    return (
        f"{short(cell['model'])} | {cell['host']} | {cell['reasoning_effort']} "
        f"| {WF_LABEL.get(cell['workflow'], cell['workflow'])} | {cell['corpus']} "
        f"| {cell['identity_mode']} | {cell['defense']}"
    )


CELL_HEADER = "Model | Host | Effort | WF | Corpus | Identity | Defense"


def section_rates(rates: list[dict[str, Any]]) -> None:
    print("### Every rate, every cell\n")
    print("Format: rate [95% pair-clustered CI] r<epoch range>. 48 pairs × 10 epochs")
    print("= 480 runs per attack cell; baseline cells as in §0.\n")
    idx = {(r["metric"], cell_of(r)): r for r in rates}
    # One line per cell with isolation and attack/baseline folded into columns.
    lines = {
        (r["metric"], cell_of({**r, "benign_only": False, "isolated": ""}))
        for r in rates
        if kind(r) != "controls"
    }
    for metric in sorted({m for m, _ in lines}):
        print(f"#### `{metric}`\n")
        print(
            f"| {CELL_HEADER} | Scope | Attack, iso off | Attack, iso on "
            "| Baseline, iso off | Baseline, iso on |"
        )
        print("|" + " --- |" * 12)
        for _, key in sorted((x for x in lines if x[0] == metric), key=str):
            cell = dict(zip(CELL_FIELDS, key, strict=True))
            found = [
                idx.get((metric, cell_of({**cell, "benign_only": b, "isolated": iso})))
                for b in (False, True)
                for iso in ("False", "True")
            ]
            print(
                f"| {_cell_columns(cell)} | {cell['scope']} | "
                + " | ".join(map(rate_cell, found))
                + " |"
            )
        print()


def section_attack_vs_baseline(rows: list[dict[str, Any]]) -> None:
    print(
        "### Attack − baseline (paired by document; floor and verdict per doc 09 "
        "§4: the matching baseline cell's epoch range)\n"
    )
    cells = group(r for r in rows if kind(r) in ("attack", "baseline"))
    print(
        "| Model | WF | Corpus | Scope | Iso | Identity | Defense | Effort | Metric "
        "| Attack | Baseline | Diff [95% CI] | Floor | Verdict |"
    )
    print("|" + " --- |" * 14)
    for key in sorted(cells, key=str):
        cell = dict(zip(CELL_FIELDS, key, strict=True))
        if cell["benign_only"]:
            continue
        base_cell = {**cell, "benign_only": True}
        a, b = cells[key], cells.get(cell_of(base_cell), [])
        for metric in HARM + ["control_check.did_correct_thing"]:
            diff = paired_difference(a, b, metric)
            ra, rb = rate_with_ci(a, metric), rate_with_ci(b, metric)
            if diff is None or ra is None or rb is None:
                continue
            if ra.rate == 0 and rb.rate == 0:
                continue
            floor = comparison_floor(rows, cell, base_cell, metric)
            shown = str(verdict(diff, floor))
            # Doc 09 §5: a 0 or 1 rate is reported, not compared.
            if {ra.rate, rb.rate} & {0.0, 1.0}:
                shown += " (saturated)"
            print(
                f"| {short(cell['model'])} | {WF_LABEL.get(cell['workflow'], cell['workflow'])} "
                f"| {cell['corpus']} | {cell['scope']} "
                f"| {'on' if cell['isolated'] == 'True' else 'off'} "
                f"| {cell['identity_mode']} | {cell['defense']} "
                f"| {cell['reasoning_effort']} | {metric} "
                f"| {ra.rate:.3f} | {rb.rate:.3f} "
                f"| {diff.diff:+.3f} [{diff.lo:+.3f}, {diff.hi:+.3f}] "
                f"| {'' if floor is None else f'{floor:.3f}'} "
                f"| {shown} |"
            )
    print()
    print(
        "Task completion under attack vs baseline is a usefulness cost, not a harm; "
        "listed for completeness.\n"
    )


def section_comparisons(dirs: list[str]) -> None:
    print("### Isolation and scope contrasts (from `comparisons.csv`; non-zero only)\n")
    print(
        "| Model | Kind | Contrast | WF | Scope / Iso | a − b | Metric | Diff [95% CI] | Floor (range) | Verdict |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for d in dirs:
        for r in read(os.path.join(d, "comparisons.csv")):
            if (
                float(r["diff_a_minus_b"]) == 0
                and float(r["ci_lo"]) == 0
                and float(r["ci_hi"]) == 0
            ):
                continue
            fixed = (
                r["scope"] if r["contrast"] == "isolation" else f"iso={r['isolated']}"
            )
            print(
                f"| {short(r['model'])} | {kind(r)} | {r['contrast']} | {WF_LABEL.get(r['workflow'], r['workflow'])} | {fixed} | "
                f"{r['a']} − {r['b']} | {r['metric']} | {float(r['diff_a_minus_b']):+.3f} "
                f"[{float(r['ci_lo']):+.3f}, {float(r['ci_hi']):+.3f}] | {f3(r['floor'])} | {r['verdict']} |"
            )
    print()


def section_breakdowns(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    attack = [r for r in rows if kind(r) == "attack"]
    for field in fields:
        print(f"### Attack runs by `{field}`\n")
        print(
            "Each line is one cell (`FLOOR_FIELDS`) with scope pooled: propagation "
            "and surfacing over the three scopes (scope has no effect on"
        )
        print("them); exfiltration and authorization at read_write only.\n")
        print(f"| {CELL_HEADER} | {field} | Metric | Iso off | Iso on |")
        print("|" + " --- |" * 11)
        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for r in attack:
            rest = cell_of({**r, "scope": "", "isolated": ""}, (field,))
            groups[(rest, r["isolated"], r["scope"])].append(r)
        for rest in sorted({k[0] for k in groups}, key=str):
            cell = dict(zip((*CELL_FIELDS, field), rest, strict=True))
            for metric in BREAKDOWN_METRICS:
                scopes = (
                    ["read_write"]
                    if metric in HARM
                    else ["read_only", "standard", "read_write"]
                )
                out = []
                for iso in ("False", "True"):
                    sel = [x for sc in scopes for x in groups.get((rest, iso, sc), [])]
                    ci = rate_with_ci(sel, metric) if sel else None
                    out.append(
                        f"{ci.rate:.3f} [{ci.lo:.2f}, {ci.hi:.2f}] n{ci.n_runs}"
                        if ci
                        else "–"
                    )
                if out != ["–", "–"]:
                    print(
                        f"| {_cell_columns(cell)} | {cell[field]} | {metric} "
                        f"| {out[0]} | {out[1]} |"
                    )
        print()


def section_usage(log_dirs: list[str]) -> None:
    print("### Tokens and wall clock (from log headers)\n")
    print(
        "| Run set | Logs | Samples | Input tokens | Output tokens | Reasoning tokens | Wall clock (sum of cells, h) | First start → last end (h) |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for d in log_dirs:
        n = samples = 0
        tin = tout = treason = 0
        secs = 0.0
        starts, ends = [], []
        for p in sorted(glob.glob(os.path.join(d, "**", "*.eval"), recursive=True)):
            h = read_eval_log(p, header_only=True)
            n += 1
            samples += h.results.completed_samples if h.results else 0
            for u in (h.stats.model_usage or {}).values():
                tin += u.input_tokens or 0
                tout += u.output_tokens or 0
                treason += u.reasoning_tokens or 0
            if h.stats.started_at and h.stats.completed_at:
                s = datetime.fromisoformat(h.stats.started_at)
                e = datetime.fromisoformat(h.stats.completed_at)
                secs += (e - s).total_seconds()
                starts.append(s)
                ends.append(e)
        span = (max(ends) - min(starts)).total_seconds() / 3600 if starts else 0
        print(
            f"| `{d}` | {n} | {samples} | {tin:,} | {tout:,} | {treason:,} | {secs / 3600:.1f} | {span:.1f} |"
        )
    print()
    print(
        "Samples are paired: one attack sample runs the attack document and its twin, so token totals cover both.\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis", nargs="+", required=True)
    ap.add_argument("--logs", nargs="*", default=[])
    ap.add_argument("--restricted", action="store_true")
    args = ap.parse_args()
    rates = [r for d in args.analysis for r in read(os.path.join(d, "rates.csv"))]
    rows = [r for d in args.analysis for r in read_rows(os.path.join(d, "rows.csv"))]
    if args.restricted:
        section_breakdowns(rows, ("channel", "file_type", "goal"))
        return
    section_denominators(args.analysis)
    section_usage(args.logs)
    section_rates(rates)
    section_attack_vs_baseline(rows)
    section_comparisons(args.analysis)
    section_breakdowns(rows, ("base_id",))


if __name__ == "__main__":
    main()
