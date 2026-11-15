"""§8 end-to-end smoke: every Phase A script runs on one real mockllm log."""

import csv
import os
import subprocess
import sys
from pathlib import Path

import pytest
from inspect_ai import eval
from inspect_ai.model import get_model

from eduinject.task_w1 import eduinject_w1
from tests.helpers import MOCK, w1_compromised

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _tree(root: Path) -> set[Path]:
    return {p for p in root.rglob("*") if p.is_file()} if root.exists() else set()


def test_every_phase_a_script_runs_on_a_mock_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import behavior_models
    import build_features
    import risk_report

    logs = tmp_path / "logs"
    runs = logs / "runs"
    (log,) = eval(
        eduinject_w1(scope="read_write", isolated=True, relay_stages=1, gate=True),
        model=get_model(MOCK, custom_outputs=w1_compromised),
        log_dir=str(runs),
        display="none",
        limit=2,
    )
    assert log.status == "success", log.error
    repo_logs_before = _tree(ROOT / "logs")

    def script(name: str, *args: str) -> str:
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / name), *args],
            cwd=tmp_path,
            env={k: v for k, v in os.environ.items() if k != "BY"},
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"{name} {args}: {proc.stderr[-2000:]}"
        return proc.stdout

    # These three pin OUT to the repository's logs/; point that at this test's.
    for module in (build_features, behavior_models, risk_report):
        monkeypatch.setattr(module, "LOGS", logs)

    r = str(runs)
    script("verify_scores.py", r)
    script(
        "audit_traces.py",
        "--log-dir",
        r,
        "--out",
        str(logs / "audit"),
        "--runs",
        "both",
    )
    features = logs / "features" / "smoke.csv"
    assert build_features.main(["--log-dir", r, "--out", str(features)]) == 0
    with features.open(encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 4  # two pairs, attack and twin
    for model in ("chain", "halflife", "predict", "profiles"):
        argv = [
            model,
            "--features",
            str(features),
            "--out",
            str(logs / "behavior"),
            "--n-boot",
            "20",
        ]
        assert behavior_models.main(argv) == 0, model
    argv = [
        "--features",
        str(features),
        "--out",
        str(logs / "risk"),
        "--n-boot",
        "20",
        "--n-draws",
        "20",
    ]
    assert risk_report.main(argv) == 0
    script("analyze.py", "report", r, "--out", str(logs / "analysis"), "--n-boot", "20")
    script("analyze.py", "trace-check", r, "--out", str(logs / "trace-check"))
    script(
        "analyze.py",
        "power",
        "--base-rate",
        "0.2",
        "--pairs",
        "10",
        "--epochs",
        "1",
        "--n-sim",
        "20",
    )
    script("rescore.py", "--log-dir", r, "--out-dir", str(logs / "rescored"))
    script("verify_scores.py", str(logs / "rescored"))
    for split in ([], ["--split", "dev"], ["--split", "confirm"]):
        assert "| --- |" in script("paired_outcomes.py", r, *split)
        assert "| --- |" in script("exfil_recipients.py", r, *split)
    script("estimate_cost.py", "--log-dir", r, "--model-preset", "luna")
    script(
        "run_sweep.py",
        "--workflow",
        "w1",
        "--model",
        MOCK,
        "--log-dir",
        str(logs / "sweep"),
        "--dry-run",
    )

    for expected in (
        "audit/runs.csv",
        "audit/violations.csv",
        "features/smoke.csv",
        "features/smoke.roles.json",
        "behavior/chain.csv",
        "behavior/halflife.csv",
        "behavior/predictors.csv",
        "risk/risk.csv",
        "risk/frontier.csv",
        "analysis/rates.csv",
    ):
        assert (logs / expected).is_file(), expected
    assert list((logs / "behavior").glob("profile_*.md"))
    assert list((logs / "rescored").rglob("*.eval"))
    # Outputs land under the given logs dir only: nothing beside it in the
    # working directory, nothing new in the repository's logs/.
    assert [p.name for p in tmp_path.iterdir()] == ["logs"]
    assert _tree(ROOT / "logs") == repo_logs_before
