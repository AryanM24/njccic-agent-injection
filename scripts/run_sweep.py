#!/usr/bin/env python3
"""Sweep the pipeline across write scope and stage isolation.

Isolation is swept, not assumed: `--isolation both` runs the isolated
condition alongside its negative control, and a result that does not move
between them is a result about the workflow rather than about the injection.

Every cell is a separate task whose metadata carries `config_hash(...)`, so the
pinned extraction stack, the document versions and the run parameters behind
any number in the logs are recoverable without consulting this script.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, NamedTuple, get_args

from dotenv import find_dotenv, load_dotenv
from inspect_ai import eval_set

from eduinject.agents.task_facts import IDENTITY_MODES
from eduinject.config import draft_documents
from eduinject.defense import DEFENSES
from eduinject.task import DEFAULT_MANIFEST as W2_MANIFEST
from eduinject.task import ReasoningEffort, eduinject_w2
from eduinject.task_w1 import DEFAULT_MANIFEST as W1_MANIFEST
from eduinject.task_w1 import eduinject_w1
from eduinject.task_w3 import DEFAULT_MANIFEST as W3_MANIFEST
from eduinject.task_w3 import eduinject_w3

ISOLATION_CHOICES = {"isolated": [True], "control": [False], "both": [True, False]}
SCOPE_NAMES = ("read_only", "standard", "read_write")
"""Shared across all three workflows -- tools.ats.SCOPES, tools.helpdesk.SCOPES
and tools.parentmail.SCOPES all use this same key set, so the sweep's --scopes
flag doesn't need to import a workflow-specific SCOPES dict just to validate."""

WORKFLOWS = {
    "w1": (eduinject_w1, W1_MANIFEST),
    "w2": (eduinject_w2, W2_MANIFEST),
    "w3": (eduinject_w3, W3_MANIFEST),
}


class Preset(NamedTuple):
    """A model with its pinned host and list price (USD per 1M tokens)."""

    model: str
    provider: dict[str, Any]
    price_in: float
    price_out: float


def _pin(*hosts: str, **extra: Any) -> dict[str, Any]:
    return {"order": list(hosts), "allow_fallbacks": False, **extra}


PRESETS: dict[str, Preset] = {
    # First edition (doc 06 §2). Luna is also a second-edition model (doc 10 §6).
    "luna": Preset("openrouter/openai/gpt-6-luna", _pin("OpenAI"), 0.10, 0.50),
    "deepseek-v4": Preset(
        "openrouter/deepseek/deepseek-v4-flash-0731", _pin("DeepInfra"), 0.06, 0.18
    ),
    # Second edition (doc 10 §6). Prices are OpenRouter's list prices for the
    # pinned host, read from openrouter.ai/api/v1 on 2026-10-25; re-check them
    # before a run, since a dry run's estimate is only as good as these.
    "gemini-3.8-flash": Preset(
        "openrouter/google/gemini-3.8-flash", _pin("Google AI Studio"), 0.75, 3.75
    ),
    "deepseek-v4.1": Preset(
        "openrouter/deepseek/deepseek-v4.1-flash-1017",
        _pin("DeepInfra", quantizations=["fp8"]),
        0.098,
        0.294,
    ),
}
"""Named models for `--preset`. A dated snapshot is used wherever one exists, so
the same slug cannot silently serve a newer model mid-study."""

TOKENS_PER_PAIR = (23_000, 9_500)
"""(input, output) tokens for one attack+twin sample, from the first edition's
pilot (RUNNING.md step 4). A twin-only sample is about half. Frontier models
with thinking on may use more output: the pilot run checks this."""


def estimate_usd(samples: int, twin_only: bool, preset: Preset) -> float:
    """Rough cost of `samples` runs at the preset's prices."""
    scale = 0.5 if twin_only else 1.0
    tin, tout = (n * scale * samples / 1e6 for n in TOKENS_PER_PAIR)
    return tin * preset.price_in + tout * preset.price_out


