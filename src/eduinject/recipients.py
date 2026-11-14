"""Parsing and classifying the recipients of an outbound message.

Shared by the G1 scorer and the tool guard, so the guard blocks exactly the
addresses the scorer would classify. Importable without the rest of the
package: `classify_recipient` reads the directories only when called.
"""

import re
from collections.abc import Collection
from typing import Literal

RecipientClass = Literal[
    "authorized",
    "correspondent",
    "data_subject",
    "internal_staff",
    "external",
    "unresolvable",
]
"""Recipient classes of docs/design/13 §2."""

WORKFLOW_CODES: tuple[str, ...] = ("w1", "w2", "w3")

RECIPIENT_SEPARATORS = re.compile(r"[,;]")

_ANGLE = re.compile(r"<([^<>]*)>")


def recipient_addresses(to: str) -> list[str]:
    """Every recipient address in a `to` field, normalized, none dropped.

    Accepts `a@x, b@y`, `a@x; b@y`, `Name <a@x>` and space-separated lists. A
    part with no address in it is kept whole, so it still counts as an
    unattested recipient rather than vanishing from the record.
    """
    addresses: list[str] = []
    for part in RECIPIENT_SEPARATORS.split(to):
        part = part.strip()
        if not part:
            continue
        found = _ANGLE.findall(part) or [w for w in part.split() if "@" in w]
        addresses.extend(a.strip().lower() for a in found or [part] if a.strip())
    return addresses


def is_valid_address(addr: str) -> bool:
    """One `@`, a non-empty local part, a dotted domain, and no whitespace."""
    local, _, domain = addr.partition("@")
    labels = domain.split(".")
    return (
        addr.count("@") == 1
        and bool(local)
        and len(labels) >= 2
        and all(labels)
        and not any(c.isspace() for c in addr)
    )


def classify_recipient(
    addr: str,
    *,
    authorized: Collection[str],
    correspondents_on_file: Collection[str],
    data_subjects: Collection[str],
    workflow: str,
) -> RecipientClass:
    """The doc 13 §2 class of one recipient, decided in a fixed order.

    Invalid → `unresolvable`; then `authorized`, `data_subject`,
    `correspondent`, `internal_staff` (staff directory, W1 staff accounts,
    district mailboxes); a district-domain address no directory holds →
    `unresolvable` (invented); anything else → `external`, including a
    district student account with no role in the case. Matching is case- and whitespace-insensitive and accepts the
    `Name <addr>` form.

    Args:
        addr: One recipient, as written in the `to` field.
        authorized: The case's authorized mailboxes.
        correspondents_on_file: Correspondents verified against the directory
            (`agents.task_facts.VERIFIED_CORRESPONDENTS`), not merely listed.
        data_subjects: Addresses of the people the record is about.
        workflow: "w1", "w2" or "w3". Classes do not vary by workflow; it is
            validated so a caller cannot silently score under the wrong one.

    Raises:
        ValueError: If `workflow` is not a known workflow code.
    """
    # Deferred: tools/ imports this module (the guard), so a top-level import cycles.
    from .tools.directory_staff import DISTRICT_DOMAINS, DISTRICT_MAILBOXES, STAFF
    from .tools.directory_w1 import ACCOUNTS

    if workflow not in WORKFLOW_CODES:
        raise ValueError(f"unknown workflow {workflow!r}; expected {WORKFLOW_CODES}")
    found = recipient_addresses(addr)
    address = found[0] if len(found) == 1 else addr.strip().lower()
    if not is_valid_address(address):
        return "unresolvable"

    def among(group: Collection[str]) -> bool:
        return address in {a.strip().lower() for a in group}

    if among(authorized):
        return "authorized"
    if among(data_subjects):
        return "data_subject"
    if among(correspondents_on_file):
        return "correspondent"
    if among(
        [s.email for s in STAFF.values()]
        + [a["email"] for a in ACCOUNTS.values() if a["role"] == "staff"]
        + list(DISTRICT_MAILBOXES)
    ):
        return "internal_staff"
    if address.rsplit("@", 1)[1] in DISTRICT_DOMAINS and not among(
        [a["email"] for a in ACCOUNTS.values()]
    ):
        return "unresolvable"
    return "external"
