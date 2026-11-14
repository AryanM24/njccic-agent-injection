#!/usr/bin/env python3
"""Recompute every logged score with the current scorers and report mismatches.

    verify_scores.py LOG_DIR...

Exits 0 if every score reproduces, 4 (listing each) if any is stale. Nothing
here contacts a model. `analyze.py` runs the same check before analysing.
"""

import argparse
import sys

from eduinject.analysis import stale_scores


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_dirs", nargs="+")
    stale = stale_scores(parser.parse_args(argv).log_dirs)
    for s in stale:
        print(
            f"stale: {s.log} sample {s.sample_id} epoch {s.epoch} {s.score}: "
            f"logged {s.logged} != recomputed {s.recomputed}"
        )
    print(f"{len(stale)} stale score(s)")
    return 4 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
