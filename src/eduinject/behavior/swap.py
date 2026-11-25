"""Message-swap effects (doc 14 §4): direct, laundered, interaction.

Pure over the rows of a `<name>.swap.csv` (feature rows with a `swap` column:
`tt`, `at`, `ta` or `aa`, the document at and after the swap, then the
hand-off's source). Intervals and tests belong to the caller.
"""

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from statistics import mean
from typing import Any, NamedTuple

CELLS = ("tt", "at", "ta", "aa")


class SwapEffects(NamedTuple):
    """One block's (or pair's) effects; `te == de + le + interaction`."""

    te: float
    """Total: Y_aa - Y_tt."""
    de: float
    """Direct: Y_at - Y_tt (attack document, twin's hand-off)."""
    le: float
    """Laundered: Y_ta - Y_tt (twin's document, attack-derived hand-off)."""
    interaction: float
    """Y_aa - Y_at - Y_ta + Y_tt."""


def block_effects(
    rows: Iterable[Mapping[str, Any]], outcome: str
) -> dict[tuple[str, int], SwapEffects]:
    """Effects on `outcome` per block, keyed `(artifact_id, epoch)`.

    A block missing any of its four cells, or with `outcome` undefined in one,
    is omitted.

    Args:
        rows: Swap feature rows of one experimental cell.
        outcome: A numeric feature column, e.g. `beh:attempt`.

    Raises:
        ValueError: Two rows share a block and swap cell, so the rows span more
            than one experimental cell; or a row's `swap` is no swap cell.
    """
    blocks: dict[tuple[str, int], dict[str, float]] = defaultdict(dict)
    for r in rows:
        key, cell = (str(r["artifact_id"]), int(r["epoch"])), str(r["swap"])
        if cell not in CELLS:
            raise ValueError(f"unknown swap cell {cell!r} in block {key}")
        if cell in blocks[key]:
            raise ValueError(f"two {cell} rows for block {key}: group by cell first")
        blocks[key][cell] = float(r[outcome])
    out = {}
    for key, y in blocks.items():
        if len(y) < len(CELLS) or any(math.isnan(v) for v in y.values()):
            continue
        out[key] = SwapEffects(
            te=y["aa"] - y["tt"],
            de=y["at"] - y["tt"],
            le=y["ta"] - y["tt"],
            interaction=y["aa"] - y["at"] - y["ta"] + y["tt"],
        )
    return out


def pair_effects(
    blocks: Mapping[tuple[str, int], SwapEffects],
) -> dict[str, SwapEffects]:
    """Each pair's effects: the mean over its epochs."""
    by_pair: dict[str, list[SwapEffects]] = defaultdict(list)
    for (artifact_id, _), effects in blocks.items():
        by_pair[artifact_id].append(effects)
    return {p: SwapEffects(*map(mean, zip(*e))) for p, e in by_pair.items()}
