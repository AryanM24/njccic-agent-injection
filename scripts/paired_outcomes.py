"""Attack vs twin within each pair, per attack cell, for every outcome.

Usage: python scripts/paired_outcomes.py LOG_DIR [LOG_DIR ...]; set BY=goal (or
channel, base_id, ...) to split each cell by that sample-metadata field. Splits
by goal, channel or file type are Tier 1 (doc 05 §6): write them under `logs/`
only. Needs no model: `analysis.in_pair_rates` re-scores both recorded ledgers
of every finished sample, so it covers outcomes (G1, the W1 authorization
oracle, task completion) that the scorers record on the attack side only.
Prints Markdown.
"""

import argparse
import os
import sys

from eduinject.analysis import (
    FLOOR_FIELDS,
    finished_samples,
    in_pair_rates,
    model_label,
    refuse_stale,
)

_ap = argparse.ArgumentParser()
_ap.add_argument("log_dirs", nargs="+")
_ap.add_argument("--allow-stale", action="store_true")
_args = _ap.parse_args()
if refuse_stale(_args.log_dirs, _args.allow_stale):
    sys.exit(4)

BY = os.environ.get("BY")
columns = [*FLOOR_FIELDS, *([BY] if BY else []), "metric"]
print(
    f"| {' | '.join(columns)} | Runs | Attack | Twin "
    "| Attack − twin [95% pair-clustered CI] |"
)
print("|" + " --- |" * (len(columns) + 4))
for r in in_pair_rates(finished_samples(_args.log_dirs), by=BY):
    if r.attack == r.twin == 0 and r.metric != "legit_task_completed":
        continue
    cell = {**r.cell, "model": model_label(r.cell["model"]), "metric": r.metric}
    print(
        f"| {' | '.join(str(cell[c]) for c in columns)} | {r.n_runs} "
        f"| {r.attack:.3f} | {r.twin:.3f} "
        f"| {r.diff.diff:+.3f} [{r.diff.lo:+.3f}, {r.diff.hi:+.3f}] |"
    )
