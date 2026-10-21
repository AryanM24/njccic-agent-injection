"""Post-run analysis: pure functions on synthetic rows, then real mock logs."""

import csv
import sys
from pathlib import Path
from typing import Any

import pytest
from inspect_ai import eval
from inspect_ai.model import get_model

from eduinject.analysis import (
    cohen_kappa,
    dedupe,
    denominators,
    epoch_spread,
    flatten_scores,
    is_null,
    load_rows,
    paired_difference,
    rate_with_ci,
    saturated,
    stratified_sample,
)
from eduinject.task_w1 import eduinject_w1
from tests.test_task_e2e_w1_w3 import w1_benign, w1_compromised

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze import main as analyze_main


def _row(pair: str, epoch: int, value: float | None, **cell: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "model": "m",
        "host": "",
        "reasoning_effort": None,
        "workflow": "w1",
        "corpus": "c",
        "benign_only": False,
        "controls": False,
        "scope": "read_write",
        "isolated": True,
        "config_hash": "h",
        "created": "t0",
        "sample_id": pair,
        "artifact_id": pair,
        "epoch": epoch,
        "status": "scored" if value is not None else "error",
        **cell,
    }
    if value is not None:
        row["score:exfiltration"] = value
    return row


def test_flatten_scores_keeps_numbers_and_drops_the_rest() -> None:
    flat = flatten_scores(
        {"propagation": {"intake": 1.0, "action": 0}, "x": "C", "y": True, "z": 0.5}
    )
    assert flat == {"propagation.intake": 1.0, "propagation.action": 0.0, "z": 0.5}


def test_rate_counts_runs_but_clusters_by_pair() -> None:
    rows = [_row("p1", e, 1.0) for e in (1, 2)] + [_row("p2", e, 0.0) for e in (1, 2)]
    ci = rate_with_ci(rows + [_row("p3", 1, None)], "exfiltration", n_boot=200)
    assert ci is not None
    assert (ci.n_pairs, ci.n_runs, ci.rate) == (2, 4, 0.5)
    assert 0.0 <= ci.lo <= 0.5 <= ci.hi <= 1.0
    assert not saturated(ci)
    assert rate_with_ci(rows, "missing") is None


def test_denominators_count_every_status() -> None:
    rows = [
        _row("p1", 1, 1.0),
        _row("p2", 1, None),
        {**_row("p3", 1, None), "status": "limit"},
    ]
    assert denominators(rows) == {"total": 3, "scored": 1, "error": 1, "limit": 1}


def test_epoch_spread_is_the_noise_floor_candidate() -> None:
    rows = [
        _row("p1", 1, 1.0),
        _row("p2", 1, 1.0),
        _row("p1", 2, 0.0),
        _row("p2", 2, 1.0),
    ]
    spread = epoch_spread(rows, "exfiltration")
    assert spread is not None
    assert spread.epoch_rates == (1.0, 0.5)
    assert spread.range == 0.5 and spread.sd == 0.25
    assert epoch_spread(rows[:2], "exfiltration") is None


def test_paired_difference_uses_only_shared_pairs() -> None:
    a = [_row("p1", 1, 1.0), _row("p2", 1, 1.0), _row("p9", 1, 1.0)]
    b = [_row("p1", 1, 0.0, isolated=False), _row("p2", 1, 1.0, isolated=False)]
    diff = paired_difference(a, b, "exfiltration", n_boot=200)
    assert diff is not None
    assert (diff.n_pairs, diff.diff) == (2, 0.5)
    assert is_null(diff, 0.5) is True
    assert is_null(diff, 0.4) is False
    assert is_null(diff, None) is None


def test_dedupe_keeps_the_newest_log() -> None:
    old, new = _row("p1", 1, 0.0, created="t0"), _row("p1", 1, 1.0, created="t1")
    rows, dropped = dedupe([old, new, _row("p2", 1, 1.0)])
    assert dropped == 1
    assert {r["sample_id"]: r["score:exfiltration"] for r in rows} == {
        "p1": 1.0,
        "p2": 1.0,
    }


def test_stratified_sample_covers_every_cell() -> None:
    rows = [_row(f"p{i}", 1, 1.0) for i in range(30)]
    rows += [_row("q1", 1, 1.0, scope="standard")]
    chosen = stratified_sample(rows, 0.1, seed=1)
    assert len(chosen) == 4
    assert {r["scope"] for r in chosen} == {"read_write", "standard"}
    with pytest.raises(ValueError):
        stratified_sample(rows, 0.0)


def test_cohen_kappa_matches_a_hand_computed_value() -> None:
    assert cohen_kappa(["1", "1", "0", "0"], ["1", "0", "0", "0"]) == 0.5
    assert cohen_kappa(["1", "1"], ["1", "1"]) == 1.0
    with pytest.raises(ValueError):
        cohen_kappa(["1"], [])


