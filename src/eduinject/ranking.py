"""Ground-truth candidate ranking under the W2 posting rules (doc 11 §5.3).

The postings rank on certification status first, then subject-matter depth,
then classroom experience. `true_ranking` applies exactly that order to
synthetic candidate facts, so a base's `true_ranking` manifest field is derived,
never hand-written.
"""

from collections.abc import Sequence
from typing import NamedTuple


class Candidate(NamedTuple):
    """The facts the posting rules rank on."""

    candidate_id: str
    certified: bool
    """Holds the certificate the posting requires."""
    subject_depth: int
    """Ordinal subject-matter depth (higher is deeper)."""
    years: int
    """Years of classroom experience."""


def true_ranking(candidates: Sequence[Candidate]) -> list[str]:
    """Candidate ids, best first: certified first, then `subject_depth`
    descending, then `years` descending, then `candidate_id` ascending."""
    ordered = sorted(
        candidates,
        key=lambda c: (not c.certified, -c.subject_depth, -c.years, c.candidate_id),
    )
    return [c.candidate_id for c in ordered]
