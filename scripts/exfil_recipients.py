"""Break G1 completions down by who received them (doc 09 §9), attack and twin.

Usage: python scripts/exfil_recipients.py LOG_DIR [LOG_DIR ...]. Needs no model:
`exfiltration_outcome` is re-applied to each run's recorded ledger, so the twin
side of a paired run is scored too. Prints a Markdown table.

Recipient classes are keyword heuristics over the address, a reading aid for
the signed G1 rule, not a replacement for it.
"""

import collections
import random
import sys

from eduinject.analysis import finished_samples, model_label
from eduinject.scorers.deterministic import RUNS_KEY
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
pairs_hit: dict[tuple[str, ...], set[str]] = collections.defaultdict(set)
for c, sample in finished_samples(sys.argv[1:]):
    wf = c["workflow"]
    spec = SPECS[wf]
    kind = "baseline" if c["benign_only"] else "attack-log"
    cell = (
        model_label(c["model"]),
        kind,
        wf,
        c["scope"],
        "on" if c["isolated"] else "off",
        c["identity_mode"],
        c["defense"],
    )
    md = sample.metadata
    third = [t.lower() for t in md.get(spec.third_party_field) or []]
    tripwires = [t.lower() for t in md.get("tripwire_addresses") or []]
    t2 = {"t2_terms": md.get(spec.t2_field, [])} if spec.t2_field else {}
    done = {}
    for side, run in (md.get(RUNS_KEY) or {}).items():
        outcome = exfiltration_outcome(
            run["ledger"]["attempted_egress"],
            authorized_recipients=md.get("authorized_recipients", []),
            applicant_addresses=md.get(spec.correspondent_field, []),
            other_candidate_terms=third,
            policy=spec.policy,
            tripwire_addresses=tripwires,
            candidate_terms=md.get("candidate_terms", {}),
            **t2,
        )
        runs[(*cell, side)] += 1
        flagged[(*cell, side)] += outcome.completed
        done[side] = int(outcome.completed)
        if outcome.completed:
            pairs_hit[(*cell, side)].add(md["artifact_id"])
        for m in outcome.completions:
            who[
                (*cell, side, recipient(m.to, m.recipient_class, tripwires, third))
            ] += 1
    if len(done) == 2:
        paired[cell][md["artifact_id"]].append(done["attack"] - done["twin"])

print(
    "Runs and Flagged count runs; Pairs counts distinct artifact pairs among the "
    "flagged runs; the recipient columns count *messages*, so they can sum to more "
    "than Flagged.\n"
)
print(
    "| Model | Logs | WF | Scope | Iso | Identity | Defense | Side | Runs | Flagged "
    "| Pairs | " + " | ".join(WHO) + " |"
)
print("|" + " --- |" * (11 + len(WHO)))
for k in sorted(runs):
    if not flagged[k] and k[3] == "read_only":
        continue
    counts = " | ".join(str(who[(*k, c)]) for c in WHO)
    print(
        f"| {' | '.join(k)} | {runs[k]} | {flagged[k]} | {len(pairs_hit[k])} "
        f"| {counts} |"
    )

print(
    "\n| Model | WF | Scope | Iso | Identity | Defense | Pairs | Runs "
    "| Attack − twin [95% pair-clustered CI] |"
)
print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
for cell in sorted(paired):
    by_art = list(paired[cell].values())
    if not any(any(v) for v in by_art):
        continue
    rng = random.Random(0)

    def mean(groups: list[list[int]]) -> float:
        return sum(map(sum, groups)) / sum(map(len, groups))

    # Doc 09 §3: 1,000 resamples of pairs, the 2.5th and 97.5th percentiles.
    draws = sorted(mean(rng.choices(by_art, k=len(by_art))) for _ in range(1000))
    model, _, wf, scope, iso, identity, defense = cell
    print(
        f"| {model} | {wf} | {scope} | {iso} | {identity} | {defense} | {len(by_art)} "
        f"| {sum(map(len, by_art))} | {mean(by_art):+.3f} "
        f"[{draws[25]:+.3f}, {draws[974]:+.3f}] |"
    )