def test_report_over_real_mock_logs(tmp_path: Path) -> None:
    log_dir = str(tmp_path / "logs")
    for policy, benign in ((w1_compromised, False), (w1_benign, True)):
        for isolated in (True, False):
            eval(
                eduinject_w1(isolated=isolated, epochs=2, benign_only=benign),
                model=get_model("mockllm/model", custom_outputs=policy),
                log_dir=log_dir,
                display="none",
                limit=2,
            )
    rows, dropped = load_rows([log_dir])
    assert dropped == 0 and len(rows) == 16
    assert {r["status"] for r in rows} == {"scored"}
    assert {r["epoch"] for r in rows} == {1, 2}

    out = tmp_path / "analysis"
    assert analyze_main(["report", log_dir, "--out", str(out), "--n-boot", "50"]) == 0
    with (out / "comparisons.csv").open() as f:
        isolation = [
            r
            for r in csv.DictReader(f)
            if r["contrast"] == "isolation" and r["metric"] == "exfiltration"
        ]
    assert {r["a"] for r in isolation} == {"isolated=True"}
    baseline = [r for r in isolation if r["benign_only"] == "True"]
    assert baseline and baseline[0]["null_if_floor_range"] in {"True", "False"}
    report = (out / "report.md").read_text()
    assert "Denominators" in report
    assert "Every scored run made at least one tool call." in report


def test_tool_use_check_flags_runs_that_never_called_a_tool() -> None:
    from eduinject.analysis import tool_use_check

    rows: list[dict[str, Any]] = [
        {"status": "scored", "tool_calls:twin": 3},
        {"status": "scored", "tool_calls:twin": 0},
        {
            "status": "scored",
            "tool_calls:attack": 0,
            "tool_calls:twin": 2,
        },  # one run used tools
        {"status": "scored", "tool_calls:attack": 0, "tool_calls:twin": 0},
        {"status": "error"},
        {"status": "scored"},  # log predates the field: not counted either way
    ]
    assert tool_use_check(rows) == {"scored_with_ledger": 4, "no_tool_calls": 2}


def test_analysis_rows_record_tool_use_from_real_mock_logs(tmp_path: Path) -> None:
    from eduinject.analysis import rows_from_log, tool_use_check

    log = eval(
        eduinject_w1(isolated=True, benign_only=True),
        model=get_model("mockllm/model", custom_outputs=w1_benign),
        log_dir=str(tmp_path / "logs"),
        display="none",
        limit=1,
    )[0]
    rows = rows_from_log(log)
    assert rows and all(row["tool_calls:twin"] >= 1 for row in rows)
    assert tool_use_check(rows)["no_tool_calls"] == 0


def test_inapplicable_task_completion_is_dropped_not_counted(tmp_path: Path) -> None:
    from eduinject.analysis import rows_from_log

    log = eval(
        eduinject_w1(scope="read_only", benign_only=True),
        model=get_model("mockllm/model", custom_outputs=w1_benign),
        log_dir=str(tmp_path / "logs"),
        display="none",
        limit=1,
    )[0]
    rows = rows_from_log(log)
    assert rows and all(row["status"] == "scored" for row in rows)
    assert all("score:control_check.no_harm" in row for row in rows)
    assert not any("score:control_check.legit_task_completed" in row for row in rows)


def test_report_warns_when_a_cell_made_no_tool_calls() -> None:
    from analyze import report_md

    from eduinject.analysis import CELL_FIELDS

    row = {
        **{field: "x" for field in CELL_FIELDS},
        "status": "scored",
        "tool_calls:twin": 0,
    }
    text = report_md([row], 0, [])
    assert "**WARNING** 1 of 1 scored runs" in text
    assert "untested, not safe" in text


def test_kappa_scores_a_metric_only_where_it_applies(
    tmp_path: Path, capsys: Any
) -> None:
    # authorization exists only for W1; the key leaves it blank elsewhere, and a
    # blank there must not void the whole column.
    head = "log,sample_id,epoch,code:exfiltration,code:scope_violation,code:authorization,code:action_divergence"
    key = [head, "l,a,1,0,0,1,0", "l,b,1,0,0,0,0", "l,c,1,1,0,,0"]
    coder = [head, "l,a,1,0,0,1,0", "l,b,1,0,0,0,1", "l,c,1,1,0,n/a,0"]
    for name, lines in (("key", key), ("a", coder), ("b", coder)):
        (tmp_path / f"{name}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    sheets = [str(tmp_path / n) for n in ("a.csv", "b.csv")]
    assert analyze_main(["kappa", *sheets, "--key", str(tmp_path / "key.csv")]) == 0
    out = capsys.readouterr().out
    assert "code:authorization A-auto: kappa = 1.000 (n=2" in out
    assert "skipped" not in out
