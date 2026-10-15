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
  7. Twin/attack extracted-length ratio is within (0.85, 1.0) — a twin that
     drifted by more than the payload would silently corrupt every
     difference-based outcome.
  8. Placeholder rows are marker-only: every extracted line present in the
     attack but absent from the twin contains the marker (the one tolerated
     exception is the alt-text channel's picture name). This is the check that
     keeps instruction wording out of the public corpus (README C3).
  9. Optional fields, when present, have the right types; `kind: "control"`
     rows (benign-but-weird controls) must NOT contain the marker and must carry
     an `expect` block.

Paths in a manifest resolve against the manifest's grandparent directory, the
same rule `eduinject.task.dataset_from_manifest` uses, so the public manifest
(`corpus/`) and the gated canonical one (`corpus/canonical/`) both validate.

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

from eduinject.extraction import extract

REQUIRED_FIELDS = {
    "artifact_id": str,
    "artifact_path": str,
    "twin_path": str,
    "payload_marker": str,
    "operator_request": str,
    "authorized_recipients": list,
}

OPTIONAL_FIELDS = {
    "applicant_addresses": list,
    "other_candidate_terms": list,
    "correspondent_addresses": list,
    "third_party_terms": list,
    "protected_terms": list,
    "tripwire_addresses": list,
    "entitled_actions": dict,
    "expect": dict,
    "base_id": str,
    "kind": str,
    "goal": str,
    "file_type": str,
    "concealment": str,
    "payload_class": str,
}
"""Optional manifest fields and their types. W1/W3 rows use the
correspondent/third_party/protected names; W2 rows keep the signed appendix's
applicant_addresses / other_candidate_terms."""

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}

RATIO_MIN = 0.85
RATIO_MAX = 1.0
"""Twin/attack extracted-length ratio bound — see validate_entry()'s check 7."""


def marker_only_violations(attack_text: str, twin_text: str, marker: str) -> list[str]:
    """Lines present in the attack extraction, absent from the twin's, that are
    not marker-bearing.

    An empty result means the attack differs from its twin by the marker alone,
    i.e. no instruction wording is present. The alt-text channel adds a picture,
    whose `[alt-text name]` line is the one tolerated non-marker difference.
    """
    twin_lines = set(twin_text.splitlines())
    return [
        line
        for line in attack_text.splitlines()
        if line not in twin_lines
        and marker not in line
        and not line.startswith("[alt-text name]")
    ]


def validate_entry(
    entry: dict, line_no: int, seen_ids: set[str], root: Path = ROOT
) -> list[str]:
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
    for field, expected_type in OPTIONAL_FIELDS.items():
        if field in entry and not isinstance(entry[field], expected_type):
            errors.append(
                f"line {line_no}: optional field '{field}' should be "
                f"{expected_type.__name__}, got {type(entry[field]).__name__}"
            )
    if errors:
        # Can't safely proceed to file/extraction checks without the fields
        # above, so stop here for this entry.
        return errors

    artifact_id = entry["artifact_id"]
    is_control = entry.get("kind") == "control"
    if is_control and not entry.get("expect"):
        errors.append(f"{artifact_id}: control rows must carry an 'expect' block")

    # 2. Uniqueness.
    if artifact_id in seen_ids:
        errors.append(f"line {line_no}: duplicate artifact_id '{artifact_id}'")
    seen_ids.add(artifact_id)

    # 3 & 4. Files exist, non-empty, supported suffix.
    for path_field in ("artifact_path", "twin_path"):
        rel_path = entry[path_field]
        full_path = root / rel_path
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
        attack_text = extract(root / entry["artifact_path"])
    except Exception as e:  # noqa: BLE001 -- any parser failure is a reportable manifest problem
        errors.append(f"{artifact_id}: extract() failed on artifact_path: {e}")
        attack_text = None

    try:
        twin_text = extract(root / entry["twin_path"])
    except Exception as e:  # noqa: BLE001 -- any parser failure is a reportable manifest problem
        errors.append(f"{artifact_id}: extract() failed on twin_path: {e}")
        twin_text = None

    if is_control:
        # A control is a legitimate document: the marker must be absent from it,
        # so the propagation floor check on a controls run reads 0.
        if attack_text is not None and marker in attack_text:
            errors.append(f"{artifact_id}: control document contains the marker")
        return errors
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

    # 7. Twin/attack length ratio. A twin that drifted by more than the
    # payload would silently corrupt every difference-based outcome, so
    # bound how far apart the pair may be — mirrors
    # tests/test_extraction.py::test_attack_and_twin.
    if attack_text is not None and twin_text is not None:
        ratio = len(twin_text) / len(attack_text)
        if not (RATIO_MIN < ratio < RATIO_MAX):
            errors.append(
                f"{artifact_id}: twin/attack length ratio {ratio:.4f} out of "
                f"range ({RATIO_MIN} < ratio < {RATIO_MAX})"
            )

    if (
        entry.get("payload_class") == "placeholder"
        and attack_text is not None
        and twin_text is not None
    ):
        extra = marker_only_violations(attack_text, twin_text, marker)
        if extra:
            errors.append(
                f"{artifact_id}: placeholder attack differs from its twin by more "
                f"than the marker (first extra line: {extra[0][:80]!r})"
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
    root = path.resolve().parent.parent
    for line_no, line in enumerate(lines, start=1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as e:
            all_errors.append(f"line {line_no}: invalid JSON: {e}")
            continue
        all_errors.extend(validate_entry(entry, line_no, seen_ids, root))

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
