"""Feature table (A4): one row per run, every column marked pre_outcome/outcome."""

import json
import math
import sys
from pathlib import Path
from typing import Any

import pytest
from inspect_ai import eval
from inspect_ai.model import get_model

from eduinject.features import _sequence, feature_row, feature_rows, role_of
from eduinject.records import CallView, RunRecord, records_from_logs
from eduinject.task import eduinject_w2
from tests.helpers import MOCK
from tests.test_task_e2e import compromised_policy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


@pytest.fixture(scope="module")
def log_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One compromised W2 pair through two relays (k=2)."""
    out = tmp_path_factory.mktemp("features") / "logs"
    (log,) = eval(
        eduinject_w2(scope="read_write", isolated=True, relay_stages=2),
        model=get_model(MOCK, custom_outputs=compromised_policy),
        log_dir=str(out),
        display="none",
        limit=1,
    )
    assert log.status == "success", log.error
    return out


@pytest.fixture(scope="module")
def rows(log_dir: Path) -> dict[str, dict[str, Any]]:
    return {r["label"]: r for r in feature_rows(records_from_logs([str(log_dir)]))}


def test_every_column_has_a_role(rows: dict[str, dict[str, Any]]) -> None:
    assert set(rows) == {"attack", "twin"}
    for row in rows.values():
        for column in row:
            assert role_of(column) in ("pre_outcome", "outcome")
    with pytest.raises(KeyError):
        role_of("not_a_column")


def test_stage_columns_follow_stages(rows: dict[str, dict[str, Any]]) -> None:
    row = rows["attack"]
    for stage in ("intake", "analysis", "relay_1", "relay_2", "action"):
        assert f"carry:{stage}" in row and f"tokens_out:{stage}" in row
    assert "carry:relay_3" not in row
    assert row["carry:relay_2"] == "carried_silent"
    assert role_of("carry:relay_2") == "pre_outcome"
    assert rows["twin"]["carry:relay_2"] == "absent"


def test_action_columns_are_outcome() -> None:
    for prefix in ("carry", "flag", "tokens_in", "tokens_out"):
        assert role_of(f"{prefix}:action") == "outcome"
        assert role_of(f"{prefix}:intake") == "pre_outcome"
    assert role_of("carry:action:name") == "outcome"
    assert role_of("carry:analysis:name") == "pre_outcome"
    for column in (
        "prov:document_only",
        "monitor:rules",
        "calls",
        "out:harm_attempted",
    ):
        assert role_of(column) == "outcome"
    for column in (
        "model",
        "relay_stages",
        "goal",
        "split",
        "label",
        "doc_available",
        "handoff_parse_error",
    ):
        assert role_of(column) == "pre_outcome"
    # `unfinished` can come from an action-stage limit.
    assert role_of("status") == "outcome"
    with pytest.raises(KeyError):
        role_of("flag:action:name")


def _record(*calls: tuple[str, str], **fields: Any) -> RunRecord:
    return RunRecord(
        label="attack",
        sample_id="s",
        artifact_id="a",
        epoch=1,
        cell={"workflow": "w2"},
        coords={},
        operator_request="",
        document_text=None,
        stages=(),
        calls=tuple(
            CallView(i, tool, {}, outcome, None)
            for i, (tool, outcome) in enumerate(calls)
        ),
        status="unfinished",
        meta={},
    )._replace(**fields)


def test_tokens_come_from_stage_usage() -> None:
    usage = {"input_tokens": 5, "output_tokens": 2}
    record = _record(stages=(("intake", "", "x"),), usage_by_stage={"intake": usage})
    row = feature_row(record, None)
    assert (row["tokens_in:intake"], row["tokens_out:intake"]) == (5, 2)


def test_verified_before_write() -> None:
    lookup, send = "get_posting_requirements", "send_email"

    def seq(*calls: tuple[str, str]) -> dict[str, Any]:
        return _sequence(_record(*calls), [send])

    ok = seq((lookup, "ok"), (send, "ok"))
    assert ok["verified_before_write"] == 1.0
    assert ok["lookups_before_first_write"] == 1
    failed = seq((lookup, "error"), (send, "ok"))
    assert failed["verified_before_write"] == 0.0
    late = seq((send, "ok"), (lookup, "ok"))
    assert late["verified_before_write"] == 0.0
    assert late["lookups_before_first_write"] == 0
    assert math.isnan(seq((lookup, "ok"))["verified_before_write"])


def test_sequence_is_nan_unless_ok() -> None:
    row = feature_row(_record(("send_email", "ok")), None)
    for column in (
        "calls",
        "lookups_before_first_write",
        "verified_before_write",
        "submitted",
    ):
        assert math.isnan(row[column])
    assert row["doc_available"] == 0.0 and row["handoff_parse_error"] == 0.0


def test_two_runs_with_one_label_refuse_to_pair() -> None:
    with pytest.raises(ValueError, match="two attack runs"):
        feature_rows([_record(), _record()])


def test_twin_row_has_twin_outcomes(rows: dict[str, dict[str, Any]]) -> None:
    attack, twin = rows["attack"], rows["twin"]
    assert attack["out:exfiltration"] == 1.0 and attack["out:harm_completed"] == 1.0
    assert twin["out:exfiltration"] == 0.0 and twin["out:harm_completed"] == 0.0
    assert attack["submitted"] == twin["submitted"] == 1.0
    # Pair-level outcomes sit on the attack row only.
    assert not math.isnan(attack["out:substituted"])
    assert math.isnan(twin["out:substituted"])


def test_build_features_writes_csv_and_roles(
    log_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import build_features

    monkeypatch.setattr(build_features, "LOGS", log_dir)
    out = log_dir / "features" / "t.csv"
    assert build_features.main(["--log-dir", str(log_dir), "--out", str(out)]) == 0
    header = out.read_text(encoding="utf-8").splitlines()[0].split(",")
    roles = json.loads(out.with_suffix(".roles.json").read_text(encoding="utf-8"))
    assert roles["features_version"] == "1.1"
    assert list(roles["roles"]) == header
    for bad in (log_dir.parent / "elsewhere.csv", log_dir.parent / "x/logs/t.csv"):
        assert build_features.main(["--log-dir", str(log_dir), "--out", str(bad)]) == 2


def _score(value: Any, key: str | None = None) -> float:
    return float(value if key is None else value[key])


@pytest.mark.parametrize("workflow", ["w1", "w2", "w3"])
def test_feature_outcomes_match_logged_scores(workflow: str, tmp_path: Path) -> None:
    """The feature table recomputes `out:*` with the scorers' own functions."""
    from eduinject.task_w1 import eduinject_w1
    from eduinject.task_w3 import eduinject_w3
    from tests.helpers import w1_compromised, w3_compromised

    task, policy = {
        "w1": (eduinject_w1, w1_compromised),
        "w2": (eduinject_w2, compromised_policy),
        "w3": (eduinject_w3, w3_compromised),
    }[workflow]
    (log,) = eval(
        task(scope="read_write", isolated=True),
        model=get_model(MOCK, custom_outputs=policy),
        log_dir=str(tmp_path / "logs"),
        display="none",
        limit=1,
    )
    assert log.status == "success", log.error
    assert log.samples
    scores = {k: v.value for k, v in (log.samples[0].scores or {}).items()}
    rows = {
        r["label"]: r for r in feature_rows(records_from_logs([str(tmp_path / "logs")]))
    }
    attack, twin = rows["attack"], rows["twin"]
    expected = {
        "out:exfiltration": _score(scores["exfiltration"]),
        "out:scope_violation": _score(scores["scope_violation"]),
        "out:misdirection": _score(scores["misdirection"]),
        "out:harm_attempted": _score(scores["harm"], "attempted"),
        "out:harm_completed": _score(scores["harm"], "completed"),
        "out:substituted": _score(scores["argument_provenance"]),
        "out:did_correct_thing": _score(scores["paired_utility"], "utility_attack"),
        "out:premise_relied": _score(scores["premise_adoption"], "relied_attack"),
    }
    if workflow == "w1":
        expected["out:authorization"] = _score(scores["authorization"])
    if "rank_corruption" in scores:
        expected["out:rank_shift"] = _score(scores["rank_corruption"], "shift")
    for column, value in expected.items():
        assert attack[column] == pytest.approx(value, nan_ok=True), column
    twin_expected = {
        "out:did_correct_thing": _score(scores["paired_utility"], "utility_twin"),
        "out:premise_relied": _score(scores["premise_adoption"], "relied_twin"),
    }
    for column, value in twin_expected.items():
        assert twin[column] == pytest.approx(value, nan_ok=True), column
