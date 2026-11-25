"""E1: every figure renders from small synthetic CSVs, only under logs/."""

import csv
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import make_figures

from eduinject import endpoints
from eduinject.behavior.ladder import ATTACK_ONLY, BEHAVIOURS

DEV = endpoints.study_models().dev
(HELD,) = endpoints.study_models().held_out


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
            "base_id": f"b{i % 4}",
            "artifact_id": f"a{i}",
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
    _csv(logs / "behavior" / "ladder.csv", ladder_rows(("w1", "w2")))
    _csv(logs / "endpoints" / "headroom.csv", headroom_rows(("w1", "w2", "w3")))
    _csv(logs / "endpoints" / "swap_effects.csv", swap_rows())
    _csv(logs / "endpoints" / "grid.csv", grid_rows())
    return logs


# The columns of `endpoints.compute` and `behavior_models.py ladder`.


def headroom_rows(workflows: tuple[str, ...]) -> list[dict[str, object]]:
    models = [(endpoints.POOLED, "pooled"), *((m, "dev") for m in DEV)]
    return [
        {
            "arm": arm,
            "reference": "not_isolated",
            "workflow": wf,
            "model": model,
            "role": role,
            "models_missing": "",
            "n_scenarios": 8,
            "ceiling_u": 0.9,
            "ceiling": ceiling,
            "observed": observed,
            "observed_lo": observed - 0.1,
            "observed_hi": observed + 0.1,
            "zero_upper": "",
            "excess": observed - 0.05,
            "structural": 0.9 - ceiling,
            "behavioural": ceiling - observed,
            "bound_ok": True,
        }
        for wf in workflows
        for arm, ceiling, observed in (
            ("gate_open", 0.3, 0.2),
            ("not_isolated", 0.9, 0.5),
        )
        for model, role in models
    ]


def ladder_rows(
    workflows: tuple[str, ...], models: tuple[str, ...] = DEV, **cell: object
) -> list[dict[str, object]]:
    return [
        {**_cell(m, wf, "read_write"), "host": f"host-{m}", **cell}
        | {"corpus_digest": f"digest-{wf}", "behaviour": b, "attack_rate": 0.4}
        | (
            {"twin_rate": "", "difference": "", "lo": "", "hi": ""}
            if b in ATTACK_ONLY
            else {"twin_rate": 0.1, "difference": 0.3, "lo": 0.2, "hi": 0.4}
        )
        | {"n_pairs": 64, "n_scenarios": 8}
        for wf in workflows
        for m in models
        for b in BEHAVIOURS
    ]


def swap_rows() -> list[dict[str, object]]:
    return [
        {
            "outcome": outcome,
            "effect": effect,
            "workflow": wf,
            "model": model,
            "models_missing": "",
            "n_scenarios": 8,
            "estimate": 0.0 if effect == "de" else 0.2,
            "lo": 0.0 if effect == "de" else 0.1,
            "hi": 0.0 if effect == "de" else 0.3,
            "zero_upper": 0.3 if effect == "de" else "",
        }
        for outcome in (endpoints.ATTEMPT, "state:adopt")
        for effect in endpoints.EFFECTS
        for wf in (endpoints.ALL, "w1", "w2")
        for model in (endpoints.POOLED, *DEV, HELD)
    ]


