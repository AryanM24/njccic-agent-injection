"""The W3 (parent correspondence) evaluation task.

Structurally identical to task.py's W2 task — same paired-sample design, same
scorers, same isolation mechanism — with W3's prompts and mock tools (an
external-attacker, correspondence workflow) substituted in. See
task.py's module docstring for why the pair, not the document, is the unit of
measurement.

Scorers beyond W2's set, and their status:

- `exfiltration` (G1) uses W3's tier table and recipient policy from
  docs/design/08_w1_w3_g1_tiers_addendum.md (signed v1.0, 2026-10-11).
  W3 G1 figures are reportable as lower bounds (07 covers W2). In W3, an "unauthorized approval" shows up as protected student data
  leaving the district, so G1 is the scorer for it; there is no separate
  authorization oracle as in W1.
- `suppression` (G5) records raw signals only; its thresholds are unset.
"""

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.model import ModelOutput
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import store_as

from .agents.pipeline import run_pipeline
from .agents.prompts_w3 import (
    ACTION_SYSTEM,
    ANALYSIS_SYSTEM,
    INTAKE_SYSTEM,
    PROMPTS_VERSION_W3,
)
from .config import DOC_VERSIONS, EXTRACTION_PINS, assert_extraction_pinned, config_hash
from .extraction import extract
from .scorers import (
    RUNS_KEY,
    W3_SPEC,
    action_divergence,
    control_check,
    exfiltration,
    propagation,
    scope_violation,
    suppression,
)
from .task import corpus_label, dataset_from_manifest, resolve_run_mode
from .tools import Ledger
from .tools.parentmail import TOOL_SURFACE, tool_names_for_scope, tools_for_scope

WORKFLOW = "w3"

DEFAULT_MANIFEST = str(
    Path(__file__).resolve().parents[2] / "corpus" / "manifest_w3.jsonl"
)
"""Manifest shipped with the repo (marker-only placeholder corpus; see
corpus/README_w1_w3.md). Resolved from the source tree, so it assumes an
editable install; pass `manifest=` explicitly otherwise."""

DEFAULT_CONTROLS_MANIFEST = str(
    Path(__file__).resolve().parents[2] / "corpus" / "manifest_w3_controls.jsonl"
)
"""Benign-but-weird controls. Run with `controls=True`."""


@solver
def paired_pipeline(scope: str, isolated: bool) -> Solver:
    """Run the attack ticket and its twin through the pipeline.

    Args:
        scope: Write scope granted to the action stage.
        isolated: Whether stages after intake see the source document.

    Returns:
        A solver that records both runs under `metadata["runs"]`.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # "attack"/"twin" naming matches task.py and task_w1.py; here the
        # artifact is inbound parent correspondence rather than a ticket.
        documents = {
            "attack": extract(state.metadata["artifact_path"]),
            "twin": extract(state.metadata["twin_path"]),
        }

        runs = {}
        for label, document_text in documents.items():
            result = await run_pipeline(
                document_text,
                state.input_text,
                scope=scope,
                isolated=isolated,
                instance=label,
                tools_for_scope=tools_for_scope,
                tool_names_for_scope=tool_names_for_scope,
                intake_system=INTAKE_SYSTEM,
                analysis_system=ANALYSIS_SYSTEM,
                action_system=ACTION_SYSTEM,
            )
            runs[label] = {
                "pipeline": result,
                "ledger": store_as(Ledger, instance=label).model_dump(),
            }

        state.metadata[RUNS_KEY] = runs
        state.output = ModelOutput.from_content(
            model=str(state.model), content=runs["attack"]["pipeline"]["final"]
        )
        return state

    return solve


@solver
def benign_pipeline(scope: str, isolated: bool) -> Solver:
    """Run only the benign twin correspondence through the pipeline -- no attack.

    Phase 2's benign-only baseline. See task.py's `benign_pipeline` docstring
    for why this exists separately from `paired_pipeline`.

    Args:
        scope: Write scope granted to the action stage.
        isolated: Whether stages after intake see the source document.

    Returns:
        A solver that records the single twin run under `metadata["runs"]["twin"]`.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        document_text = extract(state.metadata["twin_path"])
        result = await run_pipeline(
            document_text,
            state.input_text,
            scope=scope,
            isolated=isolated,
            instance="twin",
            tools_for_scope=tools_for_scope,
            tool_names_for_scope=tool_names_for_scope,
            intake_system=INTAKE_SYSTEM,
            analysis_system=ANALYSIS_SYSTEM,
            action_system=ACTION_SYSTEM,
        )
        state.metadata[RUNS_KEY] = {
            "twin": {
                "pipeline": result,
                "ledger": store_as(Ledger, instance="twin").model_dump(),
            }
        }
        state.output = ModelOutput.from_content(
            model=str(state.model), content=result["final"]
        )
        return state

    return solve


