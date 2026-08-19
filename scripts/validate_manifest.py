#!/usr/bin/env python3
"""Validate a corpus manifest before trusting it in eduinject_w2/w1/w3.

Checks, in order:
  1. Every line is valid JSON with the required fields, correctly typed.
  2. artifact_id is unique across the file.
  3. artifact_path / twin_path actually exist on disk and are non-empty.
  4. File suffix is one eduinject.extraction.extract() supports.
  5. extract() runs cleanly on both files (catches malformed docx/pdf output
     before it ever reaches the pipeline).
  6. payload_marker appears in the attack extraction and does NOT appear in
     the twin extraction — this is the check that actually proves a fixture
     pair means what its manifest line claims.

Usage:
    python scripts/validate_manifest.py corpus/manifest_w2.jsonl
    python scripts/validate_manifest.py corpus/manifest_w1.jsonl corpus/manifest_w3.jsonl

Exits 0 if every entry in every given manifest passes, 1 otherwise. Prints
one line per failure so a bad batch is easy to hand back with specifics
rather than "something's wrong, try again."
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eduinject.extraction import extract  # noqa: E402

REQUIRED_FIELDS = {
    "artifact_id": str,
    "artifact_path": str,
    "twin_path": str,
    "payload_marker": str,
    "operator_request": str,
    "authorized_recipients": list,
    "applicant_addresses": list,
    "other_candidate_terms": list,
}

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}


def validate_entry(entry: dict, line_no: int, seen_ids: set[str]) -> list[str]:
    """Validate one manifest line. Returns a list of failure messages
    (empty if the entry is clean)."""
    errors: list[str] = []

    # 1. Required fields present and correctly typed.
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in entry:
            errors.append(f"line {line_no}: missing required field '{field}'")
        elif not isinstance(entry[field], expected_type):
            errors.append(
                f"line {line_no}: field '{field}' should be "
                f"{expected_type.__name__}, got {type(entry[field]).__name__}"
            )
    if errors:
        # Can't safely proceed to file/extraction checks without the fields
        # above, so stop here for this entry.
        return errors

    artifact_id = entry["artifact_id"]

    # 2. Uniqueness.
    if artifact_id in seen_ids:
        errors.append(f"line {line_no}: duplicate artifact_id '{artifact_id}'")
    seen_ids.add(artifact_id)

    # 3 & 4. Files exist, non-empty, supported suffix.
    for path_field in ("artifact_path", "twin_path"):
        rel_path = entry[path_field]
        full_path = ROOT / rel_path
        if not full_path.exists():
            errors.append(
                f"{artifact_id}: {path_field} '{rel_path}' does not exist "
                f"(resolved to {full_path})"
            )
            continue
        if full_path.stat().st_size == 0:
            errors.append(f"{artifact_id}: {path_field} '{rel_path}' is empty")
        if full_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            errors.append(
                f"{artifact_id}: {path_field} has unsupported suffix "
                f"'{full_path.suffix}' (extract() supports {sorted(SUPPORTED_SUFFIXES)})"
            )

    if errors:
        # File-level problems make the extraction/marker checks meaningless.
        return errors

    # 5 & 6. extract() runs cleanly, and the marker lands where it should.
    marker = entry["payload_marker"]
    try:
        attack_text = extract(ROOT / entry["artifact_path"])
    except Exception as e:
        errors.append(f"{artifact_id}: extract() failed on artifact_path: {e}")
        attack_text = None

    try:
        twin_text = extract(ROOT / entry["twin_path"])
    except Exception as e:
        errors.append(f"{artifact_id}: extract() failed on twin_path: {e}")
        twin_text = None

    if attack_text is not None and marker not in attack_text:
        errors.append(
            f"{artifact_id}: payload_marker '{marker}' NOT found in attack "
            "extraction — the injection won't be visible to the intake agent"
        )
    if twin_text is not None and marker in twin_text:
        errors.append(
            f"{artifact_id}: payload_marker '{marker}' found in TWIN "
            "extraction — this pair can't measure a false-positive rate"
        )

    return errors


def validate_manifest(path: Path) -> tuple[int, list[str]]:
    """Validate one manifest file. Returns (entry_count, all_errors)."""
    if not path.exists():
        return 0, [f"{path}: file does not exist"]

    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        # An empty manifest (e.g. manifest_w1.jsonl before fixtures exist) is
        # a valid state, not an error — nothing to validate.
        return 0, []

    all_errors: list[str] = []
    seen_ids: set[str] = set()
    for line_no, line in enumerate(lines, start=1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as e:
            all_errors.append(f"line {line_no}: invalid JSON: {e}")
            continue
        all_errors.extend(validate_entry(entry, line_no, seen_ids))

    return len(lines), all_errors


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: validate_manifest.py <manifest.jsonl> [more manifests...]")
        return 1

    overall_ok = True
    for arg in sys.argv[1:]:
        path = Path(arg)
        count, errors = validate_manifest(path)
        if errors:
            overall_ok = False
            print(f"{path}: {count} entries, {len(errors)} problem(s)")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"{path}: {count} entries, all clean")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())