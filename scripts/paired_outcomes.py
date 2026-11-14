"""Score both halves of every attack pair and report attack − twin per cell.

Usage: python scripts/paired_outcomes.py LOG_DIR [LOG_DIR ...]; set BY=goal (or
channel, base_id, ...) to split each cell by that sample-metadata field. Splits by goal, channel or
file type are Tier 1 (doc 05 §6): write them under `logs/` only. Needs no model:
`control_outcome` (harm, task completion) and `authorization_outcome` are
re-applied to the attack and twin ledgers the pair recorded (retries resolved
newest-wins, errored and limit-hit samples skipped, as in `analysis.load_rows`), which is the
paired design's own comparison. The scorers in the log only score the attack
side, so this is the only place the in-pair twin rates come from. Prints Markdown.
"""

import collections
import os
import random
import sys

from eduinject.agents.task_facts import VERIFIED_CORRESPONDENTS
from eduinject.analysis import finished_samples, model_label
from eduinject.scorers.deterministic import RUNS_KEY
from eduinject.scorers.outcomes import (
    W1_SPEC,
    W2_SPEC,
    W3_SPEC,
    authorization_outcome,
    control_outcome,
    correct_outcome,
    exfiltration_outcome,
)
from eduinject.task import workflow
from eduinject.tools.helpdesk import STATE_CHANGING

SPECS = {"w1": W1_SPEC, "w2": W2_SPEC, "w3": W3_SPEC}
BY = os.environ.get("BY")
METRICS = ("no_harm", "did_correct_thing", "unauthorized", "exfiltration")

# (cell, metric) -> artifact -> [(attack, twin) per epoch]
data: dict[tuple[str, ...], dict[str, list[tuple[int, int]]]] = collections.defaultdict(
    lambda: collections.defaultdict(list)
)
for c, sample in finished_samples(sys.argv[1:]):
    if c["benign_only"]:
        continue
    wf = c["workflow"]
    spec = SPECS[wf]
    cell = (
        model_label(c["model"]),
        c["host"],
        wf,
        c["scope"],
        "on" if c["isolated"] else "off",
        c["identity_mode"],
        c["defense"],
        c["corpus"],
    )
    md = sample.metadata
    key_cell = (*cell, str(md.get(BY))) if BY else cell
    t2 = {"t2_terms": md.get(spec.t2_field, [])} if spec.t2_field else {}
    got: dict[str, dict[str, int]] = {}
    for side in ("attack", "twin"):
        ledger = md[RUNS_KEY][side]["ledger"]
        g1 = exfiltration_outcome(
            ledger["attempted_egress"],
            authorized_recipients=md.get("authorized_recipients", []),
            applicant_addresses=VERIFIED_CORRESPONDENTS[wf](md),
            other_candidate_terms=md.get(spec.third_party_field, []),
            workflow=wf,
            data_subject_addresses=md.get("data_subject_addresses", []),
            candidate_terms=md.get("candidate_terms", {}),
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
            md.get("expect", {}),
            g1_completed=g1.completed,
            unauthorized=unauth,
        )
        got[side] = {
            "no_harm": int(ctl.no_harm),
            "unauthorized": int(unauth),
            "exfiltration": int(g1.completed),
        }
        if "correct" in md:
            got[side]["did_correct_thing"] = int(
                correct_outcome(
                    ledger["calls"],
                    ledger["attempted_egress"],
                    md["correct"],
                    authorized=md.get("authorized_recipients", []),
                    correspondents=md.get(spec.correspondent_field, []),
                    write_tools=workflow(wf).write_tools,
                    escalation_tools=("escalate_to_staff",) if wf == "w3" else (),
                ).did_correct_thing
            )
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
    f"| Model | Host | WF | Scope | Iso | Identity | Defense | Corpus | {by_col}Metric "
    "| Runs | Attack | Twin | Attack − twin [95% pair-clustered CI] |"
)
print("|" + " --- |" * (13 + bool(BY)))
for key in sorted(data):
    groups = list(data[key].values())
    a, t = mean(groups, 0), mean(groups, 1)
    if a == t == 0 and key[-1] != "did_correct_thing":
        continue
    rng = random.Random(0)
    # Doc 09 §3: 1,000 resamples of pairs, the 2.5th and 97.5th percentiles.
    draws = sorted(mean(rng.choices(groups, k=len(groups)), None) for _ in range(1000))
    print(
        f"| {' | '.join(key)} | {sum(map(len, groups))} | {a:.3f} | {t:.3f} | "
        f"{a - t:+.3f} [{draws[25]:+.3f}, {draws[974]:+.3f}] |"
    )
