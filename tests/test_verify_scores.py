"""A-09: logged scores are re-derivable, and stale ones are refused."""

import importlib.util
import sys
from pathlib import Path

from inspect_ai import eval
from inspect_ai.log import read_eval_log, write_eval_log
from inspect_ai.model import get_model

from eduinject.analysis import StaleScore, stale_scores
from eduinject.task_w1 import eduinject_w1
from tests.test_task_e2e_w1_w3 import MOCK, w1_compromised

ANALYZE = Path(__file__).parent.parent / "scripts" / "analyze.py"


def _make_log(directory: Path) -> Path:
    log = eval(
        eduinject_w1(scope="read_write", isolated=True),
        model=get_model(MOCK, custom_outputs=w1_compromised),
        log_dir=str(directory),
        display="none",
        limit=1,
    )[0]
    assert log.status == "success", log.error
    return Path(log.location.removeprefix("file://"))


def _tamper(directory: Path) -> None:
    path = next(directory.glob("*.eval"))
    log = read_eval_log(str(path))
    assert log.samples
    score = next(
        s
        for s in (log.samples[0].scores or {}).values()
        if isinstance(s.value, int | float) and s.value in (0, 1)
    )
    assert isinstance(score.value, int | float)
    score.value = 1 - float(score.value)
    write_eval_log(log, str(path))


def test_fresh_log_verifies(tmp_path: Path) -> None:
    _make_log(tmp_path / "logs")
    assert stale_scores([str(tmp_path / "logs")]) == []


def test_tampered_score_is_reported(tmp_path: Path) -> None:
    _make_log(tmp_path / "logs")
    _tamper(tmp_path / "logs")
    stale = stale_scores([str(tmp_path / "logs")])
    assert len(stale) >= 1 and isinstance(stale[0], StaleScore)
    assert stale[0].logged != stale[0].recomputed


def test_analysis_refuses_stale_unless_allowed(tmp_path: Path) -> None:
    _make_log(tmp_path / "logs")
    _tamper(tmp_path / "logs")
    spec = importlib.util.spec_from_file_location("analyze_script", ANALYZE)
    assert spec and spec.loader
    analyze = importlib.util.module_from_spec(spec)
    sys.modules["analyze_script"] = analyze
    spec.loader.exec_module(analyze)
    logs, out = str(tmp_path / "logs"), str(tmp_path / "out")
    assert analyze.main(["report", logs, "--out", out]) == 4
    assert not (tmp_path / "out" / "rows.csv").exists()
    assert analyze.main(["report", logs, "--out", out, "--allow-stale"]) == 0
