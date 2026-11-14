"""run_sweep.py argument parsing."""

import argparse
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_sweep import parse_args, parse_model_arg


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
    args = parse_args(["--preset", "deepseek-v4.1"])
    assert args.model == "openrouter/deepseek/deepseek-v4.1-flash-1017"
    assert dict(args.model_args)["provider"]["allow_fallbacks"] is False
    assert args.reasoning_effort == "low"
    pinned = '{"order":["Other"],"allow_fallbacks":false}'
    over = parse_args(["--preset", "luna", "-M", f"provider={pinned}"])
    assert dict(over.model_args)["provider"]["order"] == ["Other"]


def test_dry_run_estimates_cost_and_crosses_the_new_axes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from run_sweep import PRESETS, estimate_usd, main

    argv = ["--preset", "gemini-3.8-flash", "--workflow", "w1", "--limit", "2"]
    argv += ["--scopes", "read_write", "--identity", "off", "guard"]
    argv += ["--defense", "none", "spotlight", "--isolation", "isolated", "--dry-run"]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert out.count("config_hash=") == 4 and "total: 8 pairs" in out
    assert f"${estimate_usd(8, False, PRESETS['gemini-3.8-flash']):,.2f}" in out


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
