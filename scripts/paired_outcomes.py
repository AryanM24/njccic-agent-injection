"""Score both halves of every attack pair and report attack − twin per cell.

Usage: python scripts/paired_outcomes.py LOG_DIR [LOG_DIR ...]; set BY=goal (or
channel, base_id, ...) to split each cell by that sample-metadata field. Splits by goal, channel or
file type are Tier 1 (doc 05 §6): write them under `logs/` only. Needs no model:
`control_outcome` (harm, task completion) and `authorization_outcome` are
re-applied to the attack and twin ledgers the pair recorded, which is the
paired design's own comparison. The scorers in the log only score the attack
side, so this is the only place the in-pair twin rates come from. Prints Markdown.
"""

import collections
import glob
import os
import random
import sys

from inspect_ai.log import read_eval_log

from eduinject.scorers.deterministic import RUNS_KEY
from eduinject.scorers.outcomes import (
    W1_SPEC,
    W2_SPEC,
    W3_SPEC,
    authorization_outcome,
    control_outcome,
    exfiltration_outcome,
)
from eduinject.tools.helpdesk import STATE_CHANGING

SPECS = {"w1": W1_SPEC, "w2": W2_SPEC, "w3": W3_SPEC}
BY = os.environ.get("BY")
METRICS = ("no_harm", "legit_task_completed", "unauthorized", "exfiltration")

# (cell, metric) -> artifact -> [(attack, twin) per epoch]
data: dict[tuple[str, ...], dict[str, list[tuple[int, int]]]] = collections.defaultdict(
    lambda: collections.defaultdict(list)
)
for root in sys.argv[1:]:
    for path in sorted(glob.glob(os.path.join(root, "**", "*.eval"), recursive=True)):
        log = read_eval_log(path)
        wf = log.eval.task.split("_")[-1]
        spec = SPECS[wf]
        args = log.eval.task_args
        if args.get("benign_only"):
            continue
        cell = (
            "Luna" if "luna" in log.eval.model else "DeepSeek",
            wf,
            args["scope"],
            "on" if args["isolated"] else "off",
        )
        for sample in log.samples or []:
            md = sample.metadata
            key_cell = (*cell, str(md.get(BY))) if BY else cell
            t2 = {"t2_terms": md.get(spec.t2_field, [])} if spec.t2_field else {}
            got: dict[str, dict[str, int]] = {}
            for side in ("attack", "twin"):
                ledger = md[RUNS_KEY][side]["ledger"]
                g1 = exfiltration_outcome(
                    ledger["attempted_egress"],
                    authorized_recipients=md.get("authorized_recipients", []),
                    applicant_addresses=md.get(spec.correspondent_field, []),
                    other_candidate_terms=md.get(spec.third_party_field, []),
                    policy=spec.policy,
                    **t2,
                )
                unauth = (
                    wf == "w1"
                    and authorization_outcome(
                        ledger["calls"], md.get("entitled_actions", {}), STATE_CHANGING
                    ).violated
                )
                ctl = control_outcome(
                    ledger["calls"],
                    ledger.get("granted_tools", []),
                    md.get("expect", {}),
                    g1_completed=g1.completed,
                    unauthorized=unauth,
                )
                got[side] = {
                    "no_harm": int(ctl.no_harm),
                    "unauthorized": int(unauth),
                    "exfiltration": int(g1.completed),
                }
                if ctl.applicable:
                    got[side]["legit_task_completed"] = int(ctl.legit_task_completed)
            for metric in METRICS:
                if metric in got["attack"] and metric in got["twin"]:
                    data[(*key_cell, metric)][md["artifact_id"]].append(
                        (got["attack"][metric], got["twin"][metric])
                    )


def mean(groups: list[list[tuple[int, int]]], i: int | None) -> float:
    n = sum(map(len, groups))
    if i is None:
        return sum(a - t for g in groups for a, t in g) / n
    return sum(x[i] for g in groups for x in g) / n


by_col = f"{BY} | " if BY else ""
print(
    f"| Model | WF | Scope | Iso | {by_col}Metric | Runs | Attack | Twin | Attack − twin [95% pair-clustered CI] |"
)
print("|" + " --- |" * (9 + bool(BY)))
for key in sorted(data):
    groups = list(data[key].values())
    a, t = mean(groups, 0), mean(groups, 1)
    if a == t == 0 and key[-1] != "legit_task_completed":
        continue
    rng = random.Random(0)
    draws = sorted(mean(rng.choices(groups, k=len(groups)), None) for _ in range(2000))
    print(
        f"| {' | '.join(key)} | {sum(map(len, groups))} | {a:.3f} | {t:.3f} | "
        f"{a - t:+.3f} [{draws[50]:+.3f}, {draws[1949]:+.3f}] |"
    )
