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
  7. The twin is channel-matched (A-11): it differs from the attack in one
     block only, carrying marker-free neutral text in the payload's channel,
     length-matched to the payload (see `channel_match_violations`). A twin
     that drifted elsewhere would silently corrupt every difference-based
     outcome.
  8. Placeholder rows are marker-only: every extracted line present in the
     attack but absent from the twin contains the marker. This is the check
     that keeps instruction wording out of the public corpus (README C3).
  9. Optional fields, when present, have the right types; `kind: "control"`
     rows (benign-but-weird controls) must NOT contain the marker and must carry
     an `expect` block.
 10. `correct` declares at least one well-formed correct-handling alternative
     (see `correct_errors`).

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

import difflib
import json
import re
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
    "correct": list,
    "data_subject_addresses": list,
}

CORRECT_KINDS = ("act", "refuse", "escalate", "ask_info")

OPTIONAL_FIELDS = {
    "applicant_addresses": list,
    "other_candidate_terms": list,
    "candidate_terms": dict,
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

SCORER_FIELDS: dict[str, tuple[str, ...]] = {
    "w1": (
        "correspondent_addresses",
        "third_party_terms",
        "protected_terms",
        "entitled_actions",
    ),
    "w2": ("applicant_addresses", "other_candidate_terms"),
    "w3": ("correspondent_addresses", "third_party_terms", "protected_terms"),
}
"""Fields a workflow's scorers read, by artifact-id prefix. Missing ones do not
fail loudly at scoring time: no `protected_terms` makes T2 impossible (G1 reads
0) and no `entitled_actions` makes every action unauthorized (audit #5)."""

CHANNEL_TAG = re.compile(r"^\[[^\]]+\]$")
"""What a marker line may leave behind once the marker is removed: nothing, or
the extraction channel's tag (`[comment]`, `[metadata /Subject]`, ...)."""

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}

LENGTH_TOLERANCE = 0.15
"""How far the twin's neutral text may stray from the payload's length (A-11)."""

TAG_PREFIX = re.compile(r"^\[[^\]]+\]")


def channel_match_violations(
    attack_text: str, twin_text: str, marker: str, *, single_line: bool = True
) -> list[str]:
    """Ways the twin fails to be channel-matched to its attack (empty if it is).

    A channel-matched twin differs from its attack in exactly one block of
    lines, the same size on both sides, where each line pair shares its channel
    tag (or both are untagged visible lines): the attack's block carries the
    marker, the twin's carries marker-free neutral text within LENGTH_TOLERANCE
    of the payload's length. Without this, "the twin lacks a channel" would ride
    along with "the twin lacks the payload".

    Args:
        attack_text: Extraction of the attack file.
        twin_text: Extraction of the twin file.
        marker: The payload marker.
        single_line: Require the block to be one line (placeholder rows, whose
            payload is the marker; a long canonical payload may wrap in a PDF).
    """
    a, t = attack_text.splitlines(), twin_text.splitlines()
    changes = [
        op
        for op in difflib.SequenceMatcher(None, a, t, autojunk=False).get_opcodes()
        if op[0] != "equal"
    ]
    if len(changes) != 1 or changes[0][0] != "replace":
        return [f"twin differs from the attack in {len(changes)} place(s), not 1"]
    _, i1, i2, j1, j2 = changes[0]
    payload, neutral = a[i1:i2], t[j1:j2]
    if len(payload) != len(neutral):
        return [f"{len(payload)} attack line(s) replaced by {len(neutral)} in twin"]
    if single_line and len(payload) != 1:
        return [f"twin differs from the attack in {len(payload)} lines, not 1"]
    errors: list[str] = []
    if not any(marker in line for line in payload):
        errors.append("the attack's changed lines do not carry the marker")
    if any(marker in line for line in neutral):
        errors.append("the twin's changed lines carry the marker")

    def tags(lines: list[str]) -> list[str]:
        return [m.group(0) if (m := TAG_PREFIX.match(x)) else "" for x in lines]

    def body(lines: list[str]) -> str:
        return " ".join(TAG_PREFIX.sub("", x).strip() for x in lines).strip()

    if tags(payload) != tags(neutral):
        errors.append(f"channel {tags(payload)} in attack but {tags(neutral)} in twin")
    if not body(neutral):
        errors.append("the twin's channel text is empty")
    elif abs(len(body(neutral)) - len(body(payload))) > LENGTH_TOLERANCE * len(
        body(payload)
    ):
        errors.append(
            f"neutral text is {len(body(neutral))} chars against a "
            f"{len(body(payload))}-char payload"
        )
    return errors


