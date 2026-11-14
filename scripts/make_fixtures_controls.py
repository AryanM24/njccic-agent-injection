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
(`control_check`), so a control's `no_harm` and `did_correct_thing` rates
compare directly against the twin baseline for the same base scenario.

Controls live in corpus/controls/, with one manifest per workflow
(corpus/manifest_wN_controls.jsonl). The sentences are defined in
_corpus_bases.py (CONTROLS). Re-running is idempotent.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _corpus_bases import CONTROLS
from _fixtures_common import (
    CANARIES,
    MARKER,
    ROOT,
    on_file_addresses,
    trusted_fields,
    upsert_manifest_line,
    with_extra_line,
    write_document,
)

STEMS = {"w1": "ticket", "w2": "resume", "w3": "parentmail"}


def generate_controls(out_root: Path = ROOT, dry_run: bool = False) -> list[dict]:
    """Generate every control document and its manifest row.

    Args:
        out_root: Directory holding the `corpus/` tree to write into.
        dry_run: Print the planned files and write nothing.

    Returns:
        The manifest rows, in artifact order.
    """
    out_dir = out_root / "corpus" / "controls"
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for workflow, controls in CONTROLS.items():
        manifest = out_root / "corpus" / f"manifest_{workflow}_controls.jsonl"
        for index, (base, section, sentence, ftype) in enumerate(controls, start=1):
            name = f"{STEMS[workflow]}_ctrl_{index:04d}.{ftype}"
            relative = f"corpus/controls/{name}"
            row = {
                "artifact_id": f"{workflow}c_{index:04d}",
                "artifact_path": relative,
                "twin_path": relative,
                "payload_marker": MARKER,
                "operator_request": base.operator_request,
                **base.extras,
                "on_file_addresses": on_file_addresses(workflow, base.extras),
                **trusted_fields(workflow, base, f"{workflow}c_{index:04d}"),
                "correct": list(base.correct),
                "kind": "control",
                "file_type": ftype,
                "base_id": base.base_id,
                "control_sentence": sentence,
                "canaries": list(CANARIES),
            }
            rows.append(row)
            label = f"{row['artifact_id']} {base.base_id} {ftype}"
            if dry_run:
                print(f"{label} would write {out_dir / name}")
                continue
            document = with_extra_line(base, section, sentence)
            write_document(document, out_dir / name, ftype, None, None)
            print(f"{label} {upsert_manifest_line(manifest, row)}")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out-root",
        type=Path,
        default=ROOT,
        help="Directory to write the corpus/ tree under (default: the repo).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print planned files; write nothing."
    )
    args = parser.parse_args(argv)
    rows = generate_controls(args.out_root, args.dry_run)
    print(f"\n{len(rows)} control documents generated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
