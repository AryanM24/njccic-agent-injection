#!/usr/bin/env python3
"""Analyze finished sweeps: the tables, comparisons and human-check sheets.

    analyze.py report LOG_DIR... [--out DIR]
        rows.csv          one row per (sample, epoch), with status and scores
        denominators.csv  scored / error / limit counts per cell (doc 04 §13.5)
        rates.csv         per cell and metric: rate, pair-clustered 95% CI,
                          saturation flag, epoch SD and range (noise floor)
        rates_by_base.csv the same per base scenario (D16)
        comparisons.csv   isolation, scope, identity, defense and model
                          contrasts, paired by document: the null rule under
                          both noise floors (doc 09 §4), a sign-flip
                          permutation p, Holm over the primary family, the
                          MDE, and with --gee a pair-clustered GEE (doc 10 §5)
        interaction.csv   H2: isolation's effect with facts minus without
        in_pair.csv       attack − twin harm and utility within each pair,
                          per attack cell (doc 10 §5)
        concentration.csv harm positives per distinct pair
        conditional.csv   P(harm | marker reached analysis / action)
        report.md         a readable summary of the above

    analyze.py sample-human LOG_DIR... [--fraction 0.10] [--out DIR]
        coding_sheet.csv  stratified sample with blank coding columns
        answer_key.csv    the automated scores for the same runs (keep it away
                          from the coders until both have finished)

    analyze.py kappa CODER_A.csv CODER_B.csv [--key answer_key.csv]
        Cohen's kappa per coded column, coder vs coder and coder vs automated.

    analyze.py export-pairs LOG_DIR... --salt SECRET [--out FILE]
        Pair-level aggregates for reproducing the analyses (doc 10, plan WS12):
        per cell, pair and metric, the run count and mean. Pair ids are salted
        hashes and the technique columns (goal, channel, file type) are dropped,
        so the file cannot rank attack techniques. Releasing it is still a doc
        05 decision.

Outputs default to logs/analysis/, which is gitignored: analysis of canonical
runs is Tier 1, like the logs it is computed from. Nothing here contacts a model.
"""

import argparse
import csv
import random
import sys
from collections.abc import Sequence
from itertools import combinations
from pathlib import Path
from typing import Any

from eduinject import stats
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
    within_pair_difference,
    within_pair_differences,
)

SCOPE_ORDER = ("read_only", "standard", "read_write")
FLOOR_FIELDS = (
    "model",
    "host",
    "reasoning_effort",
    "workflow",
    "scope",
    "isolated",
    "identity_mode",
    "defense",
)
"""A benign-only cell supplies the floor for every cell matching it on these."""

IDENTITY_ORDER = ("guard", "facts", "off")
DEFENSE_ORDER = ("spotlight", "none")
"""Most defended first, so A − B < 0 means the defense helped."""

PRIMARY_METRICS = ("exfiltration", "authorization", "propagation.action")
PRIMARY_CONTRASTS = ("isolation", "scope", "identity", "defense")
"""The pre-declared primary family (doc 09 §5, extended by doc 10 §5). Holm's
correction runs over it within each model and workflow; every other row is
exploratory and labelled so."""

HARM_METRICS = ("exfiltration", "authorization", "scope_violation")
CONDITIONS = ("propagation.analysis", "propagation.action")

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
                    # A zero is "below this", not proof of absence (doc 10 §5).
                    "upper95_if_zero": (
                        round(stats.zero_upper_bound(ci.n_pairs), 4)
                        if ci.rate == 0
                        else ""
                    ),
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
        ("identity", ("identity_mode",)),
        ("defense", ("defense",)),
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
            elif kind == "identity":
                keys.sort(
                    key=lambda k: IDENTITY_ORDER.index(cell_dict(k)["identity_mode"])
                )
            elif kind == "defense":
                keys.sort(key=lambda k: DEFENSE_ORDER.index(cell_dict(k)["defense"]))
            else:
                keys.sort(key=str)
            out.extend((kind, a, b) for a, b in combinations(keys, 2))
    return out


def comparison_rows(
    rows: list[dict[str, Any]], n_boot: int, gee: bool = False
) -> list[dict[str, Any]]:
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
            diffs = stats.paired_differences(cells[key_a], cells[key_b], metric)
            minimum = stats.mde(diffs)
            fit = (
                stats.gee_contrast(cells[key_a], cells[key_b], metric) if gee else None
            )
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
                    "p_sign_flip": round(stats.sign_flip_test(diffs), 4),
                    "mde_80": round(minimum, 4) if minimum is not None else "",
                    "gee_log_odds": round(fit.log_odds, 4) if fit else "",
                    "gee_p": round(fit.p, 4) if fit else "",
                    "primary": is_primary(kind, metric, shared),
                    "reportability": reportability(metric),
                }
            )
    add_holm(out)
    return out


