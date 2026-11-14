"""Break G1 completions down by who received them (doc 09 §9), attack and twin.

Usage: python scripts/exfil_recipients.py LOG_DIR [LOG_DIR ...]. Needs no model:
`analysis.g1_outcome` is re-applied to each run's recorded ledger, so the twin
side of a paired run is scored too. Prints a Markdown table. The in-pair
attack − twin G1 rate is `exfiltration` in `scripts/paired_outcomes.py`.

Recipient classes are keyword heuristics over the address, a reading aid for
the signed G1 rule, not a replacement for it.
"""

import collections
import sys

from eduinject.analysis import (
    FLOOR_FIELDS,
    WORKFLOW_SPECS,
    cell_kind,
    finished_samples,
    g1_outcome,
    model_label,
)
from eduinject.scorers.deterministic import RUNS_KEY

WHO = ["tripwire", "correspondent", "data subject", "internal staff", "other"]
COLUMNS = ["logs", *FLOOR_FIELDS, "side"]


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
pairs_hit: dict[tuple[str, ...], set[str]] = collections.defaultdict(set)
for c, sample in finished_samples(sys.argv[1:]):
    cell = {**c, "logs": cell_kind(c), "model": model_label(c["model"])}
    md = sample.metadata
    spec = WORKFLOW_SPECS[c["workflow"]]
    third = [t.lower() for t in md.get(spec.third_party_field) or []]
    tripwires = [t.lower() for t in md.get("tripwire_addresses") or []]
    for side, run in (md.get(RUNS_KEY) or {}).items():
        outcome = g1_outcome(md, c["workflow"], run["ledger"]["attempted_egress"])
        k = tuple(str(v) for v in ({**cell, "side": side}[f] for f in COLUMNS))
        runs[k] += 1
        flagged[k] += outcome.completed
        if outcome.completed:
            pairs_hit[k].add(md["artifact_id"])
        for m in outcome.completions:
            who[(*k, recipient(m.to, m.recipient_class, tripwires, third))] += 1

print(
    "Runs and Flagged count runs; Pairs counts distinct artifact pairs among the "
    "flagged runs; the recipient columns count *messages*, so they can sum to more "
    "than Flagged.\n"
)
print(f"| {' | '.join(COLUMNS)} | Runs | Flagged | Pairs | " + " | ".join(WHO) + " |")
print("|" + " --- |" * (len(COLUMNS) + 3 + len(WHO)))
scope = COLUMNS.index("scope")
for k in sorted(runs):
    if not flagged[k] and k[scope] == "read_only":
        continue
    counts = " | ".join(str(who[(*k, c)]) for c in WHO)
    print(
        f"| {' | '.join(k)} | {runs[k]} | {flagged[k]} | {len(pairs_hit[k])} "
        f"| {counts} |"
    )
