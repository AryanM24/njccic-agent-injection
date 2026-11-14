"""Shared fixtures for the eduinject tests."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GENERATORS = [
    "make_fixtures_v2.py",
    "make_fixtures_w1.py",
    "make_fixtures_w3.py",
    "make_fixtures_controls.py",
]


def skip_if_gated_payloads_stale() -> None:
    """Skip a test that needs VALID gated payloads when the workstation's
    `payloads.py` breaks the C1 contract. Never prints payload text."""
    from eduinject import corpus

    table = corpus._gated_table()
    if isinstance(table, dict) and corpus.payload_problems(table):
        pytest.skip("payloads.py predates the C1 contract")


@pytest.fixture(scope="session")
def generated_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A freshly generated public corpus (holding `corpus/`), so tests of the
    generators' output do not depend on the committed one."""
    root = tmp_path_factory.mktemp("corpus")
    for script in GENERATORS:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), "--out-root", str(root)],
            check=True,
            capture_output=True,
            env={"PYTHONPATH": str(ROOT / "src"), "PATH": ""},
        )
    return root
