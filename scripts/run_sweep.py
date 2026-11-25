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
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple, get_args

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import find_dotenv, load_dotenv
from estimate_cost import estimate_usd, token_stats
from inspect_ai import eval_set

from eduinject import freeze
from eduinject.agents.task_facts import IDENTITY_MODES
from eduinject.config import draft_documents
from eduinject.defense import DEFENSES
from eduinject.models import ModelEntry, load_models
from eduinject.task import DEFAULT_MANIFEST as W2_MANIFEST
from eduinject.task import HANDOFF_MODES, ReasoningEffort, eduinject_w2
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


ROOT = Path(__file__).resolve().parents[1]
FREEZE_COPY = "FREEZE.json"
"""The freeze entry a confirm run was made under, written to its log directory."""


class Cell(NamedTuple):
    """One model configuration of the sweep: model, bound args, effort, price."""

    model: str | None
    model_args: tuple[tuple[str, Any], ...]
    reasoning_effort: str | None
    entry: ModelEntry | None
    reader: ModelEntry | None = None
    """Registry entry that runs every stage before action (doc 14 §5)."""


class Condition(NamedTuple):
    """The axes a named arm fixes together."""

    isolated: bool
    handoff_mode: str
    defense: str
    relay_stages: int
    gate: bool
    swap_stage: str | None = None