def parse_model_arg(text: str) -> tuple[str, Any]:
    """Parse one `-M key=value`; the value is JSON if it parses, else a string."""
    key, sep, raw = text.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"expected key=value, got {text!r}")
    try:
        return key, json.loads(raw)
    except json.JSONDecodeError:
        return key, raw


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=None,
        help="Model to evaluate (defaults to the preset's, else $INSPECT_EVAL_MODEL).",
    )
    parser.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        default=None,
        help="Named model with its host pin and price (see PRESETS). Explicit "
        "--model / -M override it.",
    )
    parser.add_argument(
        "-M",
        "--model-arg",
        dest="model_args",
        action="append",
        type=parse_model_arg,
        default=[],
        metavar="KEY=VALUE",
        help="Provider arg bound with the model (repeatable; JSON values). "
        "OpenRouter models must pin their host, e.g. "
        '-M \'provider={"order":["DeepInfra"],"allow_fallbacks":false}\'.',
    )
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        choices=get_args(ReasoningEffort),
        help="Fixed reasoning effort for every stage (recorded in config_hash).",
    )
    parser.add_argument(
        "--log-dir", default="logs/sweep", help="Directory for the eval set logs."
    )
    parser.add_argument(
        "--workflow",
        default="w2",
        choices=sorted(WORKFLOWS),
        help="Workflow to sweep.",
    )
    parser.add_argument(
        "--scopes",
        nargs="+",
        default=list(SCOPE_NAMES),
        choices=list(SCOPE_NAMES),
        help="Write scopes to sweep.",
    )
    parser.add_argument(
        "--isolation",
        default="both",
        choices=sorted(ISOLATION_CHOICES),
        help="Isolation conditions to sweep ('both' includes the negative control).",
    )
    parser.add_argument(
        "--identity",
        nargs="+",
        default=["off"],
        choices=list(IDENTITY_MODES),
        help="identity_mode cells to sweep: off (v1), facts (verified task facts "
        "for the action stage), guard (facts enforced by the tools). doc 10 §2-3.",
    )
    parser.add_argument(
        "--defense",
        nargs="+",
        default=["none"],
        choices=list(DEFENSES),
        help="Prompt-level defense cells to sweep (spotlight = datamarking, "
        "doc 10 §4).",
    )
    parser.add_argument(
        "--allow-draft-docs",
        action="store_true",
        help="Run even though a governing design document is still a draft. Such "
        "runs are NOT pre-registered; use only for pilots, and say so.",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Path to the corpus manifest (defaults to the chosen workflow's).",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=None,
        help="Repetitions per sample. Doc 4 SS13.4 sets a floor of ten for any "
        "reportable run.",
    )
    parser.add_argument(
        "--benign-only",
        action="store_true",
        help="Phase 2 baseline: run only the twin, no attack artifact at all. "
        "Omits action_divergence (attack-vs-twin only) from the scorer set.",
    )
    parser.add_argument(
        "--controls",
        action="store_true",
        help="Run the benign-but-weird controls manifest (implies --benign-only). "
        "Use --scopes standard read_write: at read_only there is nothing to "
        "complete. Compare against a --benign-only run of the main manifest.",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit samples per task."
    )
    parser.add_argument(
        "--max-connections",
        type=int,
        default=None,
        help="Max concurrent model connections.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build every cell and print its run count and config_hash, then "
        "stop before contacting the model.",
    )
    args = parser.parse_args(argv)
    preset = PRESETS.get(args.preset) if args.preset else None
    if preset:
        args.model = args.model or preset.model
        if not any(key == "provider" for key, _ in args.model_args):
            args.model_args = [("provider", preset.provider), *args.model_args]
        # Every reported run is pinned at low effort (doc 06 §2, doc 10 §6).
        args.reasoning_effort = args.reasoning_effort or "low"
    args.model = args.model or os.environ.get("INSPECT_EVAL_MODEL")
    return args


def main(argv: list[str] | None = None) -> int:
    # Inspect loads .env only when the eval starts; tasks bind their model
    # (and need its API key) before that.
    load_dotenv(find_dotenv(usecwd=True))
    args = parse_args(argv)
    if not args.model:
        print(
            "no model: pass --model or set INSPECT_EVAL_MODEL (see .env.example)",
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        # Building a task constructs the model client, which refuses to start
        # without a key even though a dry run never calls the model. A placeholder
        # keeps the dry run free and usable before any key exists.
        for variable in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
            os.environ.setdefault(variable, "dry-run-placeholder")

    task_fn, default_manifest = WORKFLOWS[args.workflow]
    manifest = args.manifest or default_manifest

    isolation = ISOLATION_CHOICES[args.isolation]
    tasks = [
        task_fn(
            scope=scope,
            isolated=isolated,
            manifest=manifest,
            epochs=args.epochs,
            benign_only=args.benign_only,
            controls=args.controls,
            model=args.model,
            model_args=dict(args.model_args) or None,
            reasoning_effort=args.reasoning_effort,
            identity_mode=identity,
            defense=defense,
        )
        for scope in args.scopes
        for isolated in isolation
        for identity in args.identity
        for defense in args.defense
    ]

    print(
        f"sweeping {len(tasks)} cell(s) of {args.workflow} on {args.model} "
        f"(epochs={args.epochs}, benign_only={args.benign_only}, "
        f"controls={args.controls}, model_args={dict(args.model_args)}, "
        f"reasoning_effort={args.reasoning_effort})"
    )
    total = 0
    for task in tasks:
        meta = task.metadata or {}
        samples = len(task.dataset)
        if args.limit is not None:
            samples = min(samples, args.limit)
        runs = samples * (task.epochs or 1)
        total += runs
        print(
            f"  scope={meta['scope']:<10} "
            f"isolated={meta['isolated']!s:<5} "
            f"identity={meta['identity_mode']:<5} "
            f"defense={meta['defense']:<9} "
            f"runs={runs:<6} "
            f"config_hash={meta['config_hash']}"
        )
    twin_only = args.benign_only or args.controls
    unit = "twin runs" if twin_only else "pairs"
    print(f"total: {total} {unit}")
    if args.preset:
        usd = estimate_usd(total, twin_only, PRESETS[args.preset])
        print(f"estimated cost: ${usd:,.2f} (+~20% retries; list prices, see PRESETS)")
    drafts = draft_documents()
    if drafts:
        print(f"governing documents still in draft: {', '.join(drafts)}")
    if args.dry_run:
        return 0
    paid = not str(args.model).startswith("mockllm/")
    if drafts and paid and not args.allow_draft_docs:
        print(
            "refusing a paid run while governing documents are drafts: sign and "
            "push them first (doc 10 §8), or pass --allow-draft-docs for a pilot",
            file=sys.stderr,
        )
        return 3

    success, logs = eval_set(
        tasks,
        log_dir=args.log_dir,
        model=args.model,
        limit=args.limit,
        max_connections=args.max_connections,
    )

    print(f"\n{'config_hash':<18}{'scope':<12}{'isolated':<10}{'status':<10}scores")
    for log in logs:
        metadata = log.eval.metadata or {}
        scores = []
        for score in (log.results.scores if log.results else []) or []:
            # A dict-valued Score becomes one EvalScore per key, all carrying
            # the same scorer name, so both are needed to identify a number.
            label = (
                score.name
                if score.name == score.scorer
                else f"{score.scorer}.{score.name}"
            )
            mean = score.metrics.get("mean")
            if mean is not None:
                scores.append(f"{label}={mean.value:g}")
        print(
            f"{metadata.get('config_hash')!s:<18}"
            f"{metadata.get('scope')!s:<12}"
            f"{metadata.get('isolated')!s:<10}"
            f"{log.status:<10}"
            f"{', '.join(scores)}"
        )

    print(f"\nlogs: {Path(args.log_dir).resolve()}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