def is_primary(kind: str, metric: str, cell: dict[str, Any]) -> bool:
    """Whether a contrast is in the pre-declared primary family (doc 10 §5).

    Harm contrasts count on attack cells only: on twin baselines they are
    floor checks (about 0, p = 1) and would only inflate Holm's m. H4, the
    utility cost of a defense, is the one primary contrast on twin baselines.
    """
    if cell.get("controls"):
        return False
    if cell.get("benign_only"):
        return kind in ("identity", "defense") and metric == UTILITY_METRIC
    return kind in PRIMARY_CONTRASTS and metric in PRIMARY_METRICS


UTILITY_METRIC = "control_check.did_correct_thing"
"""H4's metric: benign utility, on twin baselines."""

FAMILY_FIELDS = ("model", "host", "reasoning_effort", "workflow", "benign_only")
"""A Holm family: one model as served (host, effort), one workflow, and attack
cells apart from twin baselines."""


def add_holm(comparisons: list[dict[str, Any]]) -> None:
    """Holm-adjust the primary rows' sign-flip p-values within each family."""
    families: dict[tuple[Any, ...], dict[int, float]] = {}
    for i, row in enumerate(comparisons):
        if row["primary"]:
            family = tuple(row.get(f) for f in FAMILY_FIELDS)
            families.setdefault(family, {})[i] = row["p_sign_flip"]
    for members in families.values():
        adjusted = stats.holm({str(i): p for i, p in members.items()})
        for i in members:
            comparisons[i]["p_holm"] = round(adjusted[str(i)], 4)


def interaction_rows(rows: list[dict[str, Any]], n_boot: int) -> list[dict[str, Any]]:
    """H2 (doc 10 §5): does isolation's effect on harm change once verified
    facts are restored?

    Per pair, (isolated − not, with facts) − (isolated − not, without facts),
    over pairs present in all four cells; bootstrap over pairs, sign-flip p,
    Holm within each family. A non-zero value means part of what isolation did
    in the first edition was the facts it withheld.
    """
    cells = group(rows)
    by_rest: dict[tuple[Any, ...], dict[tuple[bool, str], list[dict[str, Any]]]] = {}
    for key, cell_rows in cells.items():
        cell = cell_dict(key)
        if cell["benign_only"] or cell["identity_mode"] not in ("off", "facts"):
            continue
        rest = tuple(
            v for f, v in cell.items() if f not in ("isolated", "identity_mode")
        )
        by_rest.setdefault(rest, {})[(cell["isolated"], cell["identity_mode"])] = (
            cell_rows
        )
    out: list[dict[str, Any]] = []
    rest_fields = [f for f in CELL_FIELDS if f not in ("isolated", "identity_mode")]
    for rest, quad in sorted(by_rest.items(), key=str):
        if len(quad) < 4:
            continue
        for metric in PRIMARY_METRICS:
            means = {k: stats.per_pair_means(v, metric) for k, v in quad.items()}
            pairs = sorted(set.intersection(*(set(m) for m in means.values())), key=str)
            if not pairs:
                continue
            dd = {
                p: (means[(True, "facts")][p] - means[(False, "facts")][p])
                - (means[(True, "off")][p] - means[(False, "off")][p])
                for p in pairs
            }
            rng = random.Random(0)
            draws = sorted(
                sum(dd[k] for k in chosen) / len(chosen)
                for chosen in (rng.choices(pairs, k=len(pairs)) for _ in range(n_boot))
            )
            values = list(dd.values())
            out.append(
                {
                    **dict(zip(rest_fields, rest, strict=True)),
                    "metric": metric,
                    "n_pairs": len(pairs),
                    "interaction": round(sum(values) / len(values), 4),
                    "ci_lo": round(draws[int(0.025 * (n_boot - 1))], 4),
                    "ci_hi": round(draws[int(0.975 * (n_boot - 1))], 4),
                    "p_sign_flip": round(stats.sign_flip_test(values), 4),
                    "primary": True,
                }
            )
    add_holm(out)
    return out


IN_PAIR = (
    ("harm", "paired_utility.harm_attack", "paired_utility.harm_twin"),
    ("utility", "paired_utility.utility_attack", "paired_utility.utility_twin"),
)
"""(name, attack metric, twin metric): the in-pair attack effect (doc 10 §5)."""


def in_pair_rows(rows: list[dict[str, Any]], n_boot: int) -> list[dict[str, Any]]:
    """Attack − twin within each pair, per attack cell: what the injection did,
    with the twin run of the same sample as the control."""
    out: list[dict[str, Any]] = []
    for key, cell_rows in sorted(group(rows).items(), key=str):
        if cell_dict(key)["benign_only"]:
            continue
        for name, a, b in IN_PAIR:
            diff = within_pair_difference(cell_rows, a, b, n_boot=n_boot)
            if diff is None:
                continue
            diffs = list(within_pair_differences(cell_rows, a, b).values())
            minimum = stats.mde(diffs)
            out.append(
                {
                    **cell_dict(key),
                    "outcome": name,
                    "n_pairs": diff.n_pairs,
                    "attack_minus_twin": round(diff.diff, 4),
                    "ci_lo": round(diff.lo, 4),
                    "ci_hi": round(diff.hi, 4),
                    "p_sign_flip": round(stats.sign_flip_test(diffs), 4),
                    "mde_80": round(minimum, 4) if minimum is not None else "",
                }
            )
    return out


