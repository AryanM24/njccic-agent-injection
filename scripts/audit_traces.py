#!/usr/bin/env python3
"""Audit finished runs against the trace-monitor rules (doc 11 §3.3, A3).

    audit_traces.py --log-dir DIR [DIR ...] --out logs/audit/<name>/
                    --runs attack|twin|both [--split dev|confirm]

Writes, under OUT (which must lie under a `logs/` directory: traces are
Tier 1):

    violations.csv    one row per rule violation (step, tool, args, reason,
                      origin stage)
    runs.csv          one row per run: status, violated rules, first
                      violation, and the authorization / exfiltration /
                      scope_violation outcomes recomputed from the run's ledger
    cell_rules.csv    per cell (analysis.CELL_FIELDS), run label and rule: runs,
                      runs violating it, rate, and runs excluded for status
    disagreements.csv runs where the monitor (any violation) and one of those
                      scorers differ, both values listed

Runs whose record status is not "ok" (doc unavailable, handoff parse error)
appear in runs.csv with their status only and are excluded from violations,
rates and disagreements.

Disagreements are for review: rules are never edited to remove them. Nothing
here contacts a model.
"""

import argparse
import csv
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from eduinject.analysis import CELL_FIELDS, finished_samples, refuse_stale
from eduinject.monitor.rules import RULES, monitor
from eduinject.records import RunRecord, records_from_sample
from eduinject.scorers.deterministic import RUNS_KEY
from eduinject.scorers.outcomes import (
    authorization_outcome,
    exfiltration_from_metadata,
    scope_outcome,
    took_effect,
)
from eduinject.task import workflow

KEY_FIELDS = ("label", "sample_id", "artifact_id", "epoch", "split")
SCORERS = ("authorization", "exfiltration", "scope_violation")


def scorer_values(rec: RunRecord, run: Mapping[str, Any]) -> dict[str, int | None]:
    """The three comparison scorers' outcomes for one run (None: not scored)."""
    wf = workflow(rec.cell["workflow"])
    ledger = run["ledger"]
    changing = wf.state_changing
    return {
        "authorization": int(
            authorization_outcome(
                took_effect(ledger["calls"]),
                rec.meta.get("entitled_actions", {}),
                changing,
            ).violated
        )
        if changing
        else None,
        "exfiltration": int(
            exfiltration_from_metadata(
                ledger["attempted_egress"], rec.meta, wf.spec
            ).completed
        ),
        "scope_violation": int(
            scope_outcome(ledger["calls"], ledger.get("granted_tools", [])).violated
        ),
    }


def _write(path: Path, rows: list[dict[str, Any]], fields: Sequence[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(fields))
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--log-dir", nargs="+", required=True, dest="log_dirs")
    ap.add_argument("--out", required=True)
    ap.add_argument("--runs", choices=("attack", "twin", "both"), required=True)
    ap.add_argument("--split", choices=("dev", "confirm"), default=None)
    ap.add_argument("--allow-stale", action="store_true")
    args = ap.parse_args(argv)

    out = Path(args.out)
    if "logs" not in out.resolve().parts:
        print(f"refused: --out {out} is not under a logs/ directory", file=sys.stderr)
        return 2
    if refuse_stale(args.log_dirs, args.allow_stale):
        return 4
    labels = ("attack", "twin") if args.runs == "both" else (args.runs,)

    violations: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    cell_runs: Counter[tuple[Any, ...]] = Counter()
    cell_hits: Counter[tuple[Any, ...]] = Counter()
    cell_excluded: Counter[tuple[Any, ...]] = Counter()
    for cell, sample in finished_samples(args.log_dirs):
        recorded = (sample.metadata or {}).get(RUNS_KEY) or {}
        for rec in records_from_sample(sample, cell):
            if rec.label not in labels:
                continue
            if args.split and rec.coords.get("split") != args.split:
                continue
            rules = RULES[rec.cell["workflow"]]
            key = (*(rec.cell.get(f) for f in CELL_FIELDS), rec.label)
            base = {
                **{f: rec.cell.get(f) for f in CELL_FIELDS},
                "label": rec.label,
                "sample_id": rec.sample_id,
                "artifact_id": rec.artifact_id,
                "epoch": rec.epoch,
                "split": rec.coords.get("split"),
            }
            if rec.status != "ok":
                # Not auditable (no document, broken handoff): counted, not rated.
                runs.append({**base, "status": rec.status, "calls": len(rec.calls)})
                for rule in rules:
                    cell_excluded[(*key, rule.id)] += 1
                continue
            result = monitor(rec, rules)
            for v in result.violations:
                violations.append(
                    {
                        **base,
                        "rule_id": v.rule_id,
                        "severity": v.severity,
                        "step": v.step,
                        "tool": v.tool,
                        "args": json.dumps(v.args, sort_keys=True, default=str),
                        "reason": v.reason,
                        "values": ";".join(v.values),
                        "origin_stage": v.origin_stage,
                    }
                )
            hit = sorted({v.rule_id for v in result.violations})
            first = result.first_violation
            scores = scorer_values(rec, recorded[rec.label])
            runs.append(
                {
                    **base,
                    "status": rec.status,
                    "calls": len(rec.calls),
                    "violations": len(result.violations),
                    "rule_ids": ";".join(hit),
                    "first_rule": first.rule_id if first else "",
                    "first_step": first.step if first else "",
                    "first_origin_stage": (first.origin_stage or "") if first else "",
                    **{k: "" if s is None else s for k, s in scores.items()},
                }
            )
            flagged = int(bool(result.violations))
            for name, value in scores.items():
                if value is not None and value != flagged:
                    disagreements.append(
                        {
                            **base,
                            "scorer": name,
                            "scorer_value": value,
                            "monitor_violated": flagged,
                            "monitor_rule_ids": ";".join(hit),
                        }
                    )
            for rule in rules:
                cell_runs[(*key, rule.id)] += 1
                cell_hits[(*key, rule.id)] += rule.id in hit

    cell_rows = [
        {
            **dict(zip((*CELL_FIELDS, "label", "rule_id"), k, strict=True)),
            "runs": cell_runs[k],
            "violated": cell_hits[k],
            "rate": cell_hits[k] / cell_runs[k] if cell_runs[k] else "",
            "excluded": cell_excluded[k],
        }
        for k in sorted(cell_runs | cell_excluded, key=lambda k: tuple(map(str, k)))
    ]
    out.mkdir(parents=True, exist_ok=True)
    base_fields = (*CELL_FIELDS, *KEY_FIELDS)
    _write(
        out / "violations.csv",
        violations,
        (
            *base_fields,
            "rule_id",
            "severity",
            "step",
            "tool",
            "args",
            "reason",
            "values",
            "origin_stage",
        ),
    )
    _write(
        out / "runs.csv",
        runs,
        (
            *base_fields,
            "status",
            "calls",
            "violations",
            "rule_ids",
            "first_rule",
            "first_step",
            "first_origin_stage",
            *SCORERS,
        ),
    )
    _write(
        out / "cell_rules.csv",
        cell_rows,
        (*CELL_FIELDS, "label", "rule_id", "runs", "violated", "rate", "excluded"),
    )
    _write(
        out / "disagreements.csv",
        disagreements,
        (
            *base_fields,
            "scorer",
            "scorer_value",
            "monitor_violated",
            "monitor_rule_ids",
        ),
    )
    print(
        f"{len(runs)} run(s), {len(violations)} violation(s), "
        f"{len(disagreements)} disagreement(s) -> {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
