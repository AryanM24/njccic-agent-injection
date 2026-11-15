#!/usr/bin/env python3
"""Estimate sweep cost per cell from token statistics in existing logs.

The one cost path: `run_sweep.py --dry-run` calls `estimate_usd` here. With no
logs to measure it falls back to a documented default (the first edition's
pilot) and says so, rather than presenting a guess as a measurement. A model
whose price is still TODO in `configs/models.json` has no estimate.
"""

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from inspect_ai.log import list_eval_logs, read_eval_log

from eduinject.models import ModelEntry, load_models

TOKENS_PER_PAIR = (23_000, 9_500)
"""(input, output) tokens for one attack+twin sample at relay_stages=0, from the
first edition's pilot (RUNNING.md). Used only when no log gives real numbers."""


class TokenStats(NamedTuple):
    """Mean tokens per sample over the logs matched."""

    n_samples: int
    mean_in: float
    mean_out: float


def token_stats(
    log_dirs: Sequence[str | Path], cell: Mapping[str, Any] | None = None
) -> TokenStats | None:
    """Mean per-sample tokens (all stages, all models) over logs under `log_dirs`.

    `cell` keeps only logs whose eval metadata matches every given key. Returns
    None when no matching sample recorded usage.
    """
    tin = tout = n = 0
    for directory in log_dirs:
        for info in list_eval_logs(str(directory)):
            log = read_eval_log(info)
            meta = log.eval.metadata or {}
            if cell and any(meta.get(k) != v for k, v in cell.items()):
                continue
            for sample in log.samples or []:
                if not sample.model_usage:
                    continue
                n += 1
                tin += sum(u.input_tokens for u in sample.model_usage.values())
                tout += sum(u.output_tokens for u in sample.model_usage.values())
    return TokenStats(n, tin / n, tout / n) if n else None


def estimate_usd(
    n_samples: int,
    twin_only: bool,
    relay_stages: int,
    entry: ModelEntry,
    tokens: TokenStats | None,
) -> float | None:
    """USD for `n_samples` runs, or None when the entry's prices are TODO.

    Measured `tokens` are used as given (the logs already reflect their cell).
    The fallback scales by (3 + relay_stages) / 3 and halves for twin-only.
    """
    if entry.todo:
        return None
    if tokens is not None:
        tin, tout = tokens.mean_in, tokens.mean_out
    else:
        scale = (3 + relay_stages) / 3 * (0.5 if twin_only else 1.0)
        tin, tout = (t * scale for t in TOKENS_PER_PAIR)
    return n_samples * (tin * entry.price_in + tout * entry.price_out) / 1e6


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", nargs="*", default=[])
    parser.add_argument("--model-preset", required=True)
    parser.add_argument("--relay-stages", type=int, default=0)
    parser.add_argument("--samples", type=int, default=1, help="Samples to price.")
    parser.add_argument("--twin-only", action="store_true")
    args = parser.parse_args(argv)
    entry = load_models()[args.model_preset]
    tokens = token_stats(args.log_dir)
    usd = estimate_usd(args.samples, args.twin_only, args.relay_stages, entry, tokens)
    basis = f"{tokens.n_samples} logged samples" if tokens else "default pilot tokens"
    print("price unknown (TODO)" if usd is None else f"${usd:,.2f} ({basis})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
