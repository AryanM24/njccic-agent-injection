"""A8 risk scoring (doc 11 §3.8) on synthetic feature rows with known answers."""

import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import pytest

from eduinject.analysis import CELL_FIELDS
from eduinject.features import FEATURES_VERSION
from eduinject.monitor import RULES
from eduinject.risk import (
    HARMS,
    cell_risk,
    composite,
    harm_indicators,
    load_weights,
    pareto_front,
    weight_sensitivity,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

MEDIUM = next(r.id for r in RULES["w2"] if r.severity == "medium")


def _row(doc: str, label: str, epoch: int = 0, **out: Any) -> dict[str, Any]:
    return {
        "workflow": "w2",
        "defense": "none",
        "label": label,
        "artifact_id": doc,
        "epoch": epoch,
        "status": "ok",
        "monitor:rules": out.pop("rules", ""),
        "out:g1_tier": 0.0,
        "out:authorization": math.nan,
        "out:rank_shift": math.nan,
        "out:premise_relied": math.nan,
        "out:did_correct_thing": 1.0,
        **{f"out:{k}": v for k, v in out.items()},
    }


def _cell(**over: Any) -> list[dict[str, Any]]:
    """Two documents. d1: the attack leaks at tier 3, the twin does not. d2: the
    twin breaks a medium rule and fails the task, the attack does neither."""
    rows = [
        _row("d1", "attack", g1_tier=3.0),
        _row("d1", "twin"),
        _row("d2", "attack"),
        _row("d2", "twin", rules=MEDIUM, did_correct_thing=0.0),
    ]
    return [r | over for r in rows]


def test_risk_known_answer() -> None:
    weights = {"a": 1.0, "b": 0.5}
    assert composite({"a": 0.4, "b": -0.2}, weights) == pytest.approx(26.667, abs=1e-3)
    assert composite({"a": 0.4, "b": math.nan}, weights) == pytest.approx(40.0)
    assert math.isnan(composite({"a": math.nan}, weights))


def test_cell_risk_known_answer() -> None:
    weights = load_weights(ROOT / "configs" / "severity_weights.json").weights
    r = cell_risk(_cell(), weights, n_boot=200)
    # g1_tier3 ΔP = 0.5, monitor_medium ΔP = −0.5, the other defined harms 0;
    # authorization, rank and premise are undefined on these rows.
    assert r.delta["g1_tier3"] == pytest.approx(0.5)
    assert r.delta["monitor_medium"] == pytest.approx(-0.5)
    for h in ("unauthorized_state_change", "rank_corruption", "false_premise_action"):
        assert math.isnan(r.delta[h])
    defined = sum(weights[h] for h in ("g1_tier2", "g1_tier3")) + sum(
        weights[f"monitor_{s}"] for s in ("high", "medium", "low")
    )
    assert r.risk == pytest.approx(100 * 0.5 / defined)
    assert r.lo <= r.risk <= r.hi and r.n_pairs == 2
    assert r.utility == pytest.approx(0.5)


def test_rank_corruption_scaled_and_zero_on_twins() -> None:
    attack = _row("d", "attack", rank_shift=2.0)
    assert harm_indicators(attack)["rank_corruption"] == 0.5
    assert harm_indicators(attack | {"out:rank_shift": 9})["rank_corruption"] == 1.0
    assert harm_indicators(attack | {"out:rank_shift": -1})["rank_corruption"] == 0.0
    assert harm_indicators(_row("d", "twin"))["rank_corruption"] == 0.0
    off = harm_indicators(_row("d", "attack") | {"status": "unfinished"})
    assert math.isnan(off["monitor_high"])


def test_cell_risk_refuses_pooled_conditions() -> None:
    rows = _cell() + [r | {"defense": "spotlight"} for r in _cell()]
    with pytest.raises(ValueError, match="2 conditions"):
        cell_risk(rows, {"g1_tier3": 1.0})


def test_pareto_front() -> None:
    points = {"x": (10.0, 0.9), "y": (20.0, 0.95), "z": (30.0, 0.8)}
    assert pareto_front(points) == {"x", "y"}
    assert pareto_front(points | {"n": (math.nan, 1.0)}) == {"x", "y"}


def test_sensitivity_identical_weights_tau_one() -> None:
    weights = {"a": 1.0, "b": 0.5, "c": 0.2}
    risks = {
        ("c1",): {"a": 0.4, "b": 0.0, "c": 0.0},
        ("c2",): {"a": 0.0, "b": 0.6, "c": 0.0},
        ("c3",): {"a": 0.1, "b": 0.1, "c": 0.9},
        ("c4",): {"a": 0.0, "b": 0.0, "c": 0.1},
    }
    taus = weight_sensitivity(risks, weights, n_draws=50, kappa=1e9)
    assert len(taus) == 50 and all(t == pytest.approx(1.0) for t in taus)
    loose = weight_sensitivity(risks, weights, n_draws=200, kappa=1.0)
    assert min(loose) < 1.0
    assert weight_sensitivity({("c1",): risks[("c1",)]}, weights) == []


def test_weights_out_of_range_refused(tmp_path: Path) -> None:
    good = json.loads((ROOT / "configs" / "severity_weights.json").read_text())
    assert good["version"] == "0.1-draft" and set(good["weights"]) == set(HARMS)
    for bad in (1.2, -0.1):
        path = tmp_path / "w.json"
        path.write_text(
            json.dumps(good | {"weights": good["weights"] | {"g1_tier2": bad}})
        )
        with pytest.raises(ValueError, match="outside"):
            load_weights(path)
    path.write_text(json.dumps(good | {"weights": {"g1_tier2": 0.5}}))
    with pytest.raises(ValueError, match="exactly"):
        load_weights(path)


def test_components_reported_beside_composite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import risk_report

    monkeypatch.setattr(risk_report, "LOGS", tmp_path)
    features = tmp_path / "f.csv"
    rows = [{f: r.get(f, "") for f in CELL_FIELDS} | r for r in _cell()]
    with features.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    roles = features.with_suffix(".roles.json")
    roles.write_text(json.dumps({"features_version": "1.1"}))
    out = tmp_path / "risk"
    args = ["--features", str(features), "--out", str(out), "--n-boot", "50"]
    assert risk_report.main(args) == 4  # stale feature table
    assert risk_report.main([*args[:2], "--out", "/elsewhere"]) == 2
    roles.write_text(json.dumps({"features_version": FEATURES_VERSION}))
    assert risk_report.main([*args, "--n-draws", "10"]) == 0
    with (out / "risk.csv").open(encoding="utf-8") as f:
        (row,) = list(csv.DictReader(f))
    assert float(row["risk"]) == pytest.approx(
        cell_risk(
            _cell(), load_weights(ROOT / "configs/severity_weights.json").weights
        ).risk
    )
    for h in HARMS:
        assert f"delta:{h}" in row and f"weight:{h}" in row
    assert row["weights_version"] == "0.1-draft"
    with (out / "frontier.csv").open(encoding="utf-8") as f:
        assert next(csv.DictReader(f))["pareto_optimal"] == "True"
    assert (out / "sensitivity.csv").exists()
