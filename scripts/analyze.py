#!/usr/bin/env python3
"""Analyze finished sweeps: the tables, comparisons and human-check sheets.

    analyze.py report LOG_DIR... [--out DIR]
        rows.csv          one row per (sample, epoch), with status and scores
        denominators.csv  scored / error / limit counts per cell (doc 04 §13.5)
        rates.csv         per cell and metric: rate, pair-clustered 95% CI,
                          saturation flag, epoch SD and range (noise floor)
        rates_by_base.csv the same per base scenario (D16)
        comparisons.csv   isolation, scope and model contrasts, paired by
                          document, with the null rule under both candidate
                          noise floors (doc 09 §4, pending sign-off)
        report.md         a readable summary of the above

    analyze.py sample-human LOG_DIR... [--fraction 0.10] [--out DIR]
        coding_sheet.csv  stratified sample with blank coding columns
        answer_key.csv    the automated scores for the same runs (keep it away
                          from the coders until both have finished)

    analyze.py kappa CODER_A.csv CODER_B.csv [--key answer_key.csv]
        Cohen's kappa per coded column, coder vs coder and coder vs automated.

Outputs default to logs/analysis/, which is gitignored: analysis of canonical
runs is Tier 1, like the logs it is computed from. Nothing here contacts a model.
"""

import argparse
import csv
import sys
from collections.abc import Sequence
from itertools import combinations
from pathlib import Path
from typing import Any

from eduinject.analysis import (
    CELL_FIELDS,
    REPORTABILITY,
    cohen_kappa,
    denominators,
    epoch_spread,
    group,
    is_null,
    load_rows,
    metrics_in,
    paired_difference,
    rate_with_ci,
    saturated,
    stratified_sample,
    tool_use_check,
)

SCOPE_ORDER = ("read_only", "standard", "read_write")
FLOOR_FIELDS = ("model", "host", "reasoning_effort", "workflow", "scope", "isolated")
"""A benign-only cell supplies the floor for every cell matching it on these."""

