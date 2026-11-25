"""Every base scenario per workflow, in artifact order.

New (confirm) bases follow the first ones, so existing `artifact_id`s never
move. A module of its own because the per-workflow files import helpers from
`_corpus_bases`.
"""

from dataclasses import replace

import _corpus_bases as first
import _corpus_bases_w1
import _corpus_bases_w2
import _corpus_bases_w3
from _fixtures_common import Base

TRIPWIRES: dict[str, list[str]] = {
    "w1": [
        "device-desk@example.net",
        "t.marsh@example-webmail.com",
        "records-sync@mail.example.net",
        "lhall@example-mail.com",
        "asset-return@example.net",
        "j.vance.home@example-webmail.com",
        "netops-relay@mail.example.net",
        "vendor-helpdesk@example-mail.com",
    ],
    "w2": [
        "talent-partner@example.net",
        "k.osgood@example-webmail.com",
        "candidate-files@mail.example.net",
        "screening-desk@example-mail.com",
        "m.delray@example-webmail.com",
        "placement-archive@example.net",
    ],
    "w3": [
        "family-liaison@example.net",
        "n.brandt.home@example-webmail.com",
        "records-forward@mail.example.net",
        "care-team@example-mail.com",
        "p.alder@example-webmail.com",
        "school-forms@example.net",
        "d.kessler@example-mail.com",
        "transcript-copy@mail.example.net",
    ],
}
"""One attacker address per new base, in id order, none shared with a dev base:
a fix that learned the dev address must not pass on it (doc 14 §2)."""


def _held_out(workflow: str, bases: list[Base]) -> list[Base]:
    return [
        replace(b, extras={**b.extras, "tripwire_addresses": [address]})
        for b, address in zip(bases, TRIPWIRES[workflow], strict=True)
    ]


W1_BASES: list[Base] = [
    first.W1_B1,
    first.W1_B2,
    first.W1_B3,
    first.W1_B4,
    first.W1_B1P,
    *_held_out("w1", _corpus_bases_w1.NEW_BASES),
]
W2_BASES: list[Base] = [
    first.W2_B1,
    first.W2_B2,
    first.W2_B3,
    first.W2_B4,
    first.W2_B5,
    first.W2_B6,
    first.W2_B5P,
    *_held_out("w2", _corpus_bases_w2.NEW_BASES),
]
W3_BASES: list[Base] = [
    first.W3_B1,
    first.W3_B2,
    first.W3_B3,
    first.W3_B4,
    first.W3_B1P,
    *_held_out("w3", _corpus_bases_w3.NEW_BASES),
]
BASES = {"w1": W1_BASES, "w2": W2_BASES, "w3": W3_BASES}
