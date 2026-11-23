"""A5 statistics (doc 11 §3.5): GEE, mixed model, Holm family, simulated power."""

import itertools
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


def test_variance_partition_recovers_known_sources() -> None:
    pytest.importorskip("statsmodels")
    import random

    rng = random.Random(1)
    sigma, b_model, b_iso = 1.0, 2.0, 0.3
    rows = []
    for i in range(200):
        u = rng.gauss(0.0, sigma)
        for model, iso in itertools.product(("a", "b"), (False, True)):
            for _ in range(3):
                eta = -1.0 + u + b_model * (model == "b") + b_iso * iso
                rows.append(
                    {
                        "status": "scored",
                        "artifact_id": f"p{i}",
                        "model": model,
                        "isolated": iso,
                        "score:y": float(rng.random() < 1 / (1 + math.exp(-eta))),
                    }
                )
    fit = stats.mixed_fit(rows, "y", ["model", "isolated"])
    assert fit is not None and fit.variance is not None
    var, share = fit.variance
    assert set(var) == {"model", "isolated", "overlap", "pair", "run"}
    assert abs(sum(share.values()) - 1) < 1e-9
    # Balanced binary factor: variance b^2 / 4 (sampling noise at 200 pairs).
    assert abs(var["model"] - b_model**2 / 4) < 0.4
    assert abs(var["pair"] - sigma**2) < 0.6
    assert var["run"] == stats.LOGISTIC_RESIDUAL
    assert share["model"] > share["pair"] > share["isolated"]
    assert abs(var["overlap"]) < 0.05


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
    variance = read("variance.csv")
    assert {r["source"] for r in variance} >= {"arm", "pair", "run"}
    assert abs(sum(float(r["share"]) for r in variance) - 1) < 1e-3
    assert read("holm.csv")[0]["p_holm"] != ""


Y_META = [0.1, 0.5, -0.2, 0.8]
SE_META = [0.2, 0.3, 0.25, 0.4]


def test_random_effects_is_paule_mandel_with_hksj() -> None:
    pytest.importorskip("statsmodels")
    from scipy.stats import t as student_t  # type: ignore[import-untyped]

    pooled = stats.random_effects(list(zip(Y_META, SE_META, strict=True)))
    assert pooled is not None and pooled.k == 4
    w = [1 / (s**2 + pooled.tau2) for s in SE_META]
    mu = sum(wi * y for wi, y in zip(w, Y_META, strict=True)) / sum(w)
    assert abs(pooled.estimate - mu) < 1e-9
    # Paule-Mandel: the generalized Q equals its degrees of freedom.
    q_gen = sum(wi * (y - mu) ** 2 for wi, y in zip(w, Y_META, strict=True))
    assert pooled.tau2 > 0 and abs(q_gen - 3) < 1e-4
    # HKSJ, truncated below at the random-effects variance.
    se = math.sqrt(max(1.0, q_gen / 3) / sum(w))
    assert abs(pooled.se - se) < 1e-9
    crit = student_t.ppf(0.975, 3)
    assert abs(pooled.lo - (mu - crit * se)) < 1e-9
    assert abs(pooled.hi - (mu + crit * se)) < 1e-9
    # Cochran's Q with fixed-effect weights: the model x factor heterogeneity test.
    wf = [1 / s**2 for s in SE_META]
    mf = sum(a * y for a, y in zip(wf, Y_META, strict=True)) / sum(wf)
    q = sum(a * (y - mf) ** 2 for a, y in zip(wf, Y_META, strict=True))
    assert abs(pooled.q - q) < 1e-9
    assert abs(pooled.i2 - max(0.0, (q - 3) / q)) < 1e-9
    pi = student_t.ppf(0.975, 2) * math.sqrt(pooled.tau2 + se**2)
    assert pooled.pi_lo is not None and pooled.pi_hi is not None
    assert abs(pooled.pi_lo - (mu - pi)) < 1e-9 and abs(pooled.pi_hi - (mu + pi)) < 1e-9


def test_random_effects_homogeneous() -> None:
    pytest.importorskip("statsmodels")
    pooled = stats.random_effects([(0.4, 0.2), (0.4, 0.3), (0.4, 0.25)])
    assert pooled is not None
    assert pooled.tau2 == 0.0 and pooled.i2 == 0.0 and pooled.p_q > 0.99
    assert abs(pooled.estimate - 0.4) < 1e-12


def test_random_effects_needs_two() -> None:
    pytest.importorskip("statsmodels")
    assert stats.random_effects([(0.4, 0.2)]) is None
    assert stats.random_effects([(0.4, 0.2), (0.1, 0.0)]) is None
    two = stats.random_effects([(0.4, 0.2), (0.1, 0.3)])
    assert two is not None and two.pi_lo is None and two.pi_hi is None


