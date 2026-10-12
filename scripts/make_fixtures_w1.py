#!/usr/bin/env python3
"""Generate the W1 (IT help-desk ticket) attack/twin fixture corpus.

One clean twin per attack file; three base scenarios (see _corpus_bases.py).
Public builds are marker-only: the only injected content is the placeholder
marker `ZZPAYLOADZZ`, placed in one documented channel (release policy,
docs/design/05; README C3). Realistic wording is Tier 1 and lives in the
git-ignored `src/eduinject/corpus/payloads.py`; with that file present,
`--canonical` writes the real-payload corpus under the git-ignored
`corpus/canonical/` tree instead and never touches the public corpus.

Base scenarios live in `_corpus_bases.py`. Because the public payload is the same
marker for every goal, the four goals of a (file type, channel) cell are
byte-identical attack files in a public build; goal labels in the manifest become
distinguishing only in a canonical build. Re-running is idempotent.

Usage:
    python scripts/make_fixtures_w1.py              # public, marker-only
    python scripts/make_fixtures_w1.py --canonical  # gated; needs payloads.py
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _corpus_bases import BASES
from _fixtures_common import generate_workflow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--canonical",
        action="store_true",
        help="Build the gated real-payload corpus (needs payloads.py).",
    )
    args = parser.parse_args(argv)

    last = generate_workflow(
        workflow="w1",
        stem="ticket",
        bases=BASES["w1"],
        canonical=args.canonical,
        start_count=1,
    )
    generated = last - 1 + 1
    print(f"\n{generated} pairs generated, {generated * 2} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
