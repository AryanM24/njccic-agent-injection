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
    with pytest.raises(ValueError):
        stats.gee_fit(long, "paired_utility.harm", ["arm"], cov="ar1")  # type: ignore[arg-type]


def test_gee_separated_level_is_dropped_and_the_rest_fitted() -> None:
    pytest.importorskip("statsmodels")
    rows = stats.long_rows(_pairs(), HARM)
    for i, r in enumerate(rows):
        r["gate"] = i % 4 == 0
        if r["gate"]:
            r["score:paired_utility.harm"] = 0.0
    fit = stats.gee_fit(rows, "paired_utility.harm", ["arm", "gate"])
    assert fit is not None and set(fit.terms) == {"arm=attack"}
    assert fit.terms["arm=attack"].log_odds > 0
    (sep,) = fit.separated
    assert sep.term == "gate=True" and sep.events == 0 and sep.n_runs == 100
    assert sep.bound == pytest.approx(stats.zero_upper_bound(sep.n_pairs))
    assert fit.references == {"arm": "twin"} and fit.unfitted == ()


def test_gee_separated_reference_moves_the_baseline_and_too_few_is_named() -> None:
    pytest.importorskip("statsmodels")
    rows = stats.long_rows(_pairs(), HARM)
    for i, r in enumerate(rows):
        r["relay_stages"] = i % 3
        if r["relay_stages"] == 0:
            r["score:paired_utility.harm"] = 0.0
    fit = stats.gee_fit(rows, "paired_utility.harm", ["arm", "relay_stages"])
    assert fit is not None and fit.separated[0].term == "relay_stages=0"
    assert fit.references == {"arm": "twin", "relay_stages": 1}
    assert set(fit.terms) == {"arm=attack", "relay_stages=2"}
    # After dropping arm=twin only 3 events remain: named, not fitted.
    few = [
        {
            **r,
            "score:paired_utility.harm_twin": 0.0,
            "score:paired_utility.harm_attack": float(i < 3),
            "gate": i % 2 == 0,
        }
        for i, r in enumerate(_pairs())
    ]
    thin = stats.gee_fit(
        stats.long_rows(few, HARM), "paired_utility.harm", ["arm", "gate"]
    )
    assert thin is not None and thin.terms == {} and thin.unfitted == ("gate",)
    mixed = stats.mixed_fit(rows, "paired_utility.harm", ["arm", "gate"])
    assert mixed is not None and set(mixed.terms) == {"arm=attack"}


def test_gee_twin_all_zero_reports_the_arm_through_separation() -> None:
    pytest.importorskip("statsmodels")
    twin_zero = [{**r, "score:paired_utility.harm_twin": 0.0} for r in _pairs()]
    fit = stats.gee_fit(
        stats.long_rows(twin_zero, HARM), "paired_utility.harm", ["arm"]
    )
    assert fit is not None and fit.terms == {}
    (sep,) = fit.separated
    assert (sep.term, sep.events, sep.n_runs) == ("arm=twin", 0, 200)
    assert (sep.other_events, sep.other_runs) == (160, 200)
    # Sparse: twin 0/200 against attack 3/200 is still a separated row.
    sparse = [
        {**r, "score:paired_utility.harm_attack": float(i < 3)}
        for i, r in enumerate(twin_zero)
    ]
    thin = stats.gee_fit(stats.long_rows(sparse, HARM), "paired_utility.harm", ["arm"])
    assert thin is not None and thin.terms == {}
    assert thin.separated[0].other_events == 3
    assert (
        stats.gee_contrast(
            [
                {**r, "score:m": r["score:paired_utility.harm_attack"]}
                for r in twin_zero
            ],
            [{**r, "score:m": 0.0} for r in twin_zero],
            "m",
        )
        is None
    )


def test_reference_levels_are_explicit() -> None:
    assert stats.REFERENCE == {
        "arm": "twin",
        "identity_mode": "off",
        "defense": "none",
        "scope": "read_write",
        "handoff_mode": "free_text",
        "gate": False,
        "relay_stages": 0,
        "isolated": False,
    }
    assert stats.factor_levels("relay_stages", [10, 2, 0, 1]) == [0, 1, 2, 10]
    assert stats.factor_levels("scope", ["read_only", "standard", "read_write"]) == [
        "read_write",
        "read_only",
        "standard",
    ]
    assert stats.factor_levels("gate", [True, False]) == [False, True]
    assert stats.factor_levels("model", ["b/m", "a/m"]) == ["a/m", "b/m"]
    assert stats.factor_levels("defense", ["spotlight", "none"])[0] == "none"
    assert stats.factor_levels("identity_mode", ["guard", "off", "facts"])[0] == "off"


