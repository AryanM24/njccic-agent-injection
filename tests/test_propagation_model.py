"""A6: stage-propagation chain, path decomposition and half-life (doc 11 §3.6)."""

import csv
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

import pytest

from eduinject.behavior.ladder import BEHAVIOURS
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
from eduinject.behavior.swap import block_effects, pair_effects
from eduinject.features import FEATURES_VERSION
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
    assert 0 < fit.kept <= 50


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
    roles = features.with_suffix(".roles.json")
    argv = ["chain", "--features", str(features), "--out", str(out)]
    assert behavior_models.main(argv) == 4  # no roles file: stale
    roles.write_text(json.dumps({"features_version": "1.1"}))
    assert behavior_models.main(argv) == 4
    roles.write_text(json.dumps({"features_version": FEATURES_VERSION}))
    for cmd in ("chain", "halflife"):
        assert (
            behavior_models.main([cmd, "--features", str(features), "--out", str(out)])
            == 0
        )
    with (out / "halflife.csv").open(encoding="utf-8") as f:
        families = {r["family"] for r in csv.DictReader(f)}
    assert families == {"marker", "warning", "content:recipient"}
    header = (out / "halflife.csv").read_text().splitlines()[0]
    assert "kept" in header and header.startswith("section,")
    assert (out / "halflife.csv").read_text().splitlines()[1].startswith("appendix,")
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


def _block(
    aa: float, at: float, ta: float, tt: float, pair: str = "p1", epoch: Any = 1
) -> list[dict[str, Any]]:
    cells = {"aa": aa, "at": at, "ta": ta, "tt": tt}
    return [
        {"artifact_id": pair, "epoch": epoch, "swap": c, "beh:attempt": y}
        for c, y in cells.items()
    ]


def test_block_effects_identity() -> None:
    from itertools import product

    for aa, at, ta, tt in product((0.0, 1.0), repeat=4):
        ((key, e),) = block_effects(_block(aa, at, ta, tt), "beh:attempt").items()
        assert key == ("p1", 1)
        assert e.te == e.de + e.le + e.interaction
    (only_both,) = block_effects(_block(1, 0, 0, 0), "beh:attempt").values()
    assert only_both == (1, 0, 0, 1)
    (laundered,) = block_effects(_block(1, 0, 1, 0), "beh:attempt").values()
    assert laundered == (1, 0, 1, 0)
    (direct,) = block_effects(_block(1, 1, 0, 0), "beh:attempt").values()
    assert direct == (1, 1, 0, 0)


def test_incomplete_block_is_dropped() -> None:
    whole = _block(1, 0, 0, 0)
    for i in range(4):
        assert block_effects(whole[:i] + whole[i + 1 :], "beh:attempt") == {}
        undefined = [dict(r) for r in whole]
        undefined[i]["beh:attempt"] = "nan" if i % 2 else math.nan
        assert block_effects(undefined, "beh:attempt") == {}
    # Rows of two cells (say, two models) would silently overwrite each other.
    with pytest.raises(ValueError, match="group by cell"):
        block_effects(whole + whole, "beh:attempt")


def test_pair_effects_average_epochs() -> None:
    rows = [
        *_block(1, 0, 1, 0, epoch=1),
        *_block(0, 0, 0, 0, epoch="2"),
        *_block(1, 1, 0, 0, pair="p2"),
    ]
    pairs = pair_effects(block_effects(rows, "beh:attempt"))
    assert pairs == {"p1": (0.5, 0.0, 0.5, 0.0), "p2": (1.0, 1.0, 0.0, 0.0)}


IGNORE: dict[str, Any] = {"beh:ignore": 1.0}
WARN: dict[str, Any] = {"beh:warn": 1.0}


def _beh(pair: str, base: str, label: str, **cols: Any) -> dict[str, Any]:
    attack = label == "attack"
    states = dict.fromkeys(
        ("uptake", "relay", "adopt", "attempt", "attempt_strict", "harm"), 0.0
    )
    return (
        {"model": "m", "workflow": "w1", "artifact_id": pair, "base_id": base}
        | {"label": label, "epoch": 1, "status": "ok", "out:harm_completed": 0.0}
        | {f"beh:{b}": 0.0 for b in BEHAVIOURS}
        | {f"state:{s}": v for s, v in states.items()}
        | ({} if attack else {"beh:silent_carry": math.nan, "beh:ignore": math.nan})
        | cols
    )


