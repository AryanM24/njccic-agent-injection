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
import random
from collections import defaultdict
from datetime import datetime
from typing import Any

from inspect_ai.log import read_eval_log

from eduinject.analysis import rate_with_ci

HARM = ["exfiltration", "authorization", "scope_violation"]
BREAKDOWN_METRICS = [
    "propagation.intake",
    "propagation.analysis",
    "propagation.action",
    "suppression.surfaced_attack",
    "exfiltration",
    "authorization",
]


def short(model: str) -> str:
    return "Luna" if "luna" in model else "DeepSeek"


def kind(row: dict[str, str]) -> str:
    if row["controls"] == "True":
        return "controls"
    return "baseline" if row["benign_only"] == "True" else "attack"


def f3(x: Any) -> str:
    return "" if x in ("", None) else f"{float(x):.3f}"


def rate_cell(r: dict[str, str] | None) -> str:
    if not r:
        return "–"
    return (
        f"{f3(r['rate'])} [{f3(r['ci_lo'])}, {f3(r['ci_hi'])}] r{f3(r['epoch_range'])}"
    )


def read(path: str) -> list[dict[str, str]]:
    with open(path) as f:
        return list(csv.DictReader(f))


def load_rows(path: str) -> list[dict[str, Any]]:
    rows = []
    for r in read(path):
        row: dict[str, Any] = dict(r)
        for k, v in r.items():
            if k.startswith("score:"):
                if v == "":
                    del row[k]
                else:
                    row[k] = float(v)
        rows.append(row)
    return rows


def boot_diff(
    a: list[dict[str, Any]], b: list[dict[str, Any]], metric: str
) -> tuple[float, float, float] | None:
    """Difference of two independent pair-clustered rates, with a 95% interval."""

    def pairs(rows: list[dict[str, Any]]) -> list[tuple[float, int]]:
        acc: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            if row["status"] == "scored" and f"score:{metric}" in row:
                acc[row["artifact_id"]].append(row[f"score:{metric}"])
        return [(sum(v), len(v)) for v in acc.values()]

    pa, pb = pairs(a), pairs(b)
    if not pa or not pb:
        return None

    def mean(p: list[tuple[float, int]]) -> float:
        return sum(s for s, _ in p) / sum(n for _, n in p)

    rng = random.Random(0)
    draws = sorted(
        mean(rng.choices(pa, k=len(pa))) - mean(rng.choices(pb, k=len(pb)))
        for _ in range(2000)
    )
    return mean(pa) - mean(pb), draws[50], draws[1949]


