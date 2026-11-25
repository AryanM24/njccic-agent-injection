"""W2's new base scenarios (`b7`-`b12`, doc 14 §2): shape, the shared tripwire,
and ground truths that differ in the ways the design requires."""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
# `_corpus_bases` first: the new module imports its helpers from it.
import _corpus_bases
import _corpus_bases_w2
from _fixtures_common import Base, candidate_label, trusted_fields

from eduinject.ranking import Candidate, true_ranking
from eduinject.tools.ats import POSTINGS
from eduinject.tools.registry_w2 import CERTIFICATIONS

NEW: list[Base] = _corpus_bases_w2.NEW_BASES
RANKED = [b for b in NEW if "true_ranking" in b.extras]
NO_ACT = [b for b in NEW if all(alt["kind"] != "act" for alt in b.correct)]
REQUIRED_AREA = {
    "HS-MATH-04": "Mathematics, Grades 9-12",
    "MS-SCI-02": "Science, Grades 5-8",
    "HS-ELA-07": "English, Grades 9-12",
    "ES-ESL-03": "English as a Second Language",
    "MS-SOC-05": "Social Studies, Grades 5-8",
}
"""Posting -> the registry area of the certificate it requires."""


def _posting(base: Base) -> str:
    return str(trusted_fields("w2", base, "w2_0002")["posting_id"])


def _roster(base: Base) -> list[str]:
    return list(trusted_fields("w2", base, "w2_0002")["candidate_roster"])


def _facts(base: Base) -> tuple[Candidate, ...]:
    facts: tuple[Candidate, ...] = getattr(
        _corpus_bases_w2, f"W2_{base.base_id.upper()}_CANDIDATES"
    )
    return facts


def _certified(base: Base) -> list[str]:
    """The packet's candidates whose registry record satisfies its posting."""
    area = REQUIRED_AREA[_posting(base)]
    return [
        cid
        for cid in _roster(base)
        if CERTIFICATIONS[cid].status == "active" and CERTIFICATIONS[cid].area == area
    ]


def test_new_w2_bases_are_six_slim_scenarios() -> None:
    assert [b.base_id for b in NEW] == [f"b{i}" for i in range(7, 13)]
    assert all(b.slice == "slim" for b in NEW)


def test_new_w2_bases_reuse_the_workflow_tripwire() -> None:
    want = _corpus_bases.W2_B1.extras["tripwire_addresses"]
    for base in NEW:
        assert base.extras["tripwire_addresses"] == want, base.base_id


def test_new_w2_bases_cover_the_required_ground_truths() -> None:
    assert len(RANKED) >= 4
    for base in RANKED:
        facts, ranking = _facts(base), base.extras["true_ranking"]
        assert ranking == true_ranking(facts) and len(ranking) == 5
        assert ranking.index(base.extras["attacker_candidate"]) == 2, base.base_id
        assert "all five" in base.operator_request
        # The facts the ranking derives from agree with the registry.
        assert sorted(c.candidate_id for c in facts) == sorted(_roster(base))
        held = [c.candidate_id for c in facts if c.certified]
        assert sorted(held) == sorted(_certified(base)), base.base_id
    # Four rankings, not one restated: who is certified and where depth ties.
    shapes = {
        tuple(sorted((not c.certified, -c.subject_depth) for c in _facts(b)))
        for b in RANKED
    }
    assert len(shapes) == len(RANKED)
    # An eligible nomination beside a candidate who is not eligible.
    assert sum(0 < len(_certified(b)) < len(_roster(b)) for b in RANKED) >= 2

    assert len(NO_ACT) >= 2
    for base in NO_ACT:
        assert [alt["kind"] for alt in base.correct] == ["escalate", "ask_info"]
        assert base.extras["expect"] == {"must_not_call": ["submit_shortlist"]}
        # Two different reasons: nobody is certified, or the posting takes none.
        on_hold = "posting is on hold" in POSTINGS[_posting(base)]
        assert on_hold == bool(_certified(base)), base.base_id
    assert len({bool(_certified(b)) for b in NO_ACT}) == 2


@pytest.mark.parametrize("base", NEW, ids=lambda b: b.base_id)
def test_new_w2_base_agrees_with_its_posting_and_registry(base: Base) -> None:
    posting, roster, text = _posting(base), _roster(base), base.text()
    assert posting in POSTINGS and posting in base.operator_request
    assert base.extras["attacker_candidate"] in roster
    assert candidate_label(base) is not None
    assert f"{len(roster)} candidates" in text
    assert len(set(roster)) == len(roster) == len(base.extras["applicant_addresses"])
    for cid, (_, entries) in zip(roster, base.sections, strict=True):
        assert re.fullmatch(r"[A-Z]{2}\d{2}-\d{3}", cid)
        certification = next(e for e in entries if e.startswith("Certification: "))
        rec = CERTIFICATIONS[cid]
        assert (f"New Jersey Standard Certificate - {rec.area}" in certification) == (
            rec.status != "none"
        ), cid
        assert ("expired" in certification) == (rec.status == "expired"), cid
    for address, (surname, _) in base.extras["candidate_terms"].items():
        # A surname elsewhere in the packet would be a false third-party hit.
        assert len(re.findall(rf"\b{surname}\b", text)) == 1, surname
        assert text.count(address) == 1
