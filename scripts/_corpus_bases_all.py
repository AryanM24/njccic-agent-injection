"""Every base scenario per workflow, in artifact order.

New (confirm) bases follow the first ones, so existing `artifact_id`s never
move. A module of its own because the per-workflow files import helpers from
`_corpus_bases`.
"""

import _corpus_bases as first
import _corpus_bases_w1
import _corpus_bases_w2
import _corpus_bases_w3
from _fixtures_common import Base

W1_BASES: list[Base] = [
    first.W1_B1,
    first.W1_B2,
    first.W1_B3,
    first.W1_B4,
    first.W1_B1P,
    *_corpus_bases_w1.NEW_BASES,
]
W2_BASES: list[Base] = [
    first.W2_B1,
    first.W2_B2,
    first.W2_B3,
    first.W2_B4,
    first.W2_B5,
    first.W2_B6,
    first.W2_B5P,
    *_corpus_bases_w2.NEW_BASES,
]
W3_BASES: list[Base] = [
    first.W3_B1,
    first.W3_B2,
    first.W3_B3,
    first.W3_B4,
    first.W3_B1P,
    *_corpus_bases_w3.NEW_BASES,
]
BASES = {"w1": W1_BASES, "w2": W2_BASES, "w3": W3_BASES}
