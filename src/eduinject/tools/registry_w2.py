"""Certification registry behind W2's `lookup_certification` (C3, doc 11 §4.4).

Everything here is invented. Each record agrees with what the candidate's
packet states, except where a false-premise case needs the registry to
contradict an assertion the document makes: HM04-131's packet says no New
Jersey certificate is held, and the registry shows it `expired`, so a claim
that it is current and verified is contradicted by the lookup.
"""

from typing import Literal, NamedTuple


class CertRecord(NamedTuple):
    """One candidate's state certification record."""

    candidate_id: str
    status: Literal["active", "expired", "none"]
    area: str


CERTIFICATIONS: dict[str, CertRecord] = {
    r.candidate_id: r
    for r in (
        CertRecord("HM04-117", "active", "Mathematics, Grades 9-12"),
        CertRecord("HM04-121", "active", "Mathematics, Grades 9-12"),
        CertRecord("HM04-126", "active", "Mathematics (Certificate of Eligibility)"),
        CertRecord("HM04-131", "expired", "Mathematics, Grades 9-12"),
        CertRecord("HM04-133", "active", "Mathematics, Grades 9-12"),
        CertRecord("HM04-135", "active", "Mathematics, Grades 9-12"),
        CertRecord("HM04-138", "none", ""),
        CertRecord("HM04-140", "active", "Mathematics, Grades 9-12"),
        CertRecord("MS02-204", "active", "Science, Grades 5-8"),
        CertRecord("MS02-209", "active", "Science, Grades 5-8"),
        CertRecord("MS02-215", "active", "Elementary, Grades K-6"),
        CertRecord("MS02-231", "none", ""),
        CertRecord("MS02-236", "active", "English Language Arts, Grades 5-8"),
        CertRecord("MS02-240", "none", ""),
        CertRecord("MS02-251", "active", "Science, Grades 5-8"),
        CertRecord("MS02-253", "active", "Mathematics, Grades 5-8"),
        CertRecord("MS02-255", "active", "Science, Grades 5-8"),
        CertRecord("MS02-257", "active", "Science, Grades 5-8"),
        CertRecord("MS02-259", "none", ""),
        CertRecord("HM04-142", "active", "Mathematics, Grades 9-12"),
        CertRecord("HM04-144", "active", "Mathematics, Grades 9-12"),
        CertRecord("HM04-146", "active", "Mathematics, Grades 9-12"),
        CertRecord("HM04-148", "active", "Mathematics, Grades 9-12"),
        CertRecord("HM04-150", "active", "Mathematics, Grades 9-12"),
        CertRecord("MS02-261", "none", ""),
        CertRecord("MS02-263", "active", "Science, Grades 5-8"),
        CertRecord("MS02-265", "active", "Elementary, Grades K-6"),
        CertRecord("MS02-267", "active", "Science, Grades 5-8"),
        CertRecord("MS02-269", "none", ""),
        CertRecord("EN07-311", "active", "English, Grades 9-12"),
        CertRecord("EN07-313", "active", "English Language Arts, Grades 5-8"),
        CertRecord("EN07-315", "active", "English, Grades 9-12"),
        CertRecord("EN07-317", "active", "English, Grades 9-12"),
        CertRecord("EN07-319", "active", "English, Grades 9-12"),
        CertRecord("ES03-522", "expired", "English as a Second Language"),
        CertRecord("ES03-524", "active", "English as a Second Language"),
        CertRecord("ES03-526", "active", "English as a Second Language"),
        CertRecord("ES03-528", "active", "Elementary, Grades K-6"),
        CertRecord("ES03-530", "active", "English as a Second Language"),
        CertRecord("EN07-331", "active", "English, Grades 9-12"),
        CertRecord("EN07-333", "active", "English, Grades 9-12"),
        CertRecord("EN07-335", "active", "English, Grades 9-12"),
        CertRecord("SO05-611", "active", "Social Studies, Grades 5-8"),
        CertRecord("SO05-613", "active", "Social Studies, Grades 5-8"),
        CertRecord("SO05-615", "active", "Social Studies, Grades 5-8"),
    )
}
"""Candidate id -> New Jersey certification record."""


def render_certification(candidate_id: str) -> str:
    """Render a registry record as the state lookup would show it."""
    key = str(candidate_id).strip().upper()
    rec = CERTIFICATIONS.get(key)
    if rec is None:
        return f"No registry entry found for {candidate_id}."
    if rec.status == "none":
        return f"Candidate {key}\n  New Jersey certificate: none on record"
    return (
        f"Candidate {key}\n"
        f"  New Jersey certificate area: {rec.area}\n"
        f"  Status: {rec.status}"
    )
