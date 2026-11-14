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
