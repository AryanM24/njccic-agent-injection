"""run_sweep.py argument parsing."""

import argparse
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from estimate_cost import estimate_usd
from run_sweep import parse_args, parse_model_arg

from eduinject.models import load_models


def test_model_args_parse_json_values_and_fall_back_to_strings() -> None:
    args = parse_args(
        [
            "-M",
            'provider={"order":["DeepInfra"],"allow_fallbacks":false}',
            "-M",
            "responses_api=true",
            "-M",
            "region=us",
        ]
    )
    assert dict(args.model_args) == {
        "provider": {"order": ["DeepInfra"], "allow_fallbacks": False},
        "responses_api": True,
        "region": "us",
    }


def test_model_arg_without_equals_is_rejected() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="key=value"):
        parse_model_arg("provider")


def test_dry_run_counts_runs_and_stops_before_the_model(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from run_sweep import main

    argv = ["--model", "mockllm/model", "--workflow", "w2", "--benign-only"]
    assert main([*argv, "--epochs", "2", "--limit", "3", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "total: 36 twin runs" in out
    assert out.count("config_hash=") == 6


def test_dry_run_needs_no_api_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dry run must work before any key exists (it never calls the model)."""
    from run_sweep import main

    for variable in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.setenv(variable, "x")  # registers the original (absent) state
        monkeypatch.delenv(variable)
    argv = [
        "--workflow",
        "w2",
        "--benign-only",
        "--epochs",
        "1",
        "--limit",
        "1",
        "--model",
        "openrouter/deepseek/deepseek-v4-flash-0731",
        "-M",
        'provider={"order":["DeepInfra"],"allow_fallbacks":false}',
        "--reasoning-effort",
        "low",
        "--dry-run",
    ]
    assert main(argv) == 0
    assert "config_hash=" in capsys.readouterr().out


def test_preset_supplies_model_pin_and_effort_and_flags_override() -> None:
    (cell,) = parse_args(["--preset", "deepseek-v4.1"]).cells
    assert cell.model == "openrouter/deepseek/deepseek-v4.1-flash-1017"
    assert dict(cell.model_args)["provider"]["allow_fallbacks"] is False
    assert cell.reasoning_effort == "low"


def test_model_arg_still_overrides_pin() -> None:
    pinned = '{"order":["Other"],"allow_fallbacks":false}'
    (over,) = parse_args(["--preset", "luna", "-M", f"provider={pinned}"]).cells
    assert dict(over.model_args)["provider"]["order"] == ["Other"]


def test_preset_alias_same_dest() -> None:
    assert (
        parse_args(["--preset", "luna"]).cells
        == parse_args(["--model-preset", "luna"]).cells
    )


def test_registry_matches_recorded_models() -> None:
    models = load_models()
    pin = {"allow_fallbacks": False}
    want = {
        "luna": (
            "openrouter/openai/gpt-6-luna",
            {"order": ["OpenAI"], **pin},
            0.10,
            0.50,
            False,
        ),
        "deepseek-v4": (
            "openrouter/deepseek/deepseek-v4-flash-0731",
            {"order": ["DeepInfra"], **pin},
            0.06,
            0.18,
            True,
        ),
        "gemini-3.8-flash": (
            "openrouter/google/gemini-3.8-flash",
            {"order": ["Google AI Studio"], **pin},
            0.75,
            3.75,
            False,
        ),
        "deepseek-v4.1": (
            "openrouter/deepseek/deepseek-v4.1-flash-1017",
            {"order": ["DeepInfra"], **pin, "quantizations": ["fp8"]},
            0.098,
            0.294,
            True,
        ),
    }
    for name, (model, provider, p_in, p_out, open_weight) in want.items():
        e = models[name]
        assert (e.model, e.provider, e.price_in, e.price_out, e.open_weight) == (
            model,
            provider,
            p_in,
            p_out,
            open_weight,
        )
        assert e.reasoning_effort == "low" and not e.todo
    assert "fp8" in models["deepseek-v4"].note


def test_placeholders_are_todo_and_refused(capsys: pytest.CaptureFixture[str]) -> None:
    for name in ("todo-open-family",):
        assert load_models()[name].todo
        with pytest.raises(SystemExit) as exc:
            parse_args(["--model-preset", name])
        assert exc.value.code == 2
        assert f"entry {name} has TODO fields" in capsys.readouterr().err


def test_two_presets_double_cells(capsys: pytest.CaptureFixture[str]) -> None:
    from run_sweep import main

    argv = ["--workflow", "w1", "--scopes", "read_write", "--isolation", "isolated"]
    argv += ["--benign-only", "--limit", "1", "--dry-run"]
    assert main([*argv, "--model-preset", "luna"]) == 0
    one = capsys.readouterr().out
    assert (
        main(
            [
                *argv,
                "--model-preset",
                "luna",
                "deepseek-v4",
                "--reasoning-effort",
                "low",
                "high",
            ]
        )
        == 0
    )
    four = capsys.readouterr().out
    assert one.count("config_hash=") == 1 and four.count("config_hash=") == 4
    assert (
        len(
            {
                ln.split("config_hash=")[1].split()[0]
                for ln in four.splitlines()
                if "config_hash=" in ln
            }
        )
        == 4
    )


def test_dry_run_estimates_cost_and_crosses_the_new_axes(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from run_sweep import main

    argv = ["--preset", "gemini-3.8-flash", "--workflow", "w1", "--limit", "2"]
    argv += ["--scopes", "read_write", "--identity", "off", "guard"]
    argv += ["--defense", "none", "spotlight", "--isolation", "isolated", "--dry-run"]
    argv += ["--log-dir", str(tmp_path / "none")]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert out.count("config_hash=") == 4 and "total: 8 pairs" in out
    want = estimate_usd(8, False, 0, load_models()["gemini-3.8-flash"], None)
    assert f"${want:,.2f}" in out and "default pilot tokens" in out


def test_dry_run_crosses_new_axes(capsys: pytest.CaptureFixture[str]) -> None:
    from run_sweep import main

    argv = ["--model", "mockllm/model", "--workflow", "w3", "--scopes", "read_write"]
    argv += ["--isolation", "isolated", "--relay-stages", "0", "1", "--dry-run"]
    assert main(argv) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if "config_hash=" in ln]
    assert len(lines) == 2
    assert "relay=0" in lines[0] and "relay=1" in lines[1]
    assert "handoff=free_text" in lines[0] and "gate=False" in lines[0]
    assert lines[0].split("config_hash=")[1] != lines[1].split("config_hash=")[1]


def test_paid_run_is_refused_while_a_governing_document_is_a_draft(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import run_sweep

    monkeypatch.setattr(run_sweep, "draft_documents", lambda: ["addendum"])
    monkeypatch.setattr(
        run_sweep, "eval_set", lambda *a, **k: pytest.fail("must not start the eval")
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    argv = ["--preset", "deepseek-v4.1", "--workflow", "w2", "--limit", "1"]
    assert run_sweep.main(argv) == 3
    assert "refusing a paid run" in capsys.readouterr().err


def test_data_book_is_dated_and_carries_no_document_text(tmp_path: Path) -> None:
    from data_book import commits, render, runs
    from inspect_ai import eval
    from inspect_ai.model import ModelOutput, get_model

    from eduinject.corpus import MARKER
    from eduinject.task_w1 import eduinject_w1

    def echo(input: Any, tools: Any, tool_choice: Any, config: Any) -> Any:
        if tools:
            return ModelOutput.for_tool_call(
                "mockllm/model", "submit", {"answer": "ok"}
            )
        return ModelOutput.from_content("mockllm/model", f"summary {MARKER}")

    eval(
        eduinject_w1(benign_only=True),
        model=get_model("mockllm/model", custom_outputs=echo),
        log_dir=str(tmp_path),
        display="none",
        limit=1,
    )
    book = render(commits("2026-10-01") + runs(str(tmp_path), None))
    assert "run w1 baseline scope=read_write" in book and "samples=1" in book
    assert all(line.startswith(("#", "- ", "")) for line in book.splitlines())
    assert MARKER not in book


def test_defense_arms_are_eight_per_scope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from run_sweep import ARMS, main

    assert len(set(ARMS["defense"])) == 8
    assert sum(c.gate for c in ARMS["defense"]) == 4
    argv = ["--model", "mockllm/model", "--workflow", "w1", "--scopes", "read_write"]
    assert main([*argv, "--arms", "defense", "--limit", "1", "--dry-run"]) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if "config_hash=" in ln]
    assert len(lines) == 8
    assert len({ln.split("config_hash=")[1].split()[0] for ln in lines}) == 8
    assert sum("handoff=typed" in ln and "defense=spotlight" in ln for ln in lines) == 2


def test_halflife_arms(capsys: pytest.CaptureFixture[str]) -> None:
    from run_sweep import main

    argv = ["--model", "mockllm/model", "--workflow", "w3", "--scopes", "read_write"]
    assert main([*argv, "--arms", "halflife", "--limit", "1", "--dry-run"]) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if "config_hash=" in ln]
    assert [f"relay={n}" in ln for n, ln in enumerate(lines)] == [True] * 4
    assert all("isolated=True" in ln and "gate=False" in ln for ln in lines)


@pytest.mark.parametrize(
    "flag", ["--isolation", "--handoff-modes", "--gate", "--relay-stages", "--defense"]
)
def test_arms_conflict_with_axis_flags(flag: str) -> None:
    value = {"--isolation": "both", "--relay-stages": "1", "--gate": "off"}.get(
        flag, "none" if flag == "--defense" else "typed"
    )
    with pytest.raises(SystemExit) as exc:
        parse_args(["--model", "mockllm/model", "--arms", "halflife", flag, value])
    assert exc.value.code == 2


def test_defense_arms_refuse_identity_facts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = ["--model", "mockllm/model", "--arms", "defense", "--identity", "facts"]
    with pytest.raises(SystemExit) as exc:
        parse_args(argv)
    assert exc.value.code == 2
    assert "--identity facts" in capsys.readouterr().err


def test_dry_run_prints_cost_per_cell(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from run_sweep import main

    argv = ["--preset", "gemini-3.8-flash", "--workflow", "w1", "--limit", "1"]
    argv += ["--scopes", "read_write", "--arms", "halflife", "--dry-run"]
    argv += ["--log-dir", str(tmp_path / "none")]
    assert main(argv) == 0
    out = capsys.readouterr().out
    cells = [ln for ln in out.splitlines() if "config_hash=" in ln]
    assert len(cells) == 4 and all(" est=$" in ln for ln in cells)
    assert "total: " in out


def test_hosts_are_a_real_axis_and_duplicates_dedupe(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from run_sweep import main

    name = "gemini-3.8-flash"
    argv = ["--preset", name, "--workflow", "w1", "--scopes", "read_write"]
    argv += ["--isolation", "isolated", "--limit", "1", "--dry-run"]
    assert main([*argv, "--hosts", "DeepInfra", "Together", "DeepInfra"]) == 0
    captured = capsys.readouterr()
    lines = [ln for ln in captured.out.splitlines() if "config_hash=" in ln]
    assert len(lines) == 2 and "duplicate cell dropped" in captured.err
    assert len({ln.split("config_hash=")[1].split()[0] for ln in lines}) == 2
    with pytest.raises(SystemExit) as exc:
        parse_args(["--model", "m", "--hosts", "X", "-M", "provider=Y"])
    assert exc.value.code == 2


def _lines(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if "config_hash=" in ln]


def test_core_arms_are_four_per_scope(capsys: pytest.CaptureFixture[str]) -> None:
    from run_sweep import ARMS, main

    assert len(set(ARMS["core"])) == 4
    argv = ["--model", "mockllm/model", "--workflow", "w1", "--arms", "core"]
    argv += ["--scopes", "standard", "read_write", "--limit", "1", "--dry-run"]
    assert main(argv) == 0
    lines = _lines(capsys.readouterr().out)
    assert len(lines) == 8 and all("swap=None" in ln for ln in lines)
    got = [
        tuple(f in ln for f in ("isolated=True", "handoff=typed", "gate=True"))
        for ln in lines[:4]
    ]
    # U at both isolations, G, TG (doc 14 §2).
    assert got == [
        (False, False, False),
        (True, False, False),
        (False, False, True),
        (True, True, True),
    ]


def test_swap_arm_sets_swap_stage_and_prices_1_6_pairs(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from run_sweep import ARMS, main

    (arm,) = ARMS["swap"]
    assert arm.swap_stage == "action" and arm.isolated is False
    argv = ["--preset", "gemini-3.8-flash", "--workflow", "w1", "--dry-run"]
    argv += ["--scopes", "read_write", "--log-dir", str(tmp_path / "none")]
    assert main([*argv, "--arms", "swap"]) == 0
    (swap,) = _lines(capsys.readouterr().out)
    assert main([*argv, "--isolation", "control", "--swap-stage", "action"]) == 0
    (axis,) = _lines(capsys.readouterr().out)
    assert main([*argv, "--isolation", "control"]) == 0
    (plain,) = _lines(capsys.readouterr().out)
    assert swap == axis and "swap=action" in swap and "swap=None" in plain
    runs = int(plain.split("runs=")[1].split()[0])
    entry = load_models()["gemini-3.8-flash"]
    base = estimate_usd(runs, False, 0, entry, None)
    assert base is not None
    assert plain.endswith(f" est=${base:,.2f}")
    assert swap.endswith(f" est=${1.6 * base:,.2f}")
    assert swap.split("config_hash=")[1][:16] != plain.split("config_hash=")[1][:16]


def test_swap_stage_is_an_axis(capsys: pytest.CaptureFixture[str]) -> None:
    from run_sweep import main

    argv = ["--model", "mockllm/model", "--scopes", "read_write", "--limit", "1"]
    argv += ["--isolation", "control", "--swap-stage", "analysis", "action"]
    assert main([*argv, "--dry-run"]) == 0
    lines = _lines(capsys.readouterr().out)
    assert ["swap=analysis" in ln for ln in lines] == [True, False]
    assert "swap=action" in lines[1]


@pytest.mark.parametrize("argv", [["--arms", "core"], ["--arms", "swap"]])
def test_swap_stage_conflicts_with_arms(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        parse_args(["--model", "m", *argv, "--swap-stage", "action"])
    assert exc.value.code == 2
    assert "--swap-stage" in capsys.readouterr().err


@pytest.mark.parametrize("isolation", [[], ["--isolation", "both"]])
def test_swap_stage_needs_the_control_isolation(
    isolation: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        parse_args(["--model", "m", *isolation, "--swap-stage", "action"])
    assert exc.value.code == 2
    assert "--isolation control" in capsys.readouterr().err


def test_core_arms_refuse_identity_facts(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        parse_args(["--model", "m", "--arms", "core", "--identity", "facts"])
    assert exc.value.code == 2
    assert "--identity facts" in capsys.readouterr().err
    assert parse_args(["--model", "m", "--arms", "swap", "--identity", "facts"])


def test_reader_preset_crosses_models_and_diagonal_is_plain(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from run_sweep import main

    names = ["luna", "gemini-3.8-flash"]
    argv = ["--workflow", "w1", "--scopes", "read_write", "--limit", "4"]
    argv += ["--isolation", "isolated", "--dry-run", "--log-dir", str(tmp_path / "x")]
    argv += ["--model-preset", *names]
    assert main(argv) == 0
    plain = _lines(capsys.readouterr().out)
    assert main([*argv, "--reader-preset", *names]) == 0
    lines = _lines(capsys.readouterr().out)
    assert len({ln.split("config_hash=")[1][:16] for ln in lines}) == len(lines) == 4
    diagonal = [ln for ln in lines if "reader=None" in ln]
    assert diagonal == plain, "the diagonal is the ordinary cell, same hash and price"
    off = [ln for ln in lines if ln not in diagonal]
    models = load_models()
    assert {
        tuple(ln.split(f"{k}=")[1].split()[0] for k in ("reader", "model"))
        for ln in off
    } == {(models[a].model, models[b].model) for a, b in (names, names[::-1])}
    dearer = estimate_usd(4, False, 0, models["gemini-3.8-flash"], None)
    assert all(
        ln.endswith(f" est=${dearer:,.2f} (upper bound: dearer of reader/actor)")
        for ln in off
    )


def test_todo_reader_preset_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        parse_args(["--preset", "luna", "--reader-preset", "todo-open-family"])
    assert exc.value.code == 2
    assert "todo-open-family has TODO fields" in capsys.readouterr().err


def test_a_paid_reader_behind_a_mock_actor_is_a_paid_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import run_sweep

    monkeypatch.setattr(run_sweep, "draft_documents", lambda: ["addendum"])
    monkeypatch.setattr(
        run_sweep, "eval_set", lambda *a, **k: pytest.fail("must not start the eval")
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    argv = ["--model", "mockllm/model", "--reader-preset", "luna", "--limit", "1"]
    assert run_sweep.main(argv) == 3
    assert "refusing a paid run" in capsys.readouterr().err


def _confirm(tmp_path: Path, *extra: str) -> list[str]:
    argv = ["--workflow", "w1", "--split", "confirm", "--benign-only", "--limit", "1"]
    argv += ["--scopes", "read_only", "--isolation", "isolated"]
    return [*argv, "--log-dir", str(tmp_path / "logs"), *extra]


@pytest.fixture
def swept(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every `eval_set` call, none of which runs."""
    import run_sweep

    calls: list[dict[str, Any]] = []

    def fake(tasks: Any, **kwargs: Any) -> tuple[bool, list[Any]]:
        calls.append({"tasks": tasks, **kwargs})
        return True, []

    monkeypatch.setattr(run_sweep, "eval_set", fake)
    return calls


def test_confirm_split_is_refused_without_a_freeze(
    tmp_path: Path, swept: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    from run_sweep import main

    assert main(_confirm(tmp_path, "--model", "mockllm/model")) == 3
    assert "no freeze entry" in capsys.readouterr().err and not swept


def test_held_out_model_needs_confirm_and_a_freeze(
    tmp_path: Path, swept: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from run_sweep import main

    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    held = ["--model-preset", "gemini-3.8-flash", "--allow-draft-docs"]
    slug = ["--model", load_models()["gemini-3.8-flash"].model, "--allow-draft-docs"]
    slug += ["-M", 'provider={"order":["Google AI Studio"],"allow_fallbacks":false}']
    reader = ["--model-preset", "luna", "--reader-preset", "gemini-3.8-flash"]
    dev = [a if a != "confirm" else "dev" for a in _confirm(tmp_path)]
    for who in (held, slug, [*reader, "--allow-draft-docs"]):
        assert main([*dev, *who]) == 3
        assert main([*_confirm(tmp_path), *who]) == 3
    assert not swept


def test_dry_run_reports_freeze_and_does_not_refuse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from run_sweep import main

    assert main(_confirm(tmp_path, "--model", "mockllm/model", "--dry-run")) == 0
    assert "freeze: no freeze entry" in capsys.readouterr().out


def test_split_selects_samples_and_defaults_to_dev(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from run_sweep import main

    argv = ["--workflow", "w2", "--model", "mockllm/model", "--dry-run"]
    argv += ["--scopes", "read_write", "--isolation", "isolated", "--epochs", "2"]
    assert main(argv) == 0
    assert f"total: {2 * 74} pairs" in capsys.readouterr().out
    assert main([*argv, "--split", "confirm"]) == 0
    assert f"total: {2 * 48} pairs" in capsys.readouterr().out


def test_confirm_run_copies_the_entry_and_owns_its_log_dir(
    tmp_path: Path, swept: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    import run_sweep

    from eduinject.freeze import FreezeEntry

    entry = FreezeEntry("0" * 64, "c", "2026-12-01", ("gate",), ("baseline",), (), "n")
    monkeypatch.setattr(run_sweep.freeze, "freeze_problems", list)
    monkeypatch.setattr(run_sweep.freeze, "load_freeze", lambda: [entry])
    argv = _confirm(tmp_path, "--model", "mockllm/model")
    assert run_sweep.main(argv) == 0
    (call,) = swept
    assert {s.metadata["split"] for t in call["tasks"] for s in t.dataset} == {
        "confirm"
    }
    copy = tmp_path / "logs" / run_sweep.FREEZE_COPY
    assert '"2026-12-01"' in copy.read_text("utf-8")
    # A dev sweep into a confirm log dir would be taken as already done.
    assert run_sweep.main([a if a != "confirm" else "dev" for a in argv]) == 3
    copy.unlink()
    (tmp_path / "logs" / "x.eval").write_text("")
    assert run_sweep.main(argv) == 3


def test_confirm_refuses_a_manifest_outside_the_frozen_corpus(
    tmp_path: Path,
    generated_corpus: Path,
    swept: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import run_sweep

    monkeypatch.setattr(run_sweep.freeze, "freeze_problems", list)
    other = generated_corpus / "corpus" / "manifest_w1.jsonl"
    argv = _confirm(tmp_path, "--model", "mockllm/model", "--manifest", str(other))
    assert run_sweep.main(argv) == 3 and not swept


@pytest.mark.parametrize(
    "extra",
    [
        ["--model", "openrouter/google/gemini-3.8-flash:nitro"],
        ["--model", "openrouter/google/gemini-3.8-flash-20260901"],
        ["--model", "openrouter/Google/Gemini-3.8-flash"],
        [
            "--model",
            "openrouter/openai/gpt-6-luna",
            "-M",
            'models=["google/gemini-3.8-flash"]',
        ],
    ],
)
def test_held_out_model_is_refused_under_any_spelling(
    extra: list[str],
    tmp_path: Path,
    swept: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from run_sweep import main

    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    pin = ["-M", 'provider={"order":["Google AI Studio"],"allow_fallbacks":false}']
    dev = [a if a != "confirm" else "dev" for a in _confirm(tmp_path)]
    assert main([*dev, *extra, *pin, "--allow-draft-docs"]) == 3
    assert not swept


def test_a_relabelled_manifest_is_refused(
    tmp_path: Path,
    generated_corpus: Path,
    swept: list[dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    from run_sweep import main

    source = generated_corpus / "corpus" / "manifest_w1.jsonl"
    edited = generated_corpus / "corpus" / "manifest_relabelled.jsonl"
    edited.write_text(source.read_text("utf-8").replace('"confirm"', '"dev"'), "utf-8")
    argv = ["--workflow", "w1", "--model", "mockllm/model", "--manifest", str(edited)]
    try:
        assert main([*argv, "--log-dir", str(tmp_path / "logs")]) == 2
    finally:
        edited.unlink()  # the corpus fixture is shared across tests
    assert "not its scenario" in capsys.readouterr().err.replace("its \n", "its ")
    assert not swept


def test_freezes_never_share_a_log_dir(
    tmp_path: Path, swept: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    import run_sweep

    from eduinject.freeze import FreezeEntry

    old = FreezeEntry("0" * 64, "c", "2026-12-01", ("gate",), ("baseline",), (), "n")
    new = old._replace(digest="1" * 64)
    monkeypatch.setattr(run_sweep.freeze, "freeze_problems", list)
    monkeypatch.setattr(run_sweep.freeze, "load_freeze", lambda: [old])
    argv = _confirm(tmp_path, "--model", "mockllm/model")
    assert run_sweep.main(argv) == 0
    (tmp_path / "logs" / "x.eval").write_text("")
    assert run_sweep.main(argv) == 0  # the same freeze may resume
    monkeypatch.setattr(run_sweep.freeze, "load_freeze", lambda: [old, new])
    assert run_sweep.main(argv) == 3
    nested = [a if a != "confirm" else "dev" for a in argv]
    nested[nested.index("--log-dir") + 1] = str(tmp_path / "logs" / "sub")
    assert run_sweep.main(nested) == 3
