"""Pinned independent variables and the run config hash.

The extraction stack is an *independent variable*, not an implementation detail:
which parser versions are installed determines which concealment channels are
even visible to the intake agent. A silent parser upgrade mid-study would change
the measurement without changing the code, so the pins are asserted (raising) at
construction time and folded into a hash recorded on every run.
"""

import hashlib
import json
from importlib.metadata import PackageNotFoundError, version
from typing import Any

EXTRACTION_PINS: dict[str, str] = {
    "pypdf": "6.15.0",
    "python-docx": "1.2.0",
    # python-docx parses OOXML through lxml, so lxml's version is part of the
    # extraction surface even though nothing imports it directly.
    "lxml": "6.1.1",
}
"""Distribution name -> exact installed version of the extraction stack."""

DOC_VERSIONS: dict[str, str] = {
    "positioning_statement": "1.1",
    "workflow_selection": "1.1",
    "threat_model": "1.0",
    "goal_taxonomy": "1.3",
    "release_policy": "1.0",
    "thresholds_appendix": "1.0",
    "tiers_addendum_w1_w3": "1.0",
    "analysis_plan": "1.0",
}
"""Versions of the design documents in force, mirroring `docs/design/`.

Every document that binds the experiment is listed, not only the ones the code
reads: the threat model and goal taxonomy are amendable by version increment
(threat model §11, goal taxonomy §16), and results produced under a superseded
version are reported under that version rather than silently reinterpreted. The
dict is folded into `config_hash` so the document set behind any figure is
recoverable from the log alone.
"""


def assert_extraction_pinned() -> None:
    """Verify every pinned extraction package matches what is installed.

    Raises:
        RuntimeError: If a pinned package is missing or installed at a
            different version. This is a confound guard: drift in the
            extraction stack silently changes which concealment channels are
            visible, so it must fail the run rather than warn.
    """
    for package, pinned in EXTRACTION_PINS.items():
        try:
            installed = version(package)
        except PackageNotFoundError as ex:
            raise RuntimeError(
                f"extraction stack drift: {package} is pinned at {pinned} "
                "but is not installed"
            ) from ex
        if installed != pinned:
            raise RuntimeError(
                f"extraction stack drift: {package} is pinned at {pinned} "
                f"but {installed} is installed"
            )


def config_hash(**run_params: Any) -> str:
    """Hash the pinned config plus this run's parameters.

    Args:
        **run_params: Run-level independent variables (scope, isolation,
            model, prompt version, ...).

    Returns:
        The first 16 hex characters of the sha256 digest.
    """
    payload = json.dumps(
        {
            "extraction": EXTRACTION_PINS,
            "docs": DOC_VERSIONS,
            "run": dict(sorted(run_params.items())),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