def _run_ladder(
    rows: list[dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    import behavior_models

    features = tmp_path / "f.csv"
    with features.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    features.with_suffix(".roles.json").write_text(
        json.dumps({"features_version": FEATURES_VERSION})
    )
    monkeypatch.setattr(behavior_models, "LOGS", tmp_path / "logs")
    out = tmp_path / "logs" / "b"
    argv = ["ladder", "--features", str(features), "--out", str(out), "--n-boot", "20"]
    assert behavior_models.main(argv) == 0
    tables = []
    for name in ("ladder.csv", "transitions.csv"):
        with (out / name).open(encoding="utf-8") as f:
            tables.append(list(csv.DictReader(f)))
    return tables[0], tables[1]


def test_ladder_table_is_paired_and_scenario_weighted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        # Scenario b1 (its premise variant included): differences 1 and 0.
        _beh("p1", "b1", "attack", **WARN),
        _beh("p1", "b1", "twin"),
        _beh("p2", "b1p", "attack", **IGNORE),
        _beh("p2", "b1p", "twin"),
        # Scenario b2: difference -1.
        _beh("p3", "b2", "attack"),
        _beh("p3", "b2", "twin", **WARN),
        # The twin is unscored, so neither side of this block counts.
        _beh("p4", "b2", "attack", **WARN),
        _beh("p4", "b2", "twin", **(WARN | {"beh:warn": math.nan})),
        # Another model is another cell.
        _beh("p1", "b1", "attack", model="n"),
        _beh("p1", "b1", "twin", model="n"),
    ]
    ladder, _ = _run_ladder(rows, tmp_path, monkeypatch)
    by = {(r["model"], r["behaviour"]): r for r in ladder}
    warn = by["m", "warn"]
    assert float(warn["attack_rate"]) == pytest.approx(0.25)
    assert float(warn["twin_rate"]) == pytest.approx(0.5)
    assert float(warn["difference"]) == pytest.approx(-0.25)
    assert (warn["n_pairs"], warn["n_scenarios"]) == ("3", "2")
    assert float(by["n", "warn"]["difference"]) == 0.0
    # Attack-only behaviours have a rate and no difference.
    ignore = by["m", "ignore"]
    assert float(ignore["attack_rate"]) == pytest.approx(0.25)
    assert ignore["twin_rate"] == ignore["difference"] == ""
    assert not {"goal", "channel", "file_type"} & set(ladder[0])


def test_transitions_count_and_standardise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    on: dict[str, Any] = {"state:relay": 1.0}
    adopt = on | {"state:adopt": 1.0}
    rows = [
        _beh("p1", "b1", "attack", **adopt),
        _beh("p1", "b1", "twin"),
        _beh("p2", "b2", "attack", **on),
        # Model n relays only the easy pair: unstandardised, it looks perfect.
        _beh("p1", "b1", "attack", model="n", **adopt),
        _beh("p2", "b2", "attack", model="n"),
    ]
    _, table = _run_ladder(rows, tmp_path, monkeypatch)
    by = {(r["model"], r["label"], r["from"], r["to"]): r for r in table}
    m, n = (by[x, "attack", "relay", "adopt"] for x in ("m", "n"))
    assert (m["k"], m["n"], float(m["p"])) == ("1", "2", 0.5)
    assert (n["k"], n["n"], float(n["p"])) == ("1", "1", 1.0)
    # Only p1 has the conditioning event under both models.
    assert float(m["p_standardised"]) == float(n["p_standardised"]) == 1.0
    assert m["n_pairs_common"] == n["n_pairs_common"] == "1"
    assert by["m", "twin", "relay", "adopt"]["p"] == ""
    assert ("m", "attack", "adopt", "attempt_strict") in by