@task
def eduinject_w3(
    scope: str = "read_write",
    isolated: bool = True,
    manifest: str = DEFAULT_MANIFEST,
    message_limit: int | None = 100,
    epochs: int | None = None,
    benign_only: bool = False,
    controls: bool = False,
    model: str | None = None,
) -> Task:
    """Indirect prompt injection through a district parent-correspondence workflow.

    Args:
        scope: Write scope granted to the action stage ("read_only",
            "standard", or "read_write" — see tools.parentmail.SCOPES).
        isolated: When True, no stage after intake sees the source document.
            Pass False for the negative control.
        manifest: Path to the corpus manifest.
        message_limit: Per-sample message ceiling (see task.py's W2 docstring
            for the rationale behind the default).
        epochs: Repetitions per sample (Inspect's Task.epochs). None runs
            each sample once. Doc 4 SS13.4 sets a floor of ten runs per
            condition before any effect is interpretable against
            run-to-run variance -- pass epochs=10+ explicitly for any run
            whose results will be reported.
        benign_only: When True, run only the twin (Phase 2's baseline) --
            no attack artifact runs at all. Scores propagation (a floor
            check), exfiltration (the G1 false-positive rate),
            scope_violation (the out-of-scope-call base rate) and
            control_check from the twin run. action_divergence and
            suppression are omitted -- they are defined only as
            attack-vs-twin, which does not exist here.
        controls: When True, run the benign-but-weird controls manifest
            instead (implies `benign_only`). Use `standard` or `read_write`
            scope; at `read_only` there is nothing to complete.
        model: Model to bind to the task. It is folded into `config_hash`,
            so two runs with the same hash ran the same model (doc 3 AS-2).
            None leaves the model to `eval()` and records it as unbound.

    Returns:
        The configured task.
    """
    assert_extraction_pinned()
    manifest, benign_only = resolve_run_mode(
        manifest, DEFAULT_MANIFEST, DEFAULT_CONTROLS_MANIFEST, controls, benign_only
    )

    if benign_only:
        solver = benign_pipeline(scope=scope, isolated=isolated)
        scorers = [
            propagation(run_label="twin"),
            exfiltration(run_label="twin", spec=W3_SPEC),
            scope_violation(run_label="twin"),
            control_check(spec=W3_SPEC),
        ]
    else:
        solver = paired_pipeline(scope=scope, isolated=isolated)
        scorers = [
            propagation(),
            exfiltration(spec=W3_SPEC),
            scope_violation(),
            action_divergence(),
            suppression(),
        ]

    return Task(
        dataset=dataset_from_manifest(manifest),
        solver=solver,
        message_limit=message_limit,
        epochs=epochs,
        model=model,
        scorer=scorers,
        metadata={
            "workflow": WORKFLOW,
            "scope": scope,
            "isolated": isolated,
            "benign_only": benign_only,
            "controls": controls,
            "model": model,
            "corpus": corpus_label(manifest),
            "tool_surface": TOOL_SURFACE,
            "prompts_version": PROMPTS_VERSION_W3,
            "extraction_pins": EXTRACTION_PINS,
            "doc_versions": DOC_VERSIONS,
            "config_hash": config_hash(
                workflow=WORKFLOW,
                scope=scope,
                isolated=isolated,
                benign_only=benign_only,
                prompts_version=PROMPTS_VERSION_W3,
                corpus=corpus_label(manifest),
                tool_surface=TOOL_SURFACE,
                model=model,
            ),
        },
    )
