"""CI runs the Makefile targets, so a green `make check test-eduinject` is a green CI."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_ci_runs_make_targets() -> None:
    wf = (ROOT / ".github/workflows/eduinject.yml").read_text()
    runs = re.findall(r"^\s+run: (make .+)$", wf, re.MULTILINE)
    assert runs == ["make check", "make test-eduinject"]

    makefile = (ROOT / "Makefile").read_text()
    recipe = re.search(r"^check:\n((?:\t.*\n)+)", makefile, re.MULTILINE)
    assert recipe is not None
    assert "--fix" not in recipe.group(1)
    for line in recipe.group(1).splitlines():
        if "ruff format" in line:
            assert "--check" in line
