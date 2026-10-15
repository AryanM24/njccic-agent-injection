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
