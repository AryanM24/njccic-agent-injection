"""The docs name what the code has: every module, script, sweep flag and
analyze subcommand (PI instruction 2026-11-14: docs are kept current). The
DOC_VERSIONS ↔ docs/design/ check lives in test_design_docs_in_sync.py."""

import argparse
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "eduinject"
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
RUNNING = (ROOT / "RUNNING.md").read_text(encoding="utf-8")
GATED = {"payloads.py"}  # gitignored Tier 1 module; AGENTS.md names it by path

sys.path.insert(0, str(ROOT / "scripts"))


def _parser(module: str) -> argparse.ArgumentParser:
    """The parser `module.parse_args` builds, captured before it parses."""

    class Built(Exception):
        pass

    def capture(self: argparse.ArgumentParser, *_: Any, **__: Any) -> None:
        raise Built(self)

    mod = __import__(module)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(argparse.ArgumentParser, "parse_args", capture)
        try:
            mod.parse_args([])
        except Built as built:
            return built.args[0]  # type: ignore[no-any-return]
    raise AssertionError(f"{module}.parse_args built no parser")


def test_every_module_is_in_agents_md() -> None:
    missing = [
        rel
        for p in sorted(PACKAGE.rglob("*.py"))
        if p.name not in GATED and "__pycache__" not in p.parts
        if f"`{(rel := p.relative_to(PACKAGE).as_posix())}`" not in AGENTS
    ]
    assert not missing, f"add to AGENTS.md's package table: {missing}"


def test_every_script_is_in_agents_md() -> None:
    missing = [
        f"scripts/{p.name}"
        for p in sorted((ROOT / "scripts").glob("*.py"))
        if f"`scripts/{p.name}`" not in AGENTS
    ]
    assert not missing, f"add to AGENTS.md's project table: {missing}"


def test_every_sweep_flag_is_in_running_md() -> None:
    flags = {
        opt
        for action in _parser("run_sweep")._actions
        for opt in action.option_strings
        if opt.startswith("--") and opt != "--help"
    }
    assert flags
    missing = sorted(f for f in flags if f not in RUNNING)
    assert not missing, f"document in RUNNING.md: {missing}"


def test_every_analyze_subcommand_is_in_running_md() -> None:
    (sub,) = (
        a
        for a in _parser("analyze")._actions
        if isinstance(a, argparse._SubParsersAction)
    )
    commands = set(sub.choices)
    assert commands
    missing = sorted(c for c in commands if f"analyze.py {c}" not in RUNNING)
    assert not missing, f"document in RUNNING.md: {missing}"
