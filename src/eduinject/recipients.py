"""Parsing the recipients of an outbound message.

Shared by the G1 scorer and the tool guard, so the guard blocks exactly the
addresses the scorer would classify. A leaf module: it imports nothing from
the package.
"""

import re

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
