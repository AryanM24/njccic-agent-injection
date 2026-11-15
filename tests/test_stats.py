"""A5 statistics (doc 11 §3.5): GEE, mixed model, Holm family, simulated power."""

import math
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from eduinject import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

HARM = ("paired_utility.harm_attack", "paired_utility.harm_twin")


def _pairs(n: int = 200) -> list[dict[str, Any]]:
    """Balanced pairs: twin harm in half of them, attack harm in 4 of 5, with
    the two arms independent of each other within a pair."""
    return [
        {
            "status": "scored",
            "artifact_id": f"p{i:03d}",
            "score:paired_utility.harm_attack": float(i % 5 != 0),
            "score:paired_utility.harm_twin": float(i < n // 2),
        }
        for i in range(n)
    ]


def test_long_rows_split_each_pair_into_two_arms() -> None:
    rows = stats.long_rows(_pairs(4), HARM)
    assert [r["arm"] for r in rows] == ["attack", "twin"] * 4
    assert [r["score:paired_utility.harm"] for r in rows[:2]] == [0.0, 1.0]
    partial = [{"status": "scored", "artifact_id": "p", HARM[0]: 1.0}]
    assert stats.long_rows(partial, HARM) == []


@pytest.mark.parametrize("cov", ["exchangeable", "independence_bias_reduced"])
def test_gee_known_log_odds(cov: stats.GeeCov) -> None:
    pytest.importorskip("statsmodels")
    fit = stats.gee_fit(
        stats.long_rows(_pairs(), HARM), "paired_utility.harm", ["arm"], cov=cov
    )
    assert fit is not None and fit.cov == cov and fit.n_groups == 200
    term = fit.terms["arm=attack"]
    assert term.log_odds == pytest.approx(math.log(4), abs=1e-3)
    assert term.lo < term.log_odds < term.hi and term.p < 1e-6


def test_gee_separation_none() -> None:
    pytest.importorskip("statsmodels")
    zeros = [
        {
            **r,
            "score:paired_utility.harm_attack": 0.0,
            "score:paired_utility.harm_twin": 0.0,
        }
        for r in _pairs()
    ]
    long = stats.long_rows(zeros, HARM)
    assert stats.gee_fit(long, "paired_utility.harm", ["arm"]) is None
    assert stats.mixed_fit(long, "paired_utility.harm", ["arm"]) is None
    # One all-zero level of a second factor is separation too.
    rows = stats.long_rows(_pairs(), HARM)
    for i, r in enumerate(rows):
        r["gate"] = i % 4 == 0
        if r["gate"]:
            r["score:paired_utility.harm"] = 0.0
    assert stats.gee_fit(rows, "paired_utility.harm", ["arm", "gate"]) is None
    with pytest.raises(ValueError):
        stats.gee_fit(rows, "paired_utility.harm", ["arm"], cov="ar1")  # type: ignore[arg-type]


def test_mixed_fit_sign() -> None:
    pytest.importorskip("statsmodels")
    fit = stats.mixed_fit(
        stats.long_rows(_pairs(), HARM), "paired_utility.harm", ["arm"]
    )
    assert fit is not None
    estimate, sd = fit.terms["arm=attack"]
    assert estimate > 0 and abs(estimate - math.log(4)) < 0.5 and sd > 0


def test_holm_family_matches_doc11() -> None:
    doc = (ROOT / "docs" / "design" / "11_study_design.md").read_text(encoding="utf-8")
    match = re.search(r"`CONTRAST_FAMILY = \(([^)]*)\)`", doc)
    assert match, "doc 11 §3.5 must declare CONTRAST_FAMILY"
    declared = tuple(re.findall(r'"([^"]+)"', match.group(1)))
    assert declared == stats.CONTRAST_FAMILY
    # Doc 10's primary contrasts stay in the family (controller ruling 5).
    import analyze

    assert set(analyze.PRIMARY_CONTRASTS) >= {
        "isolation",
        "scope",
        "identity",
        "defense",
    }


def test_power_monotone_and_seeded() -> None:
    large, small = stats.power_mde(0.1, 1000, 1), stats.power_mde(0.1, 50, 1)
    assert large is not None and small is not None and large < small
    assert stats.power_mde(0.1, 50, 1) == small
    assert stats.power_mde(0.1, 50, 4) is not None
    assert stats.power_mde(0.5, 2, 1, n_sim=50) is None
    with pytest.raises(ValueError):
        stats.power_mde(1.0, 50, 1)


def test_analyze_power_cli(capsys: pytest.CaptureFixture[str]) -> None:
    from analyze import main

    args = ["power", "--base-rate", "0.1", "--pairs", "50", "--epochs", "1"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert f"{stats.power_mde(0.1, 50, 1):.2f}" in out


def test_report_writes_gee_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("statsmodels")
    import csv

    import analyze

    from eduinject.analysis import CELL_FIELDS

    cell = {f: None for f in CELL_FIELDS} | {
        "model": "m",
        "workflow": "w1",
        "benign_only": False,
        "controls": False,
        "scope": "read_write",
        "identity_mode": "off",
        "defense": "none",
    }
    rows = [
        {**cell, **r, "isolated": iso, "epoch": 1, "sample_id": r["artifact_id"]}
        for iso in (False, True)
        for r in _pairs(60)
    ]
    monkeypatch.setattr(analyze, "refuse_stale", lambda *a, **k: False)
    monkeypatch.setattr(analyze, "load_rows", lambda dirs, split=None: (rows, 0))
    assert analyze.main(["report", "x", "--out", str(tmp_path)]) == 0

    def read(name: str) -> list[dict[str, str]]:
        with open(tmp_path / name, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    gee = read("gee.csv")
    assert {r["term"] for r in gee} == {"arm=attack", "isolated=True"}
    assert "pending PI sign-off" in gee[0]["status"] and gee[0]["verdict"]
    assert read("gee_independence.csv")[0]["cov"] == "independence_bias_reduced"
    assert read("mixed.csv")[0]["term"] == "arm=attack"
    assert read("holm.csv")[0]["p_holm"] != ""
