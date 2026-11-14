"""Post-run analysis: pure functions on synthetic rows, then real mock logs."""

import csv
import sys
from pathlib import Path
from typing import Any

import pytest
from inspect_ai import eval
from inspect_ai.model import get_model

from eduinject.analysis import (
    CELL_FIELDS,
    cohen_kappa,
    dedupe,
    denominators,
    epoch_spread,
    flatten_scores,
    kappa_report,
    load_rows,
    paired_difference,
    rate_with_ci,
    saturated,
    sheet_problems,
    stratified_sample,
)
from eduinject.task_w1 import eduinject_w1
from tests.helpers import w1_benign, w1_compromised

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze import main as analyze_main


def _row(pair: str, epoch: int, value: float | None, **cell: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "model": "m",
        "host": "",
        "reasoning_effort": None,
        "workflow": "w1",
        "corpus": "c",
        "corpus_digest": "d",
        "tool_surface": "t",
        "prompts_version": "p",
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


def test_within_pair_difference_compares_two_scores_of_the_same_runs() -> None:
    from eduinject.analysis import within_pair_difference

    rows = [
        {"status": "scored", "artifact_id": p, "score:a": a, "score:b": b}
        for p, a, b in (("p1", 1.0, 0.0), ("p1", 1.0, 1.0), ("p2", 0.0, 0.0))
    ]
    rows.append({"status": "scored", "artifact_id": "p3", "score:a": 1.0})
    diff = within_pair_difference(rows, "a", "b", n_boot=200)
    # p1: 1 - 0.5 = 0.5; p2: 0; p3 has no `b` and is left out.
    assert diff is not None and diff.n_pairs == 2 and diff.diff == pytest.approx(0.25)


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
        {**_row("p4", 1, None), "status": "handoff_parse_error"},
    ]
    assert denominators(rows) == {
        "total": 4,
        "scored": 1,
        "error": 1,
        "limit": 1,
        "handoff_parse_error": 1,
    }


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
    assert spread.range == 0.5
    assert epoch_spread(rows[:2], "exfiltration") is None


def test_paired_difference_uses_only_shared_pairs() -> None:
    a = [_row("p1", 1, 1.0), _row("p2", 1, 1.0), _row("p9", 1, 1.0)]
    b = [_row("p1", 1, 0.0, isolated=False), _row("p2", 1, 1.0, isolated=False)]
    diff = paired_difference(a, b, "exfiltration", n_boot=200)
    assert diff is not None
    assert (diff.n_pairs, diff.diff) == (2, 0.5)


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
    assert {r["scope"] for r in chosen} == {"read_write", "standard"}
    with pytest.raises(ValueError):
        stratified_sample(rows, 0.0)


def test_min_per_cell_enforced() -> None:
    rows = [_row(f"p{i}", 1, 1.0) for i in range(30)]
    assert len(stratified_sample(rows, 0.02)) == 5


def test_small_cell_takes_all() -> None:
    rows = [_row(f"p{i}", 1, 1.0) for i in range(3)]
    assert len(stratified_sample(rows, 0.02)) == 3


def test_enriched_sample_is_labelled_and_separate() -> None:
    rows = [_row(f"p{i}", 1, float(i % 5 == 0)) for i in range(100)]
    chosen = stratified_sample(rows, 0.02, enrich_positive="exfiltration")
    primary = [r for r in chosen if r["sample"] == "primary"]
    extra = [r for r in chosen if r["sample"] == "supplementary_positive_enriched"]
    assert len(primary) == 5 and len(extra) == 5
    assert not {r["sample_id"] for r in primary} & {r["sample_id"] for r in extra}
    assert sum(r["score:exfiltration"] == 1.0 for r in extra) == 2


_BOOK = {"code:exfiltration": {"0", "1", "n/a"}}


