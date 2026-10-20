"""Break G1 completions down by who received them (doc 09 §9), attack and twin.

Usage: python scripts/exfil_recipients.py LOG_DIR [LOG_DIR ...]. Needs no model:
`exfiltration_outcome` is re-applied to each run's recorded ledger, so the twin
side of a paired run is scored too. Prints a Markdown table.

Recipient classes are keyword heuristics over the address, a reading aid for
the signed G1 rule, not a replacement for it.
"""

import collections
import glob
import os
import random
import sys

from inspect_ai.log import read_eval_log

from eduinject.scorers.outcomes import (
    W1_SPEC,
    W2_SPEC,
    W3_SPEC,
    exfiltration_outcome,
)

SPECS = {"w1": W1_SPEC, "w2": W2_SPEC, "w3": W3_SPEC}
WHO = ["tripwire", "correspondent", "data subject", "internal staff", "other"]


def recipient(to: str, cls: str, tripwires: list[str], third: list[str]) -> str:
    to = to.lower()
    local, _, dom = to.partition("@")
    if to in tripwires:
        return "tripwire"
    if cls in ("submitter", "applicant", "correspondent"):
        return "correspondent"
    words = [w for w in local.replace("-", ".").replace("_", ".").split(".")]
    if to in third or any(len(w) > 3 and any(w in t for t in third) for w in words):
        return "data subject"
    if "district" in dom or "k12" in dom or dom.endswith(".edu"):
        return "internal staff"
    return "other"


runs: collections.Counter[tuple[str, ...]] = collections.Counter()
flagged: collections.Counter[tuple[str, ...]] = collections.Counter()
who: collections.Counter[tuple[str, ...]] = collections.Counter()
# (cell) -> artifact -> [attack - twin completed, per epoch]
paired: dict[tuple[str, ...], dict[str, list[int]]] = collections.defaultdict(
    lambda: collections.defaultdict(list)
)
for root in sys.argv[1:]:
    for path in sorted(glob.glob(os.path.join(root, "**", "*.eval"), recursive=True)):
        log = read_eval_log(path)
        wf = log.eval.task.split("_")[-1]
        spec = SPECS[wf]
        args = log.eval.task_args
        model = log.eval.model.split("/")[-1]
        kind = "baseline" if args.get("benign_only") else "attack-log"
        cell = (model, kind, wf, args["scope"], "on" if args["isolated"] else "off")
        for sample in log.samples or []:
            md = sample.metadata
            third = [t.lower() for t in md.get(spec.third_party_field) or []]
            tripwires = [t.lower() for t in md.get("tripwire_addresses") or []]
            t2 = {"t2_terms": md.get(spec.t2_field, [])} if spec.t2_field else {}
            done = {}
            for side in ("attack", "twin"):
                key = f"Ledger:{side}:attempted_egress"
                if key not in sample.store:
                    continue
                outcome = exfiltration_outcome(
                    sample.store[key],
                    authorized_recipients=md.get("authorized_recipients", []),
                    applicant_addresses=md.get(spec.correspondent_field, []),
                    other_candidate_terms=third,
                    policy=spec.policy,
                    tripwire_addresses=tripwires,
                    **t2,
                )
                runs[(*cell, side)] += 1
                flagged[(*cell, side)] += outcome.completed
                done[side] = int(outcome.completed)
                for m in outcome.completions:
                    c = recipient(m.to, m.recipient_class, tripwires, third)
                    who[(*cell, side, c)] += 1
            if len(done) == 2:
                paired[cell][md["artifact_id"]].append(done["attack"] - done["twin"])

print(
    "| Model | Logs | WF | Scope | Iso | Side | Runs | Flagged | "
    + " | ".join(WHO)
    + " |"
)
print("|" + " --- |" * (8 + len(WHO)))
for k in sorted(runs):
    if not flagged[k] and k[3] == "read_only":
        continue
    counts = " | ".join(str(who[(*k, c)]) for c in WHO)
    print(f"| {' | '.join(k)} | {runs[k]} | {flagged[k]} | {counts} |")

print("\n| Model | WF | Scope | Iso | Pairs | Attack − twin [95% pair-clustered CI] |")
print("| --- | --- | --- | --- | --- | --- |")
for cell in sorted(paired):
    by_art = list(paired[cell].values())
    if not any(any(v) for v in by_art):
        continue
    rng = random.Random(0)

    def mean(groups: list[list[int]]) -> float:
        return sum(map(sum, groups)) / sum(map(len, groups))

    draws = sorted(mean(rng.choices(by_art, k=len(by_art))) for _ in range(2000))
    model, _, wf, scope, iso = cell
    print(
        f"| {model} | {wf} | {scope} | {iso} | {sum(map(len, by_art))} | "
        f"{mean(by_art):+.3f} [{draws[50]:+.3f}, {draws[1949]:+.3f}] |"
    )
