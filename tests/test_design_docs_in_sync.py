"""Guards against the addendum and the code drifting apart."""

from pathlib import Path

from eduinject.config import DOC_VERSIONS
from eduinject.scorers import FLAG_PHRASES, W1_SPEC, W3_SPEC

DOCS = Path(__file__).resolve().parents[1] / "docs" / "design"


def _addendum() -> str:
    return (DOCS / "08_w1_w3_g1_tiers_addendum.md").read_text("utf-8")


def test_addendum_lists_exactly_the_flag_phrases_in_the_code() -> None:
    text = _addendum()
    block = text.split("```")[1]
    assert [p.strip() for p in block.strip().split(",")] == list(FLAG_PHRASES)


def test_addendum_states_the_entitlement_the_code_implements() -> None:
    text = _addendum()
    assert W3_SPEC.policy.entitlement["guardian"] == 1 and "T1 only" in text
    assert W1_SPEC.policy.entitlement["submitter"] == 2


def test_addendum_signed_state_is_consistent_across_the_repo() -> None:
    """The version the hash records, the status line and the signature rows agree.

    This does not check who signed, only that a signed status is backed by two
    filled signature rows, so the status cannot be flipped without them.
    """
    text = _addendum()
    assert "STATUS: SIGNED" in text
    assert DOC_VERSIONS["tiers_addendum_w1_w3"] == "1.0"
    rows = {
        cells[0]: cells
        for cells in (
            [c.strip() for c in line.strip("|").split("|")]
            for line in text.splitlines()
            if line.startswith("| ")
        )
        if len(cells) == 4
    }
    for role in ("Principal investigator", "Second reviewer"):
        _, name, initials, date = rows[role]
        assert name and initials and date, f"{role} row must be filled when status is SIGNED"


def test_reaffirmation_status_matches_its_signature_block() -> None:
    """While the re-affirmation's signature rows are blank its status must say
    UNSIGNED; once a project member fills them, it must not. Either way the status
    line and the block cannot disagree."""
    attestation = (DOCS / "attestations" / "data_provenance.md").read_text("utf-8")
    section = attestation.split("## 5. Re-affirmation")[1]
    cells = {
        c[0]: c[1]
        for c in ([x.strip() for x in line.strip("|").split("|")] for line in section.splitlines() if line.startswith("| "))
        if len(c) == 2
    }
    signed = all(cells.get(field) for field in ("Project member", "Date", "Signature"))
    status_line = next(line for line in section.splitlines() if "STATUS" in line)
    assert ("UNSIGNED" in status_line) is (not signed)


def test_flag_language_excludes_marker_echo() -> None:
    from eduinject.scorers import flag_language_by_stage

    result = {"h1": "ZZPAYLOADZZ", "h2": "no suspicious content", "final": "This looks suspicious.",
              "stage3_messages": []}
    assert flag_language_by_stage(result) == {"intake": False, "analysis": False, "final": True}