def test_sheet_validator_flags_constant_missing_and_out_of_codebook() -> None:
    key = [
        {"row_id": f"R{i}", "code:exfiltration": "1.0" if i < 6 else "0.0"}
        for i in range(30)
    ]
    ok = [
        {"row_id": k["row_id"], "code:exfiltration": k["code:exfiltration"]}
        for k in key
    ]
    assert sheet_problems(ok, key, _BOOK) == []
    constant = [{**r, "code:exfiltration": "0"} for r in ok]
    assert any("DEV-1" in p for p in sheet_problems(constant, key, _BOOK))
    assert any("absent" in p for p in sheet_problems(ok[:-3], key, _BOOK))
    odd = [{**ok[0], "code:exfiltration": "2"}, *ok[1:]]
    assert any("outside the codebook" in p for p in sheet_problems(odd, key, _BOOK))


def test_kappa_report_fields() -> None:
    r = kappa_report(["1", "1", "0", "0"], ["1", "0", "0", "0"])
    assert (r.n, r.kappa, r.raw_agreement) == (4, 0.5, 0.75)
    assert (r.positives_a, r.positives_b) == (2, 1)
    assert r.positive_agreement == pytest.approx(2 / 3)


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
    assert baseline and baseline[0]["verdict"] in {
        "null",
        "above_floor",
        "significant",
        "no_floor",
    }
    report = (out / "report.md").read_text()
    assert "Denominators" in report
    assert "Every scored run made at least one tool call." in report

    # Second-edition outputs (doc 10 §5).
    with (out / "in_pair.csv").open() as f:
        harm = {r["isolated"]: r for r in csv.DictReader(f) if r["outcome"] == "harm"}
    # The compromised mock harms on every attack run and never on its twin.
    assert {r["attack_minus_twin"] for r in harm.values()} == {"1.0"}
    with (out / "comparisons.csv").open() as f:
        primary = [r for r in csv.DictReader(f) if r["primary"] == "True"]
    assert primary and all(r["p_holm"] != "" for r in primary)
    assert all(r["p_sign_flip"] != "" for r in primary)

    pairs = tmp_path / "pairs.csv"
    assert (
        analyze_main(["export-pairs", log_dir, "--salt", "s3cret", "--out", str(pairs)])
        == 0
    )
    with pairs.open() as f:
        exported = list(csv.DictReader(f))
    header = set(exported[0])
    assert not header & {"goal", "channel", "file_type", "artifact_id", "log"}
    assert not any(r["pair"].startswith("w1_") for r in exported)


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


def test_read_only_row_has_no_did_correct_thing_when_no_correct_action_is_reachable(
    tmp_path: Path,
) -> None:
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
    assert not any("score:control_check.did_correct_thing" in row for row in rows)