ARMS = {
    "defense": [
        Condition(iso, hand, defense, 0, gate)
        for gate in (False, True)
        for iso, hand, defense in [
            (False, "free_text", "none"),
            (True, "free_text", "none"),
            (True, "typed", "none"),
            (True, "typed", "spotlight"),
        ]
    ],
    "halflife": [Condition(True, "free_text", "none", n, False) for n in range(4)],
    "core": [
        Condition(False, "free_text", "none", 0, False),
        Condition(True, "free_text", "none", 0, False),
        Condition(False, "free_text", "none", 0, True),
        Condition(True, "typed", "none", 0, True),
    ],
    "swap": [Condition(False, "free_text", "none", 0, False, "action")],
}


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
        "--model-preset",
        "--preset",
        dest="model_presets",
        nargs="+",
        choices=sorted(load_models()),
        default=[],
        help="Registry models (configs/models.json) with host pin and price. "
        "Several names sweep the model axis; the same name may repeat. Explicit "
        "--model / -M override the pin.",
    )
    parser.add_argument(
        "--reader-preset",
        dest="reader_presets",
        nargs="+",
        choices=sorted(load_models()),
        default=[],
        help="Registry models to run every stage before action (doc 14 §5), on "
        "their registry pin and the cell's reasoning effort, crossed with the "
        "model axis. A reader equal to the actor is the ordinary cell.",
    )
    parser.add_argument(
        "--hosts",
        nargs="+",
        default=None,
        metavar="PROVIDER",
        help="OpenRouter hosts to sweep: each pins "
        '{"order":[PROVIDER],"allow_fallbacks":false} per cell, crossed with '
        "models and effort, overriding the registry pin (default: the pin). "
        "Cannot combine with -M provider=....",
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
        nargs="+",
        default=None,
        choices=get_args(ReasoningEffort),
        help="Reasoning effort cells to sweep (recorded in config_hash); "
        "defaults to the preset's.",
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
        default=None,
        choices=sorted(ISOLATION_CHOICES),
        help="Isolation conditions to sweep (default both; 'both' includes the "
        "negative control).",
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
        default=None,
        choices=list(DEFENSES),
        help="Prompt-level defense cells to sweep (spotlight = datamarking, "
        "doc 10 §4).",
    )
    parser.add_argument(
        "--relay-stages",
        nargs="+",
        type=int,
        default=None,
        help="relay_stages cells to sweep (extra relay stages, 0..3).",
    )
    parser.add_argument(
        "--handoff-modes",
        nargs="+",
        default=None,
        choices=list(HANDOFF_MODES),
        help="handoff_mode cells to sweep.",
    )
    parser.add_argument(
        "--gate",
        nargs="+",
        default=None,
        choices=["off", "on"],
        help="gate cells to sweep.",
    )
    parser.add_argument(
        "--swap-stage",
        nargs="+",
        default=None,
        metavar="STAGE",
        help="Message-swap cells to sweep (doc 14 §4): analysis, relay_i or "
        "action. Needs --isolation control.",
    )
    parser.add_argument(
        "--arms",
        choices=sorted(ARMS),
        default=None,
        help="Named comparison replacing the isolation/handoff/gate/relay/defense/"
        "swap axes (those flags then exit 2). defense: isolation off; on; typed; "
        "typed + spotlight, each without and with the gate (8 arms per scope). "
        "halflife: relay depths 0-3, isolated, free_text, gate off. doc 11 §4. "
        "core: ungated at both isolations; gated, not isolated; typed + gated, "
        "isolated. swap: the message swap at action, ungated. doc 14.",
    )
    parser.add_argument(
        "--verification-tools",
        nargs="+",
        default=["off"],
        choices=["off", "on"],
        help="verification_tools cells to sweep (W2 only).",
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
        "--split",
        choices=["dev", "confirm"],
        default="dev",
        help="Samples whose scenario is in this split. confirm, and any held-out "
        "model, needs a freeze that matches the working tree (doc 14 §10). There "
        "is no way to run both: the default never touches a confirm scenario.",
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
    axes = (
        "isolation",
        "handoff_modes",
        "gate",
        "relay_stages",
        "defense",
        "swap_stage",
    )
    if args.arms:
        clash = [a for a in axes if getattr(args, a) is not None]
        if clash:
            flags = ", ".join("--" + a.replace("_", "-") for a in clash)
            parser.exit(2, f"--arms conflicts with {flags}\n")
        typed = any(c.handoff_mode == "typed" for c in ARMS[args.arms])
        if typed and "facts" in args.identity:
            parser.exit(
                2,
                f"--arms {args.arms} includes typed hand-off arms, which cannot run "
                "with --identity facts (doc 11 §8 ruling 2); use off or guard\n",
            )
        args.conditions = ARMS[args.arms]
    else:
        if args.swap_stage and args.isolation != "control":
            parser.exit(2, "--swap-stage needs --isolation control (doc 14 §4)\n")
        args.conditions = [
            Condition(iso, hand, defense, relay, gate == "on", swap)
            for iso in ISOLATION_CHOICES[args.isolation or "both"]
            for hand in args.handoff_modes or ["free_text"]
            for defense in args.defense or ["none"]
            for relay in args.relay_stages or [0]
            for gate in args.gate or ["off"]
            for swap in args.swap_stage or [None]
        ]
    args.cells = []
    registry = load_models()
    for name in (*args.model_presets, *args.reader_presets):
        if registry[name].todo:
            parser.exit(2, f"configs/models.json entry {name} has TODO fields\n")
    readers: list[ModelEntry | None] = [registry[n] for n in args.reader_presets]
    for name in args.model_presets or [None]:
        entry = registry[name] if name else None
        base = list(args.model_args)
        model = args.model or (entry.model if entry else None)
        model = model or os.environ.get("INSPECT_EVAL_MODEL")
        if args.hosts and any(key == "provider" for key, _ in base):
            parser.exit(2, "--hosts conflicts with -M provider=...\n")
        providers: list[Any] = [
            {"order": [host], "allow_fallbacks": False} for host in args.hosts or []
        ] or [entry.provider if entry else None]
        for provider in providers:
            model_args = list(base)
            if provider is not None and not any(k == "provider" for k, _ in base):
                model_args = [("provider", provider), *model_args]
            for effort in args.reasoning_effort or [
                entry.reasoning_effort if entry else None
            ]:
                for reader in readers or [None]:
                    cell = Cell(model, tuple(model_args), effort, entry, reader)
                    if cell in args.cells:
                        print(
                            f"warning: duplicate cell dropped: {cell}", file=sys.stderr
                        )
                    else:
                        args.cells.append(cell)
    return args


def split_refusals(
    split: str,
    cells: Sequence[Cell],
    manifest: str,
    log_dir: str,
    root: Path = ROOT,
) -> list[str]:
    """Why this sweep may not run under doc 14 §10; [] when it may."""
    held_out = {e.model for e in load_models().values() if e.held_out}
    uses_held_out = any(
        m in held_out
        for c in cells
        for m in (c.model, c.reader.model if c.reader else None)
    )
    if split == "dev":
        problems = []
        if uses_held_out:
            problems.append("a held-out model runs on --split confirm only")
        if (Path(log_dir) / FREEZE_COPY).exists():
            problems.append(f"{log_dir} holds a confirm run; use another --log-dir")
        return problems
    problems = list(freeze.freeze_problems())
    if root != freeze.ROOT:
        problems.append(f"this script is in {root}, the frozen tree is {freeze.ROOT}")
    resolved = Path(manifest).resolve()
    frozen = {p.resolve() for p in (root / "corpus").glob("manifest_w*.jsonl")}
    frozen |= set((root / "corpus" / "canonical").resolve().rglob("*.jsonl"))
    if resolved not in frozen:
        problems.append(f"manifest {manifest} is not in the frozen corpus")
    logs = Path(log_dir)
    if not (logs / FREEZE_COPY).exists() and any(logs.rglob("*.eval")):
        problems.append(f"{log_dir} already holds a run that is not a confirm run")
    return problems


def main(argv: list[str] | None = None) -> int:
    # Inspect loads .env only when the eval starts; tasks bind their model
    # (and need its API key) before that.
    load_dotenv(find_dotenv(usecwd=True))
    args = parse_args(argv)
    if not args.cells[0].model:
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

    cells = [
        (
            cell,
            task_fn(
                scope=scope,
                isolated=cond.isolated,
                manifest=manifest,
                epochs=args.epochs,
                benign_only=args.benign_only,
                controls=args.controls,
                model=cell.model,
                model_args=dict(cell.model_args) or None,
                reasoning_effort=cell.reasoning_effort,  # type: ignore[arg-type]
                identity_mode=identity,
                defense=cond.defense,
                relay_stages=cond.relay_stages,
                handoff_mode=cond.handoff_mode,
                gate=cond.gate,
                verification_tools=verify == "on",
                reader_model=cell.reader.model if cell.reader else None,
                reader_model_args=(
                    {"provider": cell.reader.provider} if cell.reader else None
                ),
                swap_stage=cond.swap_stage,
            ),
        )
        for cell in args.cells
        for scope in args.scopes
        for cond in args.conditions
        for identity in args.identity
        for verify in args.verification_tools
    ]
    tasks = [task for _, task in cells]
    for task in tasks:
        if any("split" not in (s.metadata or {}) for s in task.dataset):
            print(f"{manifest}: a row has no split (doc 14 §2)", file=sys.stderr)
            return 2
        task.dataset = task.dataset.filter(
            lambda s: (s.metadata or {})["split"] == args.split
        )

    print(
        f"sweeping {len(tasks)} cell(s) of {args.workflow} on "
        f"{len({c.model for c, _ in cells})} model(s) "
        f"(epochs={args.epochs}, benign_only={args.benign_only}, "
        f"controls={args.controls}, split={args.split})"
    )
    twin_only = args.benign_only or args.controls
    total = 0
    usd_total = 0.0
    fallback = False
    for cell, task in cells:
        meta = task.metadata or {}
        samples = len(task.dataset)
        if args.limit is not None:
            samples = min(samples, args.limit)
        runs = samples * (task.epochs or 1)
        total += runs
        line = " est=n/a"
        if cell.entry:
            stats = token_stats([args.log_dir], {"config_hash": meta["config_hash"]})
            entry = cell.entry
            # The diagonal (reader = actor) is the ordinary cell, priced as one.
            split = cell.reader if meta["reader_model"] else None
            if split:
                entry = max(entry, split, key=lambda e: float(e.price_out))
            swap = meta["swap_stage"] is not None
            usd = estimate_usd(
                runs, twin_only, meta["relay_stages"], entry, stats, swap
            )
            fallback |= stats is None
            assert usd is not None  # TODO-priced entries are refused in parse_args
            usd_total += usd
            line = f" est=${usd:,.2f}"
            if split:
                line += " (upper bound: dearer of reader/actor)"
        print(
            f"  model={cell.model} effort={cell.reasoning_effort} "
            f"provider={dict(cell.model_args).get('provider')} "
            f"scope={meta['scope']:<10} "
            f"isolated={meta['isolated']!s:<5} "
            f"identity={meta['identity_mode']:<5} "
            f"defense={meta['defense']:<9} "
            f"relay={meta['relay_stages']} "
            f"handoff={meta['handoff_mode']} "
            f"gate={meta['gate']} "
            f"verify={meta['verification_tools']} "
            f"reader={meta['reader_model']} "
            f"swap={meta['swap_stage']} "
            f"runs={runs:<6} "
            f"config_hash={meta['config_hash']}{line}"
        )
    unit = "twin runs" if twin_only else "pairs"
    print(f"total: {total} {unit}")
    if any(c.entry for c, _ in cells):
        basis = (
            "default pilot tokens (no logs found in --log-dir)"
            if fallback
            else "tokens measured from existing logs"
        )
        print(
            f"estimated cost: ${usd_total:,.2f} (+~20% retries; list prices; {basis})"
        )
    drafts = draft_documents()
    if drafts:
        print(f"governing documents still in draft: {', '.join(drafts)}")
    refusals = split_refusals(args.split, args.cells, manifest, args.log_dir)
    print(f"freeze: {'; '.join(refusals) or 'ok'}")
    if args.dry_run:
        return 0
    if refusals:
        print(f"refusing (doc 14 §10): {'; '.join(refusals)}", file=sys.stderr)
        return 3
    paid = not all(
        str(m).startswith("mockllm/")
        for c, _ in cells
        for m in (c.model, *([c.reader.model] if c.reader else []))
    )
    if drafts and paid and not args.allow_draft_docs:
        print(
            "refusing a paid run while governing documents are drafts: sign and "
            "push them first (doc 10 §8), or pass --allow-draft-docs for a pilot",
            file=sys.stderr,
        )
        return 3

    if args.split == "confirm":
        copy = Path(args.log_dir) / FREEZE_COPY
        copy.parent.mkdir(parents=True, exist_ok=True)
        entry = freeze.load_freeze()[-1]
        copy.write_text(json.dumps(entry._asdict(), indent=2) + "\n", "utf-8")

    success, logs = eval_set(
        tasks,
        log_dir=args.log_dir,
        model=args.cells[0].model if len({c.model for c in args.cells}) == 1 else None,
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