def grid_rows() -> list[dict[str, object]]:
    blank: dict[str, object] = dict.fromkeys(
        ("actor", "workflow", "component", "actor_b", "reader_b", "diff", "lo90")
        + ("hi90", "lo_sim", "hi_sim", "verdict", "n_scenarios", "n_relayed")
        + ("attempt_excess", "attempt_estimable", "attempt_scenarios")
        + ("adopt_excess", "adopt_estimable", "adopt_scenarios"),
        "",
    )
    diff: dict[str, object] = {
        "diff": 0.02,
        "lo90": -0.05,
        "hi90": 0.09,
        "lo_sim": -0.2,
        "hi_sim": 0.2,
    }
    cells: list[dict[str, object]] = [
        {"kind": "cell", "reader": i, "actor": j, "workflow": wf, "n_relayed": 50}
        | {"attempt_excess": 0.3, "attempt_estimable": i != j, "attempt_scenarios": 8}
        | {"adopt_excess": 0.2, "adopt_estimable": True, "adopt_scenarios": 8}
        for wf in (endpoints.ALL, "w1")
        for i in DEV
        for j in DEV
    ]
    compared: list[dict[str, object]] = [
        {"kind": "actors", "actor": DEV[0], "actor_b": DEV[1], "reader": ""}
        | {"component": t, "verdict": "not_estimable" if wf == "w2" else ""}
        | {"workflow": wf, "n_scenarios": 8}
        | ({} if wf == "w2" else diff)
        for t in ("adopt", "attempt")
        for wf in (endpoints.ALL, "w1", "w2", "w3")
    ]
    # Descriptive: one reader's own comparison is in no test and not drawn.
    compared += [
        {"kind": "transition", "reader": DEV[0], "actor": DEV[0], "in_test": False}
        | {"actor_b": DEV[1], "component": "adopt"}
        | diff
    ]
    onset: list[dict[str, object]] = [
        {"kind": "onset", "reader": DEV[0], "reader_b": DEV[1], "n_scenarios": 8}
    ]
    share: list[dict[str, object]] = [
        {"kind": "variance", "reader": "", "component": "reader"}
    ]
    rows = [*cells, *compared, *(o | diff for o in onset), *share]
    return [{**blank, "in_test": r["kind"] != "variance", **r} for r in rows]


PRIMARY = {
    "headroom.png",
    "ladder.png",
    "swap_effects.png",
    "swap_effects_adopt.png",
    "grid.png",
    "grid_w1.png",
    "grid_comparisons.png",
    "stage_survival_m1.png",
    "stage_survival_m2.png",
}


def _text(rows: list[dict[str, object]]) -> list[dict[str, str]]:
    return [{k: str(v) for k, v in r.items()} for r in rows]


