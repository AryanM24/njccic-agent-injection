"""run_sweep.py argument parsing."""

import argparse
import sys
from pathlib import Path

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
        "--workflow", "w2", "--benign-only", "--epochs", "1", "--limit", "1",
        "--model", "openrouter/deepseek/deepseek-v4-flash-0731",
        "-M", 'provider={"order":["DeepInfra"],"allow_fallbacks":false}',
        "--reasoning-effort", "low", "--dry-run",
    ]
    assert main(argv) == 0
    assert "config_hash=" in capsys.readouterr().out