CODED = ("exfiltration", "scope_violation", "authorization", "action_divergence")
"""Binary outcomes the human coders score independently (doc 09 §6)."""


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    """Write dict rows with the union of their keys as the header."""
    fields: list[str] = []
    for row in rows:
        fields.extend(k for k in row if k not in fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def cell_dict(key: tuple[Any, ...], extra: Sequence[str] = ()) -> dict[str, Any]:
    return dict(zip((*CELL_FIELDS, *extra), key, strict=True))


def reportability(metric: str) -> str:
    return REPORTABILITY.get(metric.split(".")[0], "unclassified")


def floors(rows: list[dict[str, Any]]) -> dict[tuple[Any, ...], dict[str, Any]]:
    """Noise floors from benign-only (non-control) cells, keyed for matching."""
    found: dict[tuple[Any, ...], dict[str, Any]] = {}
    for key, cell_rows in group(r for r in rows if r["benign_only"]).items():
        cell = cell_dict(key)
        if cell["controls"]:
            continue
        match = tuple(cell[f] for f in FLOOR_FIELDS)
        for metric in metrics_in(cell_rows):
            spread = epoch_spread(cell_rows, metric)
            if spread:
                found[(*match, metric)] = {"sd": spread.sd, "range": spread.range}
    return found


def floor_for(
    cells: Sequence[dict[str, Any]], metric: str, table: dict[tuple[Any, ...], Any]
) -> dict[str, float] | None:
    """The larger floor of the cells being compared, or None if either lacks one."""
    found = [table.get((*(c[f] for f in FLOOR_FIELDS), metric)) for c in cells]
    present = [f for f in found if f is not None]
    if len(present) < len(found):
        return None
    return {s: max(f[s] for f in present) for s in ("sd", "range")}


def rate_rows(
    rows: list[dict[str, Any]], extra: Sequence[str], n_boot: int
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, cell_rows in sorted(group(rows, extra).items(), key=str):
        for metric in metrics_in(cell_rows):
            ci = rate_with_ci(cell_rows, metric, n_boot=n_boot)
            if ci is None:
                continue
            spread = epoch_spread(cell_rows, metric)
            out.append(
                {
                    **cell_dict(key, extra),
                    "metric": metric,
                    "n_pairs": ci.n_pairs,
                    "n_runs": ci.n_runs,
                    "rate": round(ci.rate, 4),
                    "ci_lo": round(ci.lo, 4),
                    "ci_hi": round(ci.hi, 4),
                    "saturated": saturated(ci),
                    "epoch_sd": round(spread.sd, 4) if spread else "",
                    "epoch_range": round(spread.range, 4) if spread else "",
                    "reportability": reportability(metric),
                }
            )
    return out


def contrasts(
    cells: dict[tuple[Any, ...], list[dict[str, Any]]],
) -> list[tuple[str, tuple[Any, ...], tuple[Any, ...]]]:
    """(kind, cell A, cell B) for every isolation, scope and model contrast.

    A is isolated=True for isolation and the narrower scope for scope.
    """

    def without(key: tuple[Any, ...], fields: Sequence[str]) -> tuple[Any, ...]:
        cell = cell_dict(key)
        return tuple(v for f, v in cell.items() if f not in fields)

    out: list[tuple[str, tuple[Any, ...], tuple[Any, ...]]] = []
    for kind, fields in (
        ("isolation", ("isolated",)),
        ("scope", ("scope",)),
        ("model", ("model", "host", "reasoning_effort")),
    ):
        buckets: dict[tuple[Any, ...], list[tuple[Any, ...]]] = {}
        for key in cells:
            buckets.setdefault(without(key, fields), []).append(key)
        for keys in buckets.values():
            # A is the more defended cell, so a negative diff means it helped.
            if kind == "scope":
                keys.sort(key=lambda k: SCOPE_ORDER.index(cell_dict(k)["scope"]))
            elif kind == "isolation":
                keys.sort(key=lambda k: not cell_dict(k)["isolated"])
            else:
                keys.sort(key=str)
            out.extend((kind, a, b) for a, b in combinations(keys, 2))
    return out


def comparison_rows(rows: list[dict[str, Any]], n_boot: int) -> list[dict[str, Any]]:
    cells = group(rows)
    floor_table = floors(rows)
    out: list[dict[str, Any]] = []
    for kind, key_a, key_b in contrasts(cells):
        a, b = cell_dict(key_a), cell_dict(key_b)
        varied = [f for f in CELL_FIELDS if a[f] != b[f]]
        shared = {f: a[f] for f in CELL_FIELDS if f not in varied}
        for metric in sorted(
            set(metrics_in(cells[key_a])) & set(metrics_in(cells[key_b]))
        ):
            diff = paired_difference(cells[key_a], cells[key_b], metric, n_boot=n_boot)
            if diff is None:
                continue
            floor = floor_for((a, b), metric, floor_table)
            out.append(
                {
                    "contrast": kind,
                    **shared,
                    "a": " / ".join(f"{f}={a[f]}" for f in varied),
                    "b": " / ".join(f"{f}={b[f]}" for f in varied),
                    "metric": metric,
                    "n_pairs": diff.n_pairs,
                    "diff_a_minus_b": round(diff.diff, 4),
                    "ci_lo": round(diff.lo, 4),
                    "ci_hi": round(diff.hi, 4),
                    "floor_sd": round(floor["sd"], 4) if floor else "",
                    "floor_range": round(floor["range"], 4) if floor else "",
                    "null_if_floor_sd": is_null(diff, floor["sd"] if floor else None),
                    "null_if_floor_range": is_null(
                        diff, floor["range"] if floor else None
                    ),
                    "reportability": reportability(metric),
                }
            )
    return out


def report_md(
    rows: list[dict[str, Any]], dropped: int, rates: list[dict[str, Any]]
) -> str:
    lines = [
        "# Sweep analysis",
        "",
        "Procedure: `docs/design/09_analysis_plan.md` (draft until signed).",
        "Every rate below is a lower bound; see `reportability` for what each",
        "metric may be used for. Saturated cells (rate 0 or 1) are reported but",
        "excluded from comparative claims (doc 04 §14).",
        "",
        f"Runs loaded: {len(rows)} ({dropped} duplicate rows from retried logs dropped).",
        "",
        "## Denominators (doc 04 §13.5)",
        "",
        "| " + " | ".join(CELL_FIELDS) + " | total | scored | error | limit |",
        "|" + " --- |" * (len(CELL_FIELDS) + 4),
    ]
    for key, cell_rows in sorted(group(rows).items(), key=str):
        d = denominators(cell_rows)
        cells = [str(v) for v in key]
        counts = [str(d[k]) for k in ("total", "scored", "error", "limit")]
        lines.append("| " + " | ".join(cells + counts) + " |")
    silent = [
        (key, tool_use_check(cell_rows))
        for key, cell_rows in sorted(group(rows).items(), key=str)
    ]
    silent = [(key, t) for key, t in silent if t["no_tool_calls"]]
    lines += ["", "## Tool-use check", ""]
    if not silent:
        lines.append("Every scored run made at least one tool call.")
    for key, t in silent:
        lines.append(
            f"**WARNING** {t['no_tool_calls']} of {t['scored_with_ledger']} scored runs "
            f"in `{' / '.join(str(v) for v in key)}` made no tool call at all. The "
            "model may not be issuing tool calls on this route; these runs are "
            "untested, not safe (RUNNING.md step 4, check 2)."
        )
    lines += [
        "",
        "## Rates (pair-clustered 95% CI)",
        "",
        "| workflow | scope | isolated | benign_only | model | metric | rate | CI | sat. |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rates:
        lines.append(
            f"| {r['workflow']} | {r['scope']} | {r['isolated']} | {r['benign_only']}"
            f" | {r['model']} | {r['metric']} | {r['rate']}"
            f" | [{r['ci_lo']}, {r['ci_hi']}] | {'yes' if r['saturated'] else ''} |"
        )
    return "\n".join(lines) + "\n"


def cmd_report(args: argparse.Namespace) -> int:
    rows, dropped = load_rows(args.log_dirs)
    if not rows:
        print(f"no eduinject logs under {args.log_dirs}", file=sys.stderr)
        return 1
    out = Path(args.out)
    rates = rate_rows(rows, (), args.n_boot)
    write_csv(out / "rows.csv", rows)
    write_csv(
        out / "denominators.csv",
        [
            {**cell_dict(key), **denominators(cell_rows), **tool_use_check(cell_rows)}
            for key, cell_rows in sorted(group(rows).items(), key=str)
        ],
    )
    write_csv(out / "rates.csv", rates)
    write_csv(out / "rates_by_base.csv", rate_rows(rows, ("base_id",), args.n_boot))
    write_csv(out / "comparisons.csv", comparison_rows(rows, args.n_boot))
    (out / "report.md").write_text(report_md(rows, dropped, rates), encoding="utf-8")
    print(f"{len(rows)} runs ({dropped} duplicates dropped) -> {out.resolve()}")
    return 0


def cmd_sample_human(args: argparse.Namespace) -> int:
    rows, _ = load_rows(args.log_dirs)
    chosen = stratified_sample(rows, args.fraction, args.seed)
    if not chosen:
        print("no scored runs to sample", file=sys.stderr)
        return 1
    ids = ("log", "sample_id", "epoch", *CELL_FIELDS, "artifact_id", "goal", "channel")
    sheet = [
        {**{f: r.get(f) for f in ids}, **{f"code:{c}": "" for c in CODED}}
        for r in chosen
    ]
    key = [
        {
            **{f: r.get(f) for f in ids},
            **{f"code:{c}": r.get(f"score:{c}", "") for c in CODED},
        }
        for r in chosen
    ]
    out = Path(args.out)
    write_csv(out / "coding_sheet.csv", sheet)
    write_csv(out / "answer_key.csv", key)
    print(f"{len(chosen)} runs sampled -> {out.resolve()}")
    return 0


NA = ("", "n/a", "na")


def read_codes(path: str) -> dict[tuple[str, str, str], dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return {(r["log"], r["sample_id"], r["epoch"]): r for r in csv.DictReader(f)}


def _norm(value: str) -> str:
    """Treat 1, 1.0 and '1' alike, so coder sheets compare with the key."""
    try:
        return str(float(value))
    except ValueError:
        return value.strip().lower()


def cmd_kappa(args: argparse.Namespace) -> int:
    sheets = {"A": read_codes(args.coder_a), "B": read_codes(args.coder_b)}
    if args.key:
        sheets["auto"] = read_codes(args.key)
    runs = sorted(set.intersection(*(set(s) for s in sheets.values())))
    if not runs:
        print("the sheets share no runs", file=sys.stderr)
        return 1
    print(f"{len(runs)} runs coded by every party")
    for column in (f"code:{c}" for c in CODED):
        # A metric that does not apply to a run (authorization outside W1) is
        # blank in the key; coders may write "n/a" there. Score only the rest.
        applies = [
            r
            for r in runs
            if _norm(sheets["auto" if args.key else "A"][r].get(column, "")) not in NA
        ]
        for x, y in combinations(sheets, 2):
            a = [_norm(sheets[x][r].get(column, "")) for r in applies]
            b = [_norm(sheets[y][r].get(column, "")) for r in applies]
            if not applies or any(v in NA for v in a + b):
                print(f"  {column} {x}-{y}: incomplete, skipped")
                continue
            agree = sum(u == v for u, v in zip(a, b, strict=True)) / len(a)
            print(
                f"  {column} {x}-{y}: kappa = {cohen_kappa(a, b):.3f} "
                f"(n={len(a)}, raw agreement {agree:.3f}, "
                f"positives {a.count('1.0')}/{b.count('1.0')})"
            )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    report = sub.add_parser("report", help="tables, comparisons and summary")
    report.add_argument("log_dirs", nargs="+")
    report.add_argument("--out", default="logs/analysis")
    report.add_argument("--n-boot", type=int, default=1000)
    report.set_defaults(func=cmd_report)

    human = sub.add_parser("sample-human", help="stratified human-coding sample")
    human.add_argument("log_dirs", nargs="+")
    human.add_argument("--fraction", type=float, default=0.10)
    human.add_argument("--seed", type=int, default=0)
    human.add_argument("--out", default="logs/analysis/human")
    human.set_defaults(func=cmd_sample_human)

    kappa = sub.add_parser("kappa", help="inter-coder agreement")
    kappa.add_argument("coder_a")
    kappa.add_argument("coder_b")
    kappa.add_argument("--key", default=None, help="answer_key.csv (automated)")
    kappa.set_defaults(func=cmd_kappa)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
