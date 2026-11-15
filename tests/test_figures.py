"""E1: every figure renders from small synthetic CSVs, only under logs/."""

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import make_figures


def _csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _cell(model: str, wf: str, scope: str) -> dict[str, object]:
    return {"model": model, "workflow": wf, "scope": scope, "isolated": "True"}


@pytest.fixture
def logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    logs = tmp_path / "logs"
    monkeypatch.setattr(make_figures, "LOGS", logs)
    cells = [
        _cell(m, wf, s)
        for m in ("m1", "m2")
        for wf in ("w1", "w2")
        for s in ("read", "write")
    ]
    feats = [
        c
        | {
            "label": "attack",
            "status": "ok",
            "out:rank_shift": i % 3,
            "goal": "g",
            "carry:intake": "carried_silent",
            "carry:analysis": "absent" if i % 2 else "carried_silent",
            "carry:action": "absent",
        }
        for i, c in enumerate(cells * 2)
    ]
    _csv(logs / "features" / "f.csv", feats)
    _csv(
        logs / "behavior" / "halflife.csv",
        [
            c
            | {
                "family": f,
                "s": 0.5,
                "half_life": 1.0 + i,
                "lo": 0.5,
                "hi": 2.0,
                "n": 5,
                "kept": 5,
            }
            for i, c in enumerate(cells)
            for f in ("warning", "content:a")
        ],
    )
    _csv(
        logs / "behavior" / "chain.csv",
        [
            c
            | {"kind": "transition", "from": a, "to": b, "p": 0.5, "lo": 0.1, "hi": 0.9}
            for c in cells[:2]
            for a in ("absent", "carried_silent")
            for b in ("absent", "carried_silent")
        ],
    )
    risk = [
        c
        | {
            "risk": 0.1 * i,
            "risk_lo": 0.0,
            "risk_hi": 0.1 * i + 0.1,
            "utility": 1 - 0.1 * i,
            "defense": "none",
        }
        for i, c in enumerate(cells)
    ]
    _csv(logs / "risk" / "risk.csv", risk)
    _csv(
        logs / "risk" / "frontier.csv",
        [
            c
            | {"risk": c["risk"], "utility": c["utility"], "pareto_optimal": i % 2 == 0}
            for i, c in enumerate(risk)
        ],
    )
    _csv(
        logs / "audit" / "violations.csv",
        [
            {"label": "attack", "origin_stage": s, "rule_id": "r"}
            for s in ("intake", "action", "action")
        ],
    )
    return logs


def test_renders_every_figure(logs: Path) -> None:
    out = logs / "figures"
    ins = [str(logs / d) for d in ("features", "behavior", "risk", "audit")]
    assert make_figures.main(["--in", *ins, "--out", str(out), "--by", "goal"]) == 0
    names = {p.name for p in out.glob("*.png")}
    assert {
        "stage_survival_m1.png",
        "halflife_content_vs_warning.png",
        "pareto_frontier.png",
        "risk_heatmap.png",
        "rank_shift.png",
        "violations_by_origin_stage.png",
        "rank_shift_RESTRICTED_by_goal.png",
    } <= names
    assert any(n.startswith("transitions_") for n in names)
    assert all(p.stat().st_size > 0 for p in out.glob("*.png"))


def test_missing_input_skips_not_crashes(
    logs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = logs / "figures"
    assert make_figures.main(["--in", str(logs / "risk"), "--out", str(out)]) == 0
    assert "skipped halflife" in capsys.readouterr().out
    assert (out / "risk_heatmap.png").is_file()


def test_out_outside_logs_refused(logs: Path, tmp_path: Path) -> None:
    assert make_figures.main(["--in", str(logs), "--out", str(tmp_path / "x")]) == 2
