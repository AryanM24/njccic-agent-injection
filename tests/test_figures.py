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


def test_cells_differing_only_in_gate_are_never_pooled(tmp_path: Path) -> None:
    base = _cell("m1", "w1", "read") | {"risk": "0.2"}
    rows = [
        {k: str(v) for k, v in (base | {"gate": g}).items()} for g in ("True", "False")
    ]
    arm = make_figures.labeller(rows, ("model", "scope", "workflow"))
    assert arm(rows[0]) != arm(rows[1]) and "gate" in arm(rows[0])
    make_figures.heatmap(rows, tmp_path)
    assert (tmp_path / "risk_heatmap.png").is_file()
    with pytest.raises(ValueError, match="one heatmap square"):
        make_figures.heatmap([rows[0], dict(rows[0])], tmp_path)


def _captured(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    figs: list[object] = []
    monkeypatch.setattr(make_figures, "save", lambda fig, out, name: figs.append(fig))
    return figs


def test_rank_shift_and_violations_keep_cells_apart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I3: two cells differing only in gate get two boxes and two panels."""
    figs = _captured(monkeypatch)
    rows = [
        {
            k: str(v)
            for k, v in (
                _cell("m1", "w2", "read")
                | {"gate": g, "label": "attack", "out:rank_shift": "1"}
                | {"origin_stage": "intake", "goal": "g"}
            ).items()
        }
        for g in ("True", "False")
    ]
    make_figures.rank_shift(rows, tmp_path, None)
    make_figures.rank_shift(rows, tmp_path, "goal")
    make_figures.violations(rows, tmp_path)
    shift, restricted, viol = figs
    ticks = [t.get_text() for t in shift.axes[0].get_xticklabels()]  # type: ignore[attr-defined]
    assert ticks == ["gate=False", "gate=True"]
    ticks = [t.get_text() for t in restricted.axes[0].get_xticklabels()]  # type: ignore[attr-defined]
    assert ticks == ["gate=False | goal=g", "gate=True | goal=g"]
    assert [a.get_title() for a in viol.axes] == ["gate=False", "gate=True"]  # type: ignore[attr-defined]


def test_stage_survival_shows_relays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    figs = _captured(monkeypatch)
    row = {
        "model": "m1",
        "label": "attack",
        "status": "ok",
        "carry:intake": "carried_silent",
        "carry:analysis": "carried_silent",
        "carry:relay_1": "absent",
        "carry:action": "absent",
    }
    make_figures.stage_survival([row], tmp_path)
    (fig,) = figs
    ticks = [t.get_text() for t in fig.axes[0].get_xticklabels()]  # type: ignore[attr-defined]
    assert ticks == ["intake", "analysis", "relay_1", "action"]


def test_two_feature_tables_refused(logs: Path) -> None:
    import shutil

    shutil.copy(logs / "features" / "f.csv", logs / "features" / "g.csv")
    out = logs / "figures"
    assert make_figures.main(["--in", str(logs / "features"), "--out", str(out)]) == 2