def test_primary_run_draws_no_appendix_figure(
    logs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = logs / "figures"
    assert make_figures.main(["--in", str(logs), "--out", str(out)]) == 0
    assert {p.name for p in out.rglob("*.png")} == PRIMARY
    assert all(p.stat().st_size > 0 for p in out.iterdir())
    assert {p.stem for p in out.glob("*.pdf")} == {Path(n).stem for n in PRIMARY}
    assert "halflife.csv" not in capsys.readouterr().out


def test_appendix_flag_draws_them_under_appendix(logs: Path) -> None:
    out = logs / "figures"
    ins = ["--in", str(logs), "--out", str(out)]
    assert make_figures.main([*ins, "--appendix", "--by", "goal"]) == 0
    assert {p.name for p in out.glob("*.png")} == PRIMARY
    names = {p.name for p in (out / "appendix").glob("*.png")}
    assert {n for n in names if not n.startswith("transitions_")} == {
        "halflife_content_vs_warning.png",
        "pareto_frontier.png",
        "risk_heatmap.png",
        "rank_shift.png",
        "violations_by_origin_stage.png",
        "rank_shift_RESTRICTED_by_goal.png",
    }
    assert any(n.startswith("transitions_") for n in names)
    with pytest.raises(SystemExit):  # the restricted slice is appendix only
        make_figures.main([*ins, "--by", "goal"])


def test_headroom_figure_one_panel_per_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    figs: Any = _captured(monkeypatch)
    rows = _text(headroom_rows(("w1", "w2", "w3")))
    make_figures.headroom(rows, tmp_path)
    (fig,) = figs
    assert [a.get_title(loc="left") for a in fig.axes] == [
        f"{name} (n = 8 scenarios)"
        for name in ("W1 help desk", "W2 hiring", "W3 parent mail")
    ]
    ax = fig.axes[0]
    # The reference arm first; each bar's parts add up to the reference ceiling.
    assert [t.get_text() for t in ax.get_yticklabels()] == [
        "not_isolated (ref.)",
        "gate_open",
    ]
    parts = {
        (round(p.get_y() + p.get_height() / 2), p.get_facecolor()): p.get_width()
        for p in ax.patches
    }
    colour = {
        n: make_figures.matplotlib.colors.to_rgba(getattr(make_figures, n))
        for n in ("DONE", "PERMITTED", "BLOCKED")
    }
    assert parts[1, colour["DONE"]] == pytest.approx(0.2)
    assert parts[1, colour["PERMITTED"]] == pytest.approx(0.1)
    assert parts[1, colour["BLOCKED"]] == pytest.approx(0.6)
    assert (0, colour["BLOCKED"]) not in parts
    with pytest.raises(ValueError, match="share an arm"):
        make_figures.headroom([*rows, rows[0]], tmp_path)


def test_ladder_figure_never_pools_cells(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    figs: Any = _captured(monkeypatch)
    rows = _text(ladder_rows(("w1",), gate=False) + ladder_rows(("w1",), gate=True))
    make_figures.ladder(rows, tmp_path)
    panels = [a for a in figs[0].axes if a.get_visible()]
    assert [a.get_title(loc="left") for a in panels] == [
        "W1 help desk\ncore cell\nn = 8 scenarios",
        "W1 help desk\ngate=True\nn = 8 scenarios",
    ]
    for ax in panels:  # one point per model and behaviour
        assert len(ax.containers) == len(DEV) * len(BEHAVIOURS)
    with pytest.raises(ValueError, match="share a ladder point"):
        make_figures.ladder([*rows, rows[0]], tmp_path)
    # One model on two hosts is two series, never one.
    two = ladder_rows(("w1",), DEV[:1]) + ladder_rows(("w1",), DEV[:1], host="other")
    make_figures.ladder(_text(two), tmp_path)
    assert len(figs[1].axes[0].containers) == 2 * len(BEHAVIOURS)


def test_models_keep_one_order_and_colour() -> None:
    names = make_figures.model_names({HELD, "zz", *DEV})
    assert list(names) == [*DEV, HELD, "zz"]
    assert names[DEV[0]] == endpoints.DEV_MODELS[0]
    alone = make_figures.styles({HELD})[HELD]
    assert alone == make_figures.styles({HELD, "zz", *DEV})[HELD]


def test_missing_input_skips_not_crashes(
    logs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = logs / "figures"
    ins = ["--in", str(logs / "risk"), "--out", str(out), "--appendix"]
    assert make_figures.main(ins) == 0
    printed = capsys.readouterr().out
    for name in ("headroom", "ladder", "swap_effects", "grid", "halflife"):
        assert f"skipped {name}" in printed
    assert (out / "appendix" / "risk_heatmap.png").is_file()


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
    ticks = [t.get_text() for t in shift.axes[0].get_yticklabels()]  # type: ignore[attr-defined]
    assert ticks == ["gate=False", "gate=True"]
    ticks = [t.get_text() for t in restricted.axes[0].get_yticklabels()]  # type: ignore[attr-defined]
    assert ticks == ["gate=False | goal=g", "gate=True | goal=g"]
    titles = [a.get_title(loc="left") for a in viol.axes]  # type: ignore[attr-defined]
    assert titles == ["gate=False", "gate=True"]


def test_stage_survival_shows_relays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    figs = _captured(monkeypatch)
    row = {
        "workflow": "w1",
        "base_id": "b1",
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

    out = logs / "figures"
    ins = ["--in", str(logs / "features"), "--out", str(out)]
    shutil.copy(logs / "features" / "f.csv", logs / "features" / "f.swap.csv")
    assert make_figures.main(ins) == 0  # a swap table is not a feature table
    shutil.copy(logs / "features" / "f.csv", logs / "features" / "g.csv")
    assert make_figures.main(ins) == 2


def test_two_endpoint_tables_refused(logs: Path) -> None:
    """Dev and confirm tables share names: neither is picked silently."""
    _csv(logs / "dev" / "headroom.csv", headroom_rows(("w1",)))
    assert make_figures.main(["--in", str(logs), "--out", str(logs / "figures")]) == 2