def test_mixed_fit_sign() -> None:
    pytest.importorskip("statsmodels")
    fit = stats.mixed_fit(
        stats.long_rows(_pairs(), HARM), "paired_utility.harm", ["arm"]
    )
    assert fit is not None
    estimate, sd = fit.terms["arm=attack"]
    assert estimate > 0 and abs(estimate - math.log(4)) < 0.5 and sd > 0


def test_mixed_fit_recovers_a_conditional_effect_under_pair_variance() -> None:
    pytest.importorskip("statsmodels")
    import random

    rng = random.Random(0)
    beta, sigma = 1.0, 1.5
    rows = []
    for i in range(300):
        u = rng.gauss(0.0, sigma)
        for arm, shift in (("attack", beta), ("twin", 0.0)):
            for _ in range(4):
                p = 1 / (1 + math.exp(-(-0.5 + u + shift)))
                rows.append(
                    {
                        "status": "scored",
                        "artifact_id": f"p{i}",
                        "arm": arm,
                        "score:y": float(rng.random() < p),
                    }
                )
    mixed = stats.mixed_fit(rows, "y", ["arm"])
    gee = stats.gee_fit(rows, "y", ["arm"])
    assert mixed is not None and gee is not None
    estimate, _ = mixed.terms["arm=attack"]
    assert abs(estimate - beta) < 0.3
    # Population-averaged GEE attenuates towards 0 when pairs differ.
    assert 0 < gee.terms["arm=attack"].log_odds < estimate


def test_holm_family_matches_doc11() -> None:
    doc = (ROOT / "docs" / "design" / "11_study_design.md").read_text(encoding="utf-8")
    match = re.search(r"`CONTRAST_FAMILY = \(([^)]*)\)`", doc)
    assert match, "doc 11 §3.5 must declare CONTRAST_FAMILY"
    declared = tuple(re.findall(r'"([^"]+)"', match.group(1)))
    assert declared == stats.CONTRAST_FAMILY
    # Doc 10's primary contrasts stay in the family (controller ruling 5).
    import analyze

    # model's primary Holm test is the GEE term (holm.csv), not comparisons.csv.
    assert "model" not in analyze.PRIMARY_CONTRASTS
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
    # Heterogeneity costs power: concentrated effects need a larger mean shift.
    spread = stats.power_mde(0.1, 100, 4, effect_concentration=1.0)
    focused = stats.power_mde(0.1, 100, 4, effect_concentration=0.2)
    assert spread is not None and focused is not None and spread < focused


def test_power_mde_has_its_power_on_resimulation() -> None:
    kwargs: dict[str, Any] = {"effect_concentration": 0.2, "icc": 0.2}
    delta = stats.power_mde(0.1, 100, 2, n_sim=400, **kwargs)
    assert delta is not None
    again = stats.power_at(delta, 0.1, 100, 2, n_sim=1000, seed=1, **kwargs)
    assert again == pytest.approx(0.8, abs=0.06)
    below = stats.power_at(delta - 0.01, 0.1, 100, 2, n_sim=400, **kwargs)
    assert below < 0.8


def test_analyze_power_cli(capsys: pytest.CaptureFixture[str]) -> None:
    from analyze import main

    args = ["power", "--base-rate", "0.1", "--pairs", "50", "--epochs", "1"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert f"{stats.power_mde(0.1, 50, 1):.2f}" in out
    assert "ICC 0.2" in out and "50% of pairs" in out and "sign-flip" in out


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
        "gate": False,
    }
    rows = [
        {**cell, **r, "isolated": iso, "epoch": 1, "sample_id": r["artifact_id"]}
        for iso in (False, True)
        for r in _pairs(60)
    ]
    rows += [
        {
            **r,
            "gate": True,
            "score:paired_utility.harm_attack": 0.0,
            "score:paired_utility.harm_twin": 0.0,
        }
        for r in rows[:60]
    ]
    monkeypatch.setattr(analyze, "refuse_stale", lambda *a, **k: False)
    monkeypatch.setattr(analyze, "load_rows", lambda dirs, split=None: (rows, 0))
    assert analyze.main(["report", "x", "--out", str(tmp_path)]) == 0

    def read(name: str) -> list[dict[str, str]]:
        with open(tmp_path / name, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    gee = read("gee.csv")
    assert {r["term"] for r in gee} == {"arm=attack", "isolated=True", "gate=True"}
    fitted = [r for r in gee if r["log_odds"]]
    assert all("pending PI sign-off" in r["status"] and r["verdict"] for r in fitted)
    (sep,) = [r for r in gee if r["term"] == "gate=True"]
    assert sep["note"].startswith("separated: 0/120") and not sep["log_odds"]
    assert {r["reference"] for r in fitted} == {"arm=twin", "isolated=False"}
    assert read("gee_independence.csv")[0]["cov"] == "independence_bias_reduced"
    assert read("mixed.csv")[0]["term"] == "arm=attack"
    assert read("holm.csv")[0]["p_holm"] != ""
