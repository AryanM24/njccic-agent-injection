"""Copy eval logs with `propagation` recomputed by the current scorer code.

Usage: python scripts/rescore_propagation.py SRC_DIR DST_DIR. Needs no model: the pipeline
record each run kept in sample metadata is all `marker_propagation` reads.
Originals are never modified.
"""

import glob
import os
import sys

from inspect_ai.log import read_eval_log, write_eval_log

from eduinject.scorers.deterministic import RUNS_KEY
from eduinject.scorers.outcomes import marker_propagation

src, dst = sys.argv[1], sys.argv[2]
changed = total = 0
for path in sorted(glob.glob(os.path.join(src, "**", "*.eval"), recursive=True)):
    log = read_eval_log(path)
    for sample in log.samples or []:
        old = sample.scores.get("propagation") if sample.scores else None
        if old is None:
            continue
        pipeline = sample.metadata[RUNS_KEY]["attack"]["pipeline"]
        outcome = marker_propagation(pipeline, sample.metadata["payload_marker"])
        value = {
            k: float(getattr(outcome, k)) for k in ("intake", "analysis", "action")
        }
        total += 1
        changed += value != old.value
        old.value = value
    out = os.path.join(dst, os.path.relpath(path, src))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    write_eval_log(log, out)
print(f"{total} samples rescored, {changed} changed -> {dst}")