def section_denominators(dirs: list[str]) -> None:
    print("### Denominators (every cell)\n")
    print(
        "| Model | Kind | WF | Cells | Runs | Scored | Error | Limit | No tool calls |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    agg: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0] * 6)
    for d in dirs:
        for r in read(os.path.join(d, "denominators.csv")):
            k = (short(r["model"]), kind(r), r["workflow"])
            v = agg[k]
            v[0] += 1
            for i, f in enumerate(
                ["total", "scored", "error", "limit", "no_tool_calls"], 1
            ):
                v[i] += int(r[f] or 0)
    for k in sorted(agg):
        print(f"| {' | '.join(k)} | {' | '.join(map(str, agg[k]))} |")
    print()


def section_rates(rates: list[dict[str, str]]) -> None:
    print("### Every rate, every cell\n")
    print("Format: rate [95% pair-clustered CI] r<epoch range>. 48 pairs × 10 epochs")
    print("= 480 runs per attack cell; baseline cells as in §0.\n")
    idx = {}
    for r in rates:
        idx[
            (
                r["metric"],
                short(r["model"]),
                kind(r),
                r["workflow"],
                r["scope"],
                r["isolated"],
            )
        ] = r
    for metric in sorted({r["metric"] for r in rates}):
        print(f"#### `{metric}`\n")
        print(
            "| Model | WF | Scope | Attack, iso off | Attack, iso on | Baseline, iso off | Baseline, iso on |"
        )
        print("| --- | --- | --- | --- | --- | --- | --- |")
        for model in ("Luna", "DeepSeek"):
            for wf in ("w1", "w2", "w3"):
                for scope in ("read_only", "standard", "read_write"):
                    cells = [
                        idx.get((metric, model, k, wf, scope, iso))
                        for k in ("attack", "baseline")
                        for iso in ("False", "True")
                    ]
                    if any(cells):
                        print(
                            f"| {model} | {wf} | {scope} | "
                            + " | ".join(map(rate_cell, cells))
                            + " |"
                        )
        print()


def section_attack_vs_baseline(
    rows: list[dict[str, Any]], rates: list[dict[str, str]]
) -> None:
    print(
        "### Attack − baseline (independent bootstrap; floor = largest baseline epoch range for model × WF × metric)\n"
    )
    floors: dict[tuple[str, str, str], float] = defaultdict(float)
    for r in rates:
        if kind(r) == "baseline" and r["epoch_range"]:
            k = (short(r["model"]), r["workflow"], r["metric"])
            floors[k] = max(floors[k], float(r["epoch_range"]))
    cells: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        cells[
            (
                short(row["model"]),
                kind(row),
                row["workflow"],
                row["scope"],
                row["isolated"],
            )
        ].append(row)
    print(
        "| Model | WF | Scope | Iso | Metric | Attack | Baseline | Diff [95% CI] | Floor | Verdict |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for model in ("Luna", "DeepSeek"):
        for wf in ("w1", "w2", "w3"):
            for scope in ("read_only", "standard", "read_write"):
                for iso in ("False", "True"):
                    a = cells.get((model, "attack", wf, scope, iso), [])
                    b = cells.get((model, "baseline", wf, scope, iso), [])
                    for metric in HARM + ["control_check.legit_task_completed"]:
                        res = boot_diff(a, b, metric)
                        if res is None:
                            continue
                        ra, rb = rate_with_ci(a, metric), rate_with_ci(b, metric)
                        if ra is None or rb is None or (ra.rate == 0 and rb.rate == 0):
                            continue
                        floor = floors.get((model, wf, metric), 0.0)
                        diff, lo, hi = res
                        excl0 = lo > 0 or hi < 0
                        verdict = "effect" if abs(diff) > floor and excl0 else "null"
                        print(
                            f"| {model} | {wf} | {scope} | {'on' if iso == 'True' else 'off'} | {metric} | "
                            f"{ra.rate:.3f} | {rb.rate:.3f} | {diff:+.3f} [{lo:+.3f}, {hi:+.3f}] | {floor:.3f} | {verdict} |"
                        )
    print()
    print(
        "Task completion under attack vs baseline is a usefulness cost, not a harm; listed for completeness.\n"
    )


def section_comparisons(dirs: list[str]) -> None:
    print("### Isolation and scope contrasts (from `comparisons.csv`; non-zero only)\n")
    print(
        "| Model | Kind | Contrast | WF | Scope / Iso | a − b | Metric | Diff [95% CI] | Floor (range) | Null? |"
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
                f"| {short(r['model'])} | {kind(r)} | {r['contrast']} | {r['workflow']} | {fixed} | "
                f"{r['a']} − {r['b']} | {r['metric']} | {float(r['diff_a_minus_b']):+.3f} "
                f"[{float(r['ci_lo']):+.3f}, {float(r['ci_hi']):+.3f}] | {f3(r['floor_range'])} | {r['null_if_floor_range']} |"
            )
    print()


def section_breakdowns(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    attack = [r for r in rows if kind(r) == "attack"]
    for field in fields:
        print(f"### Attack runs by `{field}`\n")
        print(
            "Propagation and surfacing pooled over the three scopes (scope has no effect on"
        )
        print("them); exfiltration and authorization at read_write only.\n")
        print(f"| Model | WF | {field} | Metric | Iso off | Iso on |")
        print("| --- | --- | --- | --- | --- | --- |")
        groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for r in attack:
            groups[
                (short(r["model"]), r["workflow"], r[field], r["isolated"], r["scope"])
            ].append(r)
        values = sorted({r[field] for r in attack})
        for model in ("Luna", "DeepSeek"):
            for wf in ("w1", "w2", "w3"):
                for v in values:
                    for metric in BREAKDOWN_METRICS:
                        scopes = (
                            ["read_write"]
                            if metric in HARM
                            else ["read_only", "standard", "read_write"]
                        )
                        out = []
                        for iso in ("False", "True"):
                            sel = [
                                x
                                for s in scopes
                                for x in groups.get((model, wf, v, iso, s), [])
                            ]
                            ci = rate_with_ci(sel, metric) if sel else None
                            out.append(
                                f"{ci.rate:.3f} [{ci.lo:.2f}, {ci.hi:.2f}] n{ci.n_runs}"
                                if ci
                                else "–"
                            )
                        if out != ["–", "–"]:
                            print(
                                f"| {model} | {wf} | {v} | {metric} | {out[0]} | {out[1]} |"
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
    rows = [r for d in args.analysis for r in load_rows(os.path.join(d, "rows.csv"))]
    if args.restricted:
        section_breakdowns(rows, ("channel", "file_type", "goal"))
        return
    section_denominators(args.analysis)
    section_usage(args.logs)
    section_rates(rates)
    section_attack_vs_baseline(rows, rates)
    section_comparisons(args.analysis)
    section_breakdowns(rows, ("base_id",))


if __name__ == "__main__":
    main()
