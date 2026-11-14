"""Guards against the addendum and the code drifting apart."""

import re
from pathlib import Path
from typing import get_args

from eduinject.config import DOC_VERSIONS
from eduinject.recipients import RecipientClass
from eduinject.scorers import FLAG_PHRASES

DOCS = Path(__file__).resolve().parents[1] / "docs" / "design"


DOC_FILES = {
    "positioning_statement": "01_positioning_statement.md",
    "workflow_selection": "02_workflow_selection_and_grounding_corpus.md",
    "threat_model": "03_threat_model.md",
    "goal_taxonomy": "04_attacker_goal_taxonomy.md",
    "release_policy": "05_dual_use_and_release_policy.md",
    "thresholds_appendix": "07_thresholds_appendix.md",
    "tiers_addendum_w1_w3": "08_w1_w3_g1_tiers_addendum.md",
    "analysis_plan": "09_analysis_plan.md",
    "second_edition_addendum": "10_second_edition_addendum.md",
    "study_design": "11_study_design.md",
    "v1_audit": "12_v1_audit.md",
    "recipient_policy": "13_recipient_policy_addendum.md",
}
"""The design document each `DOC_VERSIONS` key records."""


def test_every_doc_version_names_a_document_whose_header_carries_it() -> None:
    """A key added to `DOC_VERSIONS` needs a file here, and a version bumped in
    one place must be bumped in the other. The header is the text before the
    first `## ` section."""
    assert set(DOC_FILES) == set(DOC_VERSIONS)
    for key, version in DOC_VERSIONS.items():
        path = DOCS / DOC_FILES[key]
        assert path.is_file(), f"{key}: {path} missing"
        header = path.read_text("utf-8").split("\n## ")[0]
        assert version in header, f"{key}: {path.name} header lacks {version}"


def _addendum() -> str:
    return (DOCS / "08_w1_w3_g1_tiers_addendum.md").read_text("utf-8")


def test_addendum_lists_exactly_the_flag_phrases_in_the_code() -> None:
    text = _addendum()
    block = text.split("```")[1]
    assert [p.strip() for p in block.strip().split(",")] == list(FLAG_PHRASES)


def test_recipient_policy_addendum_matches_the_code() -> None:
    """Doc 13 names every recipient class the code assigns, at the recorded
    version (it amends 08 §2's entitlement tables, which are left as signed)."""
    text = (DOCS / "13_recipient_policy_addendum.md").read_text("utf-8")
    assert f"v{DOC_VERSIONS['recipient_policy']}" in text
    for name in get_args(RecipientClass):
        assert f"`{name}`" in text


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
        assert name and initials and date, (
            f"{role} row must be filled when status is SIGNED"
        )


def test_reaffirmation_status_matches_its_signature_block() -> None:
    """While the re-affirmation's signature rows are blank its status must say
    UNSIGNED; once a project member fills them, it must not. Either way the status
    line and the block cannot disagree."""
    attestation = (DOCS / "attestations" / "data_provenance.md").read_text("utf-8")
    section = attestation.split("## 5. Re-affirmation")[1]
    cells = {
        c[0]: c[1]
        for c in (
            [x.strip() for x in line.strip("|").split("|")]
            for line in section.splitlines()
            if line.startswith("| ")
        )
        if len(c) == 2
    }
    signed = all(cells.get(field) for field in ("Project member", "Date", "Signature"))
    status_line = next(line for line in section.splitlines() if "STATUS" in line)
    assert ("UNSIGNED" in status_line) is (not signed)


def test_flag_language_excludes_marker_echo() -> None:
    from eduinject.scorers import flag_language_by_stage

    result = {
        "h1": "ZZPAYLOADZZ",
        "h2": "no suspicious content",
        "final": "This looks suspicious.",
        "stage3_messages": [],
    }
    assert flag_language_by_stage(result) == {
        "intake": False,
        "analysis": False,
        "final": True,
    }


_FINAL_STATUS = re.compile(
    r"fixed|partially fixed|won't fix \(.+\)|needs a decision from me"
)


def test_audit_rows_have_final_status() -> None:
    """Every doc 12 row ends in one final status, and every test it names exists."""
    tests = {
        m
        for f in Path(__file__).parent.rglob("*.py")
        for m in re.findall(r"def (test_\w+)", f.read_text("utf-8"))
    }
    rows = [
        [c.strip() for c in line.strip().strip("|").split("|")]
        for line in (DOCS / DOC_FILES["v1_audit"]).read_text("utf-8").splitlines()
        if line.startswith("| A-")
    ]
    assert len(rows) == 86
    for row in rows:
        assert _FINAL_STATUS.fullmatch(row[-1]), f"{row[0]}: {row[-1]!r}"
        missing = set(re.findall(r"`(test_\w+)`", row[-2])) - tests
        assert not missing, f"{row[0]} names missing tests {missing}"
