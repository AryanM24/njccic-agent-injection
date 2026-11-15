"""A6: stage-propagation chain, path decomposition and half-life (doc 11 §3.6)."""

import csv
import math
import random
import sys
from pathlib import Path
from typing import Any

import pytest

from eduinject.behavior.propagation_model import (
    HALFLIFE_FIELDS,
    RunPath,
    decompose,
    fit_chain,
    fit_survival,
    group_rows,
    half_life,
    paths_from_features,
    survival,
    survival_by_depth,
)
from eduinject.scorers.outcomes import CarryState

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

A: CarryState = "absent"
F: CarryState = "carried_flagged"
S: CarryState = "carried_silent"


def test_half_life_recovers_s() -> None:
    rng = random.Random(0)
    counts = {
        k: (2000, sum(rng.random() < 0.8**k for _ in range(2000))) for k in range(4)
    }
    s_hat = fit_survival(counts)
    assert abs(s_hat - 0.8) < 0.02
    assert abs(half_life(s_hat) - 3.106) < 0.3


def test_no_decay_half_life_is_inf() -> None:
    s = fit_survival({0: (50, 50), 1: (50, 50), 2: (40, 40)})
    assert s == 1.0 and half_life(s) == math.inf


def test_degenerate_survival_never_fakes_a_number() -> None:
    assert fit_survival({0: (10, 10), 1: (10, 0)}) == 0.0
    assert half_life(0.0) == 0.0
    assert math.isnan(fit_survival({0: (10, 10)}))
    assert math.isnan(half_life(math.nan))


def test_chain_counts() -> None:
    paths = [
        RunPath("p1", (A, A, A), "no_act"),
        RunPath("p2", (S, S, S), "harmful_act"),
        RunPath("p3", (S, F, A), "benign_act"),
        RunPath("p4", (F, S, S), "harmful_act"),
    ]
    chain = fit_chain(paths)
    assert chain.n_runs == 4
    assert chain.transition[A] == {A: 1.0, F: 0.0, S: 0.0}
    assert chain.transition[S] == {A: 0.0, F: 0.25, S: 0.75}
    assert chain.transition[F] == {A: 0.5, F: 0.0, S: 0.5}
    assert chain.emission[A] == {"no_act": 0.5, "benign_act": 0.5, "harmful_act": 0.0}
    assert chain.emission[S]["harmful_act"] == 1.0
    assert F not in chain.emission


def test_decomposition_product_and_residual() -> None:
    # 20 runs, not 10: reach 0.5 × action|analysis 0.5 needs an even count at
    # analysis, so the brief's ratios and residual hold only at 20.
    paths = (
        [RunPath(f"r{i}", (S, S, S), "harmful_act") for i in range(5)]
        + [RunPath(f"a{i}", (S, S, A), "benign_act") for i in range(5)]
        + [RunPath(f"h{i}", (A, A, A), "harmful_act") for i in range(2)]
        + [RunPath(f"n{i}", (A, A, A), "no_act") for i in range(8)]
    )
    d = decompose(paths)
    assert (d.reach_analysis, d.reach_action_given_analysis) == (0.5, 0.5)
    assert d.harm_given_reached == 1.0
    assert d.p_harm == pytest.approx(0.35)
    assert d.residual == pytest.approx(0.1)


def _row(
    pair: str, carries: list[str], flags: list[int], harm: float = 0.0, **extra: Any
) -> dict[str, Any]:
    stages = (
        ["intake", "analysis"]
        + [f"relay_{i}" for i in range(1, len(carries) - 2)]
        + ["action"]
    )
    row: dict[str, Any] = {
        "label": "attack",
        "status": "ok",
        "artifact_id": pair,
        "model": "m",
        "workflow": "w2",
        "out:harm_completed": harm,
        "calls": 1,
    }
    for stage, c, f in zip(stages, carries, flags):
        row[f"carry:{stage}"] = c
        row[f"carry:{stage}:recipient"] = c
        row[f"flag:{stage}"] = float(f)
    return row | extra


def test_survival_by_depth_and_paths() -> None:
    rows = [
        _row("p1", [S, S, S, A, A], [0, 1, 1, 0, 0], harm=1.0),
        _row("p2", [S, S, A, A, A], [0, 1, 0, 0, 0]),
        _row("p3", [A, A, A, A, A], [0, 0, 0, 0, 0]),
        _row("p4", [S, S, S, S, S], [0, 0, 0, 0, 0], status="unfinished"),
        _row("p5", [S, S, S, S, S], [0, 0, 0, 0, 0], label="twin"),
    ]
    assert survival_by_depth(rows, "carry") == {0: (2, 2), 1: (2, 1), 2: (2, 0)}
    assert survival_by_depth(rows, "flag") == {0: (2, 2), 1: (2, 1), 2: (2, 0)}
    assert survival_by_depth(rows, "carry:recipient")[1] == (2, 1)
    paths = paths_from_features(rows)
    assert [p.outcome for p in paths] == ["harmful_act", "benign_act", "benign_act"]
    assert paths[0].states == (S, S, S, A, A)
    fit = survival(rows, "carry", n_boot=50)
    assert fit.n == 2 and 0 < fit.s < 1 and fit.lo <= fit.hi


def test_behavior_models_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import behavior_models

    rows = [
        _row(
            f"p{i}",
            [S, S, S if i % 2 else A, A],
            [0, 1, i % 2, 0],
            harm=float(i % 3 == 0),
        )
        for i in range(8)
    ]
    features = tmp_path / "f.csv"
    with features.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    out = tmp_path / "logs" / "behavior"
    monkeypatch.setattr(behavior_models, "LOGS", tmp_path / "logs")
    assert (
        behavior_models.main(
            ["chain", "--features", str(features), "--out", str(tmp_path)]
        )
        == 2
    )
    for cmd in ("chain", "halflife"):
        assert (
            behavior_models.main([cmd, "--features", str(features), "--out", str(out)])
            == 0
        )
    with (out / "halflife.csv").open(encoding="utf-8") as f:
        families = {r["family"] for r in csv.DictReader(f)}
    assert families == {"marker", "warning", "content:recipient"}
    assert (out / "chain.csv").read_text().count("transition") > 0
    assert "n_boot_kept" in (out / "chain.csv").read_text().splitlines()[0]
    assert "residual" in (out / "decomposition.csv").read_text()


def test_unknown_carry_state_raises() -> None:
    with pytest.raises(ValueError, match="carried"):
        paths_from_features([_row("p1", [S, "carried", A], [0, 0, 0])])


def test_groups_never_pool_across_conditions() -> None:
    rows = [
        _row("p1", [S, S, A], [0, 0, 0], defense="none", relay_stages=0),
        _row("p2", [S, S, A], [0, 0, 0], defense="spotlight", relay_stages=0),
        _row("p3", [S, S, S, A], [0, 0, 0, 0], defense="none", relay_stages=1),
    ]
    assert len(group_rows(rows)) == 3
    assert len(group_rows(rows, HALFLIFE_FIELDS)) == 2