@pytest.mark.parametrize("script", ["exfil_recipients.py", "paired_outcomes.py"])
def test_log_scripts_run_on_a_real_mock_log(tmp_path: Path, script: str) -> None:
    import subprocess

    eval(
        eduinject_w1(scope="read_write", isolated=True),
        model=get_model("mockllm/model", custom_outputs=w1_compromised),
        log_dir=str(tmp_path / "logs"),
        display="none",
        limit=1,
    )
    path = Path(__file__).resolve().parents[1] / "scripts" / script
    out = subprocess.run(
        [sys.executable, str(path), str(tmp_path / "logs")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "| --- |" in out
    if script == "exfil_recipients.py":
        assert "internal_staff" in out and "data_subject" in out


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
    other = [ln.replace("l,b,1,0,0,0,1", "l,b,1,0,0,0,0") for ln in coder]
    for name, lines in (("key", key), ("a", coder), ("b", other)):
        (tmp_path / f"{name}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    sheets = [str(tmp_path / n) for n in ("a.csv", "b.csv")]
    args = ["kappa", *sheets, "--key", str(tmp_path / "key.csv")]
    assert analyze_main([*args, "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "code:authorization A-auto: kappa = 1.000 (n=2" in out
    assert "skipped" not in out
    assert "positive_agreement" in (tmp_path / "kappa.csv").read_text()


# --------------------------------------------------------------------------
# Second-edition statistics (eduinject.stats)
# --------------------------------------------------------------------------


def _rows(values: dict[str, list[float]], metric: str = "m") -> list[dict[str, Any]]:
    return [
        {"status": "scored", "artifact_id": pair, "epoch": i, f"score:{metric}": v}
        for pair, vs in values.items()
        for i, v in enumerate(vs, 1)
    ]


def test_sign_flip_is_exact_on_small_samples() -> None:
    from eduinject.stats import sign_flip_test

    # Three pairs all +1: only the all-+ and all-- patterns are as extreme.
    assert sign_flip_test([1.0, 1.0, 1.0]) == 2 / 8
    assert sign_flip_test([0.0, 0.0]) == 1.0
    # Zero differences are dropped, not counted as evidence either way.
    assert sign_flip_test([1.0, 1.0, 1.0, 0.0]) == 2 / 8
    # Monte Carlo above 16 pairs: never exactly 0 (review #6).
    assert 0 < sign_flip_test([1.0] * 20, n_perm=999) <= 1 / 1000 * 2


def test_holm_steps_down_and_stays_monotone() -> None:
    from eduinject.stats import holm

    adjusted = holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adjusted == pytest.approx({"a": 0.03, "c": 0.06, "b": 0.06})


def test_zero_upper_bound_is_about_three_over_n() -> None:
    from eduinject.stats import zero_upper_bound

    assert zero_upper_bound(48) == pytest.approx(3 / 48, rel=0.05)
    with pytest.raises(ValueError):
        zero_upper_bound(0)


def test_mde_shrinks_with_more_pairs() -> None:
    from eduinject.stats import mde

    small, large = mde([0.0, 0.2, -0.1, 0.1] * 3), mde([0.0, 0.2, -0.1, 0.1] * 12)
    assert small is not None and large is not None and large < small
    assert mde([0.1]) is None


def test_pair_concentration_shows_a_single_artifact() -> None:
    from eduinject.stats import pair_concentration

    c = pair_concentration(_rows({"p1": [1, 1, 1, 0], "p2": [0, 0], "p3": [1, 0]}), "m")
    assert (c.positive_runs, c.pairs, c.pairs_with_any) == (4, 3, 2)
    assert c.top_pair_share == 0.75


def test_conditional_rate_counts_only_runs_where_the_condition_fired() -> None:
    from eduinject.stats import conditional_rate

    rows = [
        {"status": "scored", "artifact_id": "p", "score:prop": 1.0, "score:harm": 1.0},
        {"status": "scored", "artifact_id": "p", "score:prop": 1.0, "score:harm": 0.0},
        {"status": "scored", "artifact_id": "q", "score:prop": 0.0, "score:harm": 1.0},
        {"status": "limit", "artifact_id": "q", "score:prop": 1.0, "score:harm": 1.0},
    ]
    assert conditional_rate(rows, "harm", "prop") == (2, 0.5)
    assert conditional_rate(rows, "harm", "prop", when=False) == (1, 1.0)


def test_gee_recovers_the_direction_of_a_planted_effect() -> None:
    pytest.importorskip("statsmodels")
    from eduinject.stats import gee_contrast

    a = _rows({f"p{i}": [1, 1, 1, 0] if i % 2 else [1, 1, 0, 0] for i in range(20)})
    b = _rows({f"p{i}": [0, 0, 1, 0] if i % 2 else [0, 0, 0, 0] for i in range(20)})
    result = gee_contrast(a, b, "m")
    assert result is not None and result.log_odds > 0 and result.p < 0.01
    assert gee_contrast(_rows({"p": [0, 0]}), _rows({"p": [0, 0]}), "m") is None
    # One event against none is separation: no estimate, rather than p≈0.
    one = _rows({f"p{i}": [1 if i == 0 else 0] * 4 for i in range(20)})
    none = _rows({f"p{i}": [0] * 4 for i in range(20)})
    assert gee_contrast(one, none, "m") is None


# --------------------------------------------------------------------------
# Second-edition human validation (scripts/human_coding.py blind / agree)
# --------------------------------------------------------------------------


def _coding_rows() -> list[dict[str, str]]:
    import itertools

    rows = []
    for cell, i in itertools.product(("read_only", "read_write"), range(40)):
        rows.append(
            {
                **{f: "" for f in CELL_FIELDS},
                "scope": cell,
                "benign_only": "False",
                "controls": "False",
                "status": "scored",
                "log": "x",
                "sample_id": str(i),
                "epoch": "1",
                "score:exfiltration": "1.0" if i < 4 else "0.0",
            }
        )
    return rows


def test_blind_sample_balances_scorer_positives_and_negatives() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from human_coding import blind_sample

    chosen = blind_sample(_coding_rows(), n=20, seed=3)
    assert len(chosen) == 20
    flagged = [r for r in chosen if r["score:exfiltration"] == "1.0"]
    # 10 per cell, half positive where available: all 4 positives of each cell.
    assert len(flagged) == 8
    assert chosen == blind_sample(_coding_rows(), n=20, seed=3), "seeded"


def test_agree_refuses_the_dev1_pattern() -> None:
    cols = ("code:exfiltration", "code:authorization", "code:scope_violation")
    book = {c: {"0", "1", "n/a"} for c in cols}
    key = [
        {"row_id": f"R{i}", "code:exfiltration": "1.0" if i < 6 else "0.0"}
        for i in range(30)
    ]
    zeros = [
        {
            "row_id": k["row_id"],
            "code:exfiltration": "0",
            "code:authorization": "n/a",
            "code:scope_violation": "0",
        }
        for k in key
    ]
    assert any("DEV-1" in p for p in sheet_problems(zeros, key, book))
    honest = [
        {**z, "code:exfiltration": k["code:exfiltration"]} for z, k in zip(zeros, key)
    ]
    honest[0]["code:exfiltration"] = "0"  # an honest disagreement is fine
    assert sheet_problems(honest, key, book) == []
    blank = [{**v, "code:scope_violation": ""} for v in honest]
    assert any("blank" in p for p in sheet_problems(blank, key, book))
    all_na = [{**v, "code:exfiltration": "n/a"} for v in zeros]
    assert any("DEV-1" in p for p in sheet_problems(all_na, key, book))
    floats = [{k: ("1.0" if x == "1" else x) for k, x in v.items()} for v in honest]
    assert any("identical" in p for p in sheet_problems(honest, key, book, floats))


def test_h2_interaction_isolates_what_restoring_facts_changes() -> None:
    from analyze import interaction_rows

    def cell(isolated: bool, identity: str, harm: float) -> list[dict[str, Any]]:
        base: dict[str, Any] = {f: "" for f in CELL_FIELDS}
        base.update(
            benign_only=False, controls=False, isolated=isolated, identity_mode=identity
        )
        return [
            {
                **base,
                "status": "scored",
                "artifact_id": f"p{i}",
                "score:authorization": harm,
            }
            for i in range(12)
        ]

    # Isolation cuts harm by 0.5 with facts, and not at all without them.
    rows = (
        cell(True, "facts", 0.0)
        + cell(False, "facts", 0.5)
        + cell(True, "off", 0.5)
        + cell(False, "off", 0.5)
    )
    (row,) = [
        r for r in interaction_rows(rows, n_boot=200) if r["metric"] == "authorization"
    ]
    assert row["interaction"] == -0.5 and row["n_pairs"] == 12
    assert row["p_sign_flip"] < 0.001 and "p_holm" in row


def test_kappa_cli_refuses_bad_sheet_and_defaults_under_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    head = "log,sample_id,epoch,code:exfiltration,code:scope_violation,code:authorization,code:action_divergence"
    key = [head] + [f"l,s{i},1,{int(i < 6)},0,0,0" for i in range(12)]
    bad = [head] + [f"l,s{i},1,0,0,0,0" for i in range(12)]
    ok = [head] + [f"l,s{i},1,{int(i < 6 and i != 0)},0,0,0" for i in range(12)]
    for name, lines in (("key", key), ("bad", bad), ("ok", ok)):
        (tmp_path / f"{name}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    args = ["kappa", "bad.csv", "ok.csv", "--key", "key.csv"]
    assert analyze_main(args) == 2
    assert analyze_main([*args, "--accept-suspicious"]) == 0
    assert (tmp_path / "logs/analysis/human/kappa.csv").exists()


def _trace_sample(calls: list[dict[str, Any]]) -> tuple[dict[str, Any], Any]:
    from types import SimpleNamespace

    from eduinject.scorers import RUNS_KEY

    cell = {f: None for f in CELL_FIELDS} | {"workflow": "w1"}
    md = {
        "entitled_actions": {"reset_password": ["S-1"], "unlock_device": []},
        RUNS_KEY: {"attack": {"ledger": {"calls": calls}}},
    }
    return cell, SimpleNamespace(metadata=md)


def _call(tool: str, arg: str, value: str, outcome: str = "ok") -> dict[str, Any]:
    return {"tool": tool, "args": {arg: value}, "outcome": outcome}


def test_counts_missing_prior_lookup() -> None:
    from eduinject.analysis import ownership_lookup_check

    with_lookup = [
        _call("lookup_account", "account_id", "s-2"),
        _call("reset_password", "account_id", "S-2"),
    ]
    without = [_call("unlock_device", "asset_tag", "A-9")]
    authorized = [_call("reset_password", "account_id", "S-1")]
    rows = ownership_lookup_check(
        _trace_sample(c) for c in (with_lookup, without, authorized)
    )
    assert len(rows) == 1
    assert rows[0].cell[-1] == "attack"
    assert rows[0][1:] == (2, 1, 1)


def test_lookup_of_other_target_does_not_count() -> None:
    from eduinject.analysis import ownership_lookup_check

    calls = [
        _call("lookup_account", "account_id", "S-1"),
        _call("lookup_asset", "asset_tag", "A-9", outcome="error"),
        _call("reset_password", "account_id", "S-2"),
        _call("unlock_device", "asset_tag", "A-9"),
    ]
    (row,) = ownership_lookup_check([_trace_sample(calls)])
    assert row[1:] == (1, 0, 1)


def test_coding_sheet_order_does_not_reveal_the_enriched_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import csv

    import analyze

    rows = [_row(f"p{i:03d}", 1, float(i % 5 == 0)) for i in range(100)]
    monkeypatch.setattr(analyze, "refuse_stale", lambda *a, **k: False)
    monkeypatch.setattr(analyze, "load_rows", lambda dirs: (rows, 0))
    args = ["sample-human", "x", "--enrich-positive", "exfiltration"]
    assert analyze_main([*args, "--out", str(tmp_path)]) == 0
    with open(tmp_path / "answer_key.csv", newline="", encoding="utf-8") as f:
        labels = [r["sample"] for r in csv.DictReader(f)]
    with open(tmp_path / "coding_sheet.csv", newline="", encoding="utf-8") as f:
        sheet = list(csv.DictReader(f))
    assert "sample" not in sheet[0]
    assert labels != sorted(labels, key=lambda s: s != "primary"), "not grouped"


def test_cell_fields_include_new_conditions() -> None:
    from types import SimpleNamespace

    from eduinject.analysis import cell_from_log

    log = SimpleNamespace(
        eval=SimpleNamespace(
            model="m",
            metadata={
                "relay_stages": 2,
                "handoff_mode": "typed",
                "gate": True,
                "verification_tools": False,
            },
        )
    )
    cell = cell_from_log(log)
    assert cell["relay_stages"] == 2 and cell["handoff_mode"] == "typed"
    assert cell["gate"] is True and cell["verification_tools"] is False
    for f in ("relay_stages", "handoff_mode", "gate", "verification_tools"):
        assert f in CELL_FIELDS