def test_report_writes_across_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("statsmodels")
    import csv

    import analyze

    from eduinject.analysis import CELL_FIELDS

    cell = {f: None for f in CELL_FIELDS} | {
        "workflow": "w1",
        "benign_only": False,
        "controls": False,
        "scope": "read_write",
        "identity_mode": "off",
        "defense": "none",
        "gate": False,
    }
    rows = [
        {
            **cell,
            **r,
            "model": m,
            "isolated": iso,
            "epoch": 1,
            "sample_id": r["artifact_id"],
        }
        for m in ("m", "n")
        for iso in (False, True)
        for r in _pairs(60)
    ]
    monkeypatch.setattr(analyze, "refuse_stale", lambda *a, **k: False)
    monkeypatch.setattr(analyze, "load_rows", lambda dirs, split=None: (rows, 0))
    assert analyze.main(["report", "x", "--out", str(tmp_path)]) == 0
    with open(tmp_path / "across_models.csv", newline="", encoding="utf-8") as f:
        table = {r["term"]: r for r in csv.DictReader(f)}
    assert set(table) == {"arm=attack", "isolated=True"}
    arm = table["arm=attack"]
    assert arm["k"] == "2" and arm["models"] == "m;n"
    assert (arm["k_sep_zero"], arm["k_sep_all"], arm["k_other"]) == ("0", "0", "0")
    assert arm["lo_br"] != "" and arm["k_same_family"] == "0"
    assert float(arm["estimate"]) > 0 and arm["n_positive"] == "2"
    assert arm["pi_lo"] == "" and "secondary" in arm["status"]


def test_across_models_pools_only_a_shared_reference() -> None:
    """A model whose usual reference level is separated is fitted against the
    next level; its same-named term is a different contrast and must not be
    pooled with the others' (it counts in `k_other`)."""
    pytest.importorskip("statsmodels")
    import random

    import analyze

    rng = random.Random(4)
    rows = []
    for model in ("m", "n", "o"):
        for i in range(90):
            scope = ("read_write", "standard", "read_only")[i % 3]
            for arm in ("attack", "twin"):
                p = 0.0 if (model == "n" and scope == "read_write") else 0.5
                rows.append(
                    {
                        "status": "scored",
                        "artifact_id": f"{model}{i}",
                        "model": model,
                        "scope": scope,
                        "arm": arm,
                        "score:h": float(rng.random() < p),
                    }
                )
    out = analyze.across_model_rows({}, rows, "h", ["arm", "scope", "model"])
    by_term = {r["term"]: r for r in out}
    for term in ("scope=read_only", "scope=standard"):
        assert by_term[term]["models"] == "m;o", term
        assert by_term[term]["k_other"] == 1 and by_term[term]["k_sep_zero"] == 0
        assert by_term[term]["reference"] == "scope=read_write"
    assert by_term["arm=attack"]["models"] == "m;n;o"


def test_across_models_pools_one_model_per_family() -> None:
    pytest.importorskip("statsmodels")
    import analyze

    old, new = (
        "openrouter/deepseek/deepseek-v4-flash-0731",
        "openrouter/deepseek/deepseek-v4.1-flash-1017",
    )
    assert analyze.model_family(f"{old} (DeepInfra, low)") == "deepseek-v4"
    assert analyze.model_family(new) == "deepseek-v4.1", "the registry decides"
    assert analyze.model_family("mockllm/model") == "mockllm/model"
    rows = [
        {**r, "model": m, "arm": arm, "score:h": r[f"score:paired_utility.harm_{arm}"]}
        for m in (old, "openrouter/openai/gpt-6-luna")
        for r in _pairs(60)
        for arm in ("attack", "twin")
    ]
    # Same family twice: one model left, nothing to pool.
    twins = [{**r, "model": old} for r in rows]
    assert analyze.across_model_rows({}, twins, "h", ["arm", "model"]) == []
    (row,) = analyze.across_model_rows({}, rows, "h", ["arm", "model"])
    assert row["k"] == 2 and row["k_same_family"] == 0
    dup = rows + [{**r, "model": f"{old} (DeepInfra, high)"} for r in rows[:240]]
    (row,) = analyze.across_model_rows({}, dup, "h", ["arm", "model"])
    assert row["k"] == 2 and row["k_same_family"] == 1


def test_across_models_counts_zero_event_separation() -> None:
    pytest.importorskip("statsmodels")
    import random

    import analyze

    rng = random.Random(5)
    rows = []
    for model in ("m", "n", "o"):
        for i in range(90):
            gate = i % 2 == 1
            for arm in ("attack", "twin"):
                p = 0.0 if (model == "o" and gate) else 0.5
                rows.append(
                    {
                        "status": "scored",
                        "artifact_id": f"{model}{i}",
                        "model": model,
                        "gate": gate,
                        "arm": arm,
                        "score:h": float(rng.random() < p),
                    }
                )
    out = {
        r["term"]: r for r in analyze.across_model_rows({}, rows, "h", ["arm", "gate"])
    }
    row = out["gate=True"]
    assert row["models"] == "m;n" and row["k_sep_zero"] == 1 and row["k_other"] == 0