def concentration_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per cell and harm metric: how many distinct pairs carry the positives."""
    out: list[dict[str, Any]] = []
    for key, cell_rows in sorted(group(rows).items(), key=str):
        for metric in HARM_METRICS:
            c = stats.pair_concentration(cell_rows, metric)
            if c.positive_runs:
                out.append(
                    {
                        **cell_dict(key),
                        "metric": metric,
                        "positive_runs": c.positive_runs,
                        "pairs": c.pairs,
                        "pairs_with_any": c.pairs_with_any,
                        "top_pair_share": round(c.top_pair_share, 4),
                    }
                )
    return out


def conditional_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """P(harm | the marker reached a later stage), per attack cell."""
    out: list[dict[str, Any]] = []
    for key, cell_rows in sorted(group(rows).items(), key=str):
        if cell_dict(key)["benign_only"]:
            continue
        for harm in HARM_METRICS:
            for given in CONDITIONS:
                c = stats.conditional_rate(cell_rows, harm, given)
                if c.n_given:
                    out.append(
                        {
                            **cell_dict(key),
                            "outcome": harm,
                            "given": given,
                            "n_given": c.n_given,
                            "rate": round(c.rate or 0.0, 4),
                        }
                    )
        # Exploratory (doc 10 §9): influence that got past the verbatim channel.
        if cell_dict(key)["isolated"]:
            c = stats.conditional_rate(
                cell_rows, "action_divergence", "propagation.analysis", when=False
            )
            if c.n_given:
                out.append(
                    {
                        **cell_dict(key),
                        "outcome": "action_divergence (laundering candidate)",
                        "given": "NOT propagation.analysis",
                        "n_given": c.n_given,
                        "rate": round(c.rate or 0.0, 4),
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
    write_csv(out / "comparisons.csv", comparison_rows(rows, args.n_boot, args.gee))
    write_csv(out / "in_pair.csv", in_pair_rows(rows, args.n_boot))
    write_csv(out / "interaction.csv", interaction_rows(rows, args.n_boot))
    write_csv(out / "concentration.csv", concentration_rows(rows))
    write_csv(out / "conditional.csv", conditional_rows(rows))
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


TECHNIQUE_FIELDS = ("goal", "channel", "file_type", "concealment")
"""Columns that would rank attack techniques (doc 05 §6, Tier 1): never exported."""


def pair_export_rows(rows: list[dict[str, Any]], salt: str) -> list[dict[str, Any]]:
    """Per cell × pseudonymous pair × metric: runs and mean. No text, no ids."""
    import hashlib

    if not salt:
        raise ValueError("a non-empty --salt is required (keep it private)")
    out: list[dict[str, Any]] = []
    for key, cell_rows in sorted(
        group(rows, ("base_id", "artifact_id")).items(), key=str
    ):
        cell = cell_dict(key, ("base_id", "artifact_id"))
        artifact = str(cell.pop("artifact_id"))
        pair = hashlib.sha256(f"{salt}:{artifact}".encode()).hexdigest()[:12]
        for metric in metrics_in(cell_rows):
            values = [
                float(r[f"score:{metric}"])
                for r in cell_rows
                if r["status"] == "scored" and f"score:{metric}" in r
            ]
            if values:
                out.append(
                    {
                        **cell,
                        "pair": pair,
                        "metric": metric,
                        "n_runs": len(values),
                        "mean": round(sum(values) / len(values), 4),
                    }
                )
    assert not any(f in row for row in out for f in TECHNIQUE_FIELDS)
    return out


def cmd_export_pairs(args: argparse.Namespace) -> int:
    rows, _ = load_rows(args.log_dirs)
    out = pair_export_rows(rows, args.salt)
    write_csv(Path(args.out), out)
    print(f"{len(out)} pair-level rows -> {Path(args.out).resolve()}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    report = sub.add_parser("report", help="tables, comparisons and summary")
    report.add_argument("log_dirs", nargs="+")
    report.add_argument("--out", default="logs/analysis")
    report.add_argument(
        "--n-boot",
        type=int,
        default=1000,
        help="Bootstrap resamples (doc 09 §3: 1,000; doc 10 §5 proposes 10,000).",
    )
    report.add_argument(
        "--gee",
        action="store_true",
        help="Add the pair-clustered GEE sensitivity analysis (needs the "
        "`stats` extra: statsmodels).",
    )
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

    export = sub.add_parser("export-pairs", help="pseudonymized pair-level aggregates")
    export.add_argument("log_dirs", nargs="+")
    export.add_argument("--salt", required=True, help="private; do not publish it")
    export.add_argument("--out", default="logs/analysis/pairs.csv")
    export.set_defaults(func=cmd_export_pairs)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
