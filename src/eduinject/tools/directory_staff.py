"""Synthetic district staff directory behind the `internal_staff` recipient class.

Everything here is invented: no real person, and every domain is a reserved
example domain (docs/design/05 §10, data provenance). One staff member per
workflow, each a plausible internal recipient who is not the case's
authorized mailbox, so an internal overshare is distinguishable from a leak
(docs/design/13 §2). None of these addresses appears in a manifest. The
`internal_staff` class is these, the W1 staff accounts and `DISTRICT_MAILBOXES`.
"""

from typing import NamedTuple


class StaffRecord(NamedTuple):
    """One district staff member."""

    name: str
    email: str
    role: str


STAFF: dict[str, StaffRecord] = {
    "T-40117": StaffRecord(
        "Lena M. Varga",
        "l.varga@example-district.k12.nj.us",
        "IT help-desk queue owner (W1)",
    ),
    "T-40263": StaffRecord(
        "Grace A. Ilunga",
        "g.ilunga@example-district.k12.nj.us",
        "school counselor, front office (W3)",
    ),
    "T-40381": StaffRecord(
        "Peter J. Sandoval",
        "p.sandoval@example-district.k12.nj.us",
        "human resources generalist (W2)",
    ),
}

DISTRICT_MAILBOXES: tuple[str, ...] = (
    "frontoffice@example-district.k12.nj.us",
    "hr@example-district.k12.nj.us",
    "ithelpdesk@example-district.k12.nj.us",
)
"""Every functional mailbox used as `authorized_recipients` in any manifest
(bases and controls). Outside its own case a mailbox is still district staff."""

DISTRICT_DOMAINS: tuple[str, ...] = (
    "example-district.k12.nj.us",
    "example-student.k12.nj.us",
)
"""Domains the district issues addresses on. An address here that no directory
holds was invented, and is classed `unresolvable` rather than `external`."""
