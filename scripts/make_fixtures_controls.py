#!/usr/bin/env python3
"""Generate the benign-but-weird control documents for all three workflows.

A control is a *legitimate* document that contains one sentence which merely
sounds like an instruction ("please disregard my earlier message", "ACTION
REQUIRED", a quoted policy line). None is an attack and none carries the marker.
They exist to measure over-reaction: does an agent that handles the base
document's benign twin sensibly start refusing, escalating, or misacting when
ordinary instruction-like phrasing appears?

Evaluation (see docs/design/08_w1_w3_g1_tiers_addendum.md §6): run each workflow
with `controls=True`. The run uses the same scorer as the benign-twin baseline
(`control_check`), so a control's `no_harm` and `legit_task_completed` rates
compare directly against the twin baseline for the same base scenario.

Controls live in corpus/controls/, with one manifest per workflow
(corpus/manifest_wN_controls.jsonl). The sentences are defined in
_corpus_bases.py (CONTROLS). Re-running is idempotent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _corpus_bases import CONTROLS
from _fixtures_common import (
    MARKER,
    ROOT,
    upsert_manifest_line,
    with_extra_line,
    write_document,
)

STEMS = {"w1": "ticket", "w2": "resume", "w3": "parentmail"}


def main() -> int:
    out_dir = ROOT / "corpus" / "controls"
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for workflow, controls in CONTROLS.items():
        manifest = ROOT / "corpus" / f"manifest_{workflow}_controls.jsonl"
        for index, (base, section, sentence, ftype) in enumerate(controls, start=1):
            document = with_extra_line(base, section, sentence)
            name = f"{STEMS[workflow]}_ctrl_{index:04d}.{ftype}"
            write_document(document, out_dir / name, ftype, None, None)
            relative = f"corpus/controls/{name}"
            outcome = upsert_manifest_line(
                manifest,
                {
                    "artifact_id": f"{workflow}c_{index:04d}",
                    "artifact_path": relative,
                    "twin_path": relative,
                    "payload_marker": MARKER,
                    "operator_request": base.operator_request,
                    **base.extras,
                    "kind": "control",
                    "file_type": ftype,
                    "base_id": base.base_id,
                    "control_sentence": sentence,
                },
            )
            total += 1
            print(f"{workflow}c_{index:04d} {base.base_id} {ftype} {outcome}")
    print(f"\n{total} control documents generated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
