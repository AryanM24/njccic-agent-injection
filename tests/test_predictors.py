"""A7: behaviour predictors and model profiles (doc 11 §3.7)."""

import csv
import math
import random
import sys
from pathlib import Path
from typing import Any

import pytest

from eduinject.behavior.predictors import (
    LINE_PATTERNS,
    TARGETS,
    cross_validate,
    default_columns,
    design_matrix,
    explain,
    profile_stats,
    top_rule_targets,
    write_profile,
)
from eduinject.features import role_of

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

S, A = "carried_silent", "absent"


def _rows(n: int = 200, seed: int = 0) -> list[dict[str, Any]]:
    """Attack runs whose harm follows `carry:analysis`, flipped on exactly 5%."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        pair = i // 4
        carried = rng.random() < 0.5
        harm = carried != (i % 20 == 7)
        rows.append(
            {
                "model": f"m{i % 2}",
                "workflow": "w2",
                "isolated": "True",
                "label": "attack",
                "status": "ok",
                "artifact_id": f"p{pair}",
                "base_id": f"b{pair % 5}",
                "epoch": i % 4,
                "goal": "g1",
                "carry:intake": S,
                "carry:analysis": S if carried else A,
                "flag:intake": float(rng.random() < 0.3),
                "flag:analysis": 0.0,
                "tokens_in:intake": "",
                "carry:action": S if carried and rng.random() < 0.7 else A,
                "flag:action": 0.0,
                "calls": 2,
                "monitor:rules": "R1;R2" if harm else ("R3" if carried else ""),
                "monitor:first": "R1" if harm else ("R3" if carried else ""),
                "monitor:origin_stage": "analysis" if carried else "action",
                "out:harm_completed": float(harm),
                "out:exfiltration": float(harm),
            }
        )
    return rows


def test_outcome_column_leak_raises() -> None:
    with pytest.raises(ValueError, match="out:exfiltration"):
        design_matrix(
            _rows(), "out:harm_completed", columns=["carry:intake", "out:exfiltration"]
        )
    for leak in ("carry:action", "monitor:rules", "artifact_id", "nonsense"):
        with pytest.raises(ValueError, match=leak):
            design_matrix(_rows(), "out:harm_completed", columns=[leak])


def test_default_columns_are_all_pre_outcome() -> None:
    columns = default_columns(_rows())
    assert columns and "carry:analysis" in columns
    assert all(role_of(c) == "pre_outcome" for c in columns)
    assert not {"artifact_id", "base_id", "label", "epoch"} & set(columns)
    _, _, names = design_matrix(_rows(), "out:harm_completed")
    assert all(role_of(n.split("=")[0]) == "pre_outcome" for n in names)
    assert not any(n.startswith("artifact_id") for n in names)


def test_l1_recovers_signal() -> None:
    for scheme in ("group_kfold", "leave_one_base_out"):
        cv = cross_validate(_rows(), "out:harm_completed", "l1", scheme)  # type: ignore[arg-type]
        assert cv.auroc > 0.9, scheme
        assert cv.brier < cv.baseline_majority_brier
        assert sum(n for _, _, n in cv.calibration) == 200
    tree = cross_validate(_rows(), "out:harm_completed", "tree", "group_kfold")
    assert tree.auroc > 0.9


def test_single_class_fold_auroc_nan() -> None:
    rows = _rows()
    for r in rows:  # base b0 never harms: its leave-one-base-out fold has one class
        if r["base_id"] == "b0":
            r["out:harm_completed"] = 0.0
    cv = cross_validate(rows, "out:harm_completed", "l1", "leave_one_base_out")
    assert math.isnan(cv.auroc) and math.isnan(cv.fold_auroc[0])
    assert not math.isnan(cv.fold_auroc[1])
    assert 0 <= cv.brier <= 1
    # One class overall, or a single group: NaN, never a crash.
    flat = [r | {"out:harm_completed": 0.0} for r in _rows()]
    assert math.isnan(
        cross_validate(flat, "out:harm_completed", "tree", "group_kfold").auroc
    )
    one = [r | {"artifact_id": "p0"} for r in _rows()]
    assert math.isnan(
        cross_validate(one, "out:harm_completed", "l1", "group_kfold").auroc
    )
    assert explain(flat, "out:harm_completed", n_boot=5).std_coefs == []


def test_explain_and_rule_targets() -> None:
    assert top_rule_targets(_rows(), n=2) == ["rule:R1", "rule:R2"]
    expl = explain(_rows(), "out:harm_completed", n_boot=30)
    top = max(expl.std_coefs, key=lambda c: abs(c.coef))
    assert top.feature.startswith("carry:analysis") and top.lo <= top.coef <= top.hi
    assert "carry:analysis" in expl.tree_text
    assert max(expl.drop_column, key=lambda k: expl.drop_column[k]) == "carry:analysis"


def test_profile_has_no_free_text(tmp_path: Path) -> None:
    rows = [r for r in _rows() if r["model"] == "m0"]
    path = tmp_path / "profile_m0.md"
    write_profile("m0", profile_stats(rows, n_boot=20), path)
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln]
    assert len(lines) > 6
    for line in lines:
        assert any(p.fullmatch(line) for p in LINE_PATTERNS), line
    text = path.read_text(encoding="utf-8")
    assert "carry at analysis" in text and "Rule R1" in text
    assert "carry:analysis" in text and "95% CI" in text


def test_behavior_models_predict_and_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import behavior_models

    rows = _rows(80)
    features = tmp_path / "f.csv"
    with features.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    monkeypatch.setattr(behavior_models, "LOGS", tmp_path / "logs")
    out = tmp_path / "logs" / "behavior"
    args = ["--features", str(features), "--n-boot", "10", "--out", str(out)]
    assert behavior_models.main(["predict", *args[:4], "--out", str(tmp_path)]) == 2
    assert behavior_models.main(["predict", *args]) == 0
    assert behavior_models.main(["profiles", *args]) == 0
    with (out / "predictors.csv").open(encoding="utf-8") as f:
        cv = list(csv.DictReader(f))
    assert {r["target"] for r in cv} >= set(TARGETS)
    assert {(r["model"], r["scheme"]) for r in cv} == {
        (m, s) for m in ("l1", "tree") for s in ("group_kfold", "leave_one_base_out")
    }
    for name in ("coefficients.csv", "drop_column.csv", "trees.txt", "calibration.csv"):
        assert (out / name).exists(), name
    assert sorted(p.name for p in out.glob("profile_*.md")) == [
        "profile_m0.md",
        "profile_m1.md",
    ]