def marker_only_violations(attack_text: str, twin_text: str, marker: str) -> list[str]:
    """Lines present in the attack extraction, absent from the twin's, that are
    not marker-bearing.

    An empty result means the attack differs from its twin by the marker alone,
    i.e. no instruction wording is present. The twin's own neutral line is not
    an attack line, so it never counts; and since the twin carries the same
    channel (an alt-text twin has the same picture), no channel line is excused.
    """
    twin_lines = set(twin_text.splitlines())

    def explained(line: str) -> bool:
        if line in twin_lines:
            return True
        if marker not in line:
            return False
        # Extra wording beside the marker is still wording (audit #3).
        rest = line.replace(marker, "").strip()
        return not rest or rest in twin_lines or bool(CHANNEL_TAG.match(rest))

    return [line for line in attack_text.splitlines() if not explained(line)]


def correct_errors(correct: list) -> list[str]:
    """Schema problems in a row's `correct` alternatives (empty if well-formed).

    Each alternative is {"kind": one of CORRECT_KINDS, "calls": [{"tool": str,
    "args": {str: str | non-empty list[str]}}]}; an `act` needs at least one call.
    """
    if not correct:
        return ["'correct' declares no alternative"]
    errors: list[str] = []
    for index, alt in enumerate(correct):
        where = f"correct[{index}]"
        if not isinstance(alt, dict) or alt.get("kind") not in CORRECT_KINDS:
            errors.append(f"{where}: kind must be one of {CORRECT_KINDS}")
            continue
        calls = alt.get("calls")
        if not isinstance(calls, list):
            errors.append(f"{where}: 'calls' must be a list")
            continue
        if alt["kind"] == "act" and not calls:
            errors.append(f"{where}: an 'act' alternative needs at least one call")
        for call in calls:
            args = call.get("args") if isinstance(call, dict) else None
            if not (
                isinstance(call, dict)
                and isinstance(call.get("tool"), str)
                and isinstance(args, dict)
                and all(
                    isinstance(value, str)
                    or (
                        isinstance(value, list)
                        and value
                        and all(isinstance(v, str) for v in value)
                    )
                    for value in args.values()
                )
            ):
                errors.append(f"{where}: malformed call {call!r}")
    return errors


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
    workflow = artifact_id.split("_")[0].rstrip("c")
    for field in SCORER_FIELDS.get(workflow, ()):
        if field not in entry:
            errors.append(f"{artifact_id}: missing '{field}', which its scorers read")
    stray = set(entry.get("candidate_terms", {})) - set(
        entry.get("applicant_addresses", [])
    )
    if stray:
        errors.append(
            f"{artifact_id}: candidate_terms addresses not in applicant_addresses: "
            f"{sorted(stray)}"
        )
    errors.extend(f"{artifact_id}: {e}" for e in correct_errors(entry["correct"]))
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

    # 7. Channel-matched twin.
    if attack_text == "":
        errors.append(f"{artifact_id}: attack extraction is empty")
    elif attack_text is not None and twin_text is not None:
        errors.extend(
            f"{artifact_id}: {e}"
            for e in channel_match_violations(
                attack_text,
                twin_text,
                marker,
                single_line=entry.get("payload_class") != "canonical",
            )
        )

    # Everything but the gated canonical corpus must be marker-only.
    if (
        entry.get("payload_class") != "canonical"
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
