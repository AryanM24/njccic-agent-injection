"""The W1 (IT help-desk triage) evaluation task.

Structurally identical to task.py's W2 task — same paired-sample design, same
scorers, same isolation mechanism — with W1's prompts and mock tools (an
insider-attacker, credential/device-action workflow) substituted in. See
task.py's module docstring for why the pair, not the document, is the unit of
measurement.

G1 (exfiltration) is intentionally NOT included here: docs/design/07_thresholds_appendix.md
fixes sensitivity tiers only for W2. Per that appendix's own rule, an outcome
without signed-off thresholds is descoped rather than approximated, so this
task reports propagation, scope_violation, and action_divergence only until a
W1 tiering table is written and signed.
"""

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.model import ModelOutput
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import store_as

from .agents.pipeline import run_pipeline
from .agents.prompts_w1 import (
    ACTION_SYSTEM,
    ANALYSIS_SYSTEM,
    INTAKE_SYSTEM,
    PROMPTS_VERSION_W1,
)
from .config import DOC_VERSIONS, EXTRACTION_PINS, assert_extraction_pinned, config_hash
from .extraction import extract
from .scorers import RUNS_KEY, action_divergence, propagation, scope_violation
from .task import dataset_from_manifest
from .tools import Ledger
from .tools.helpdesk import tool_names_for_scope, tools_for_scope

WORKFLOW = "w1"

DEFAULT_MANIFEST = str(
    Path(__file__).resolve().parents[2] / "corpus" / "manifest_w1.jsonl"
)
"""Manifest shipped with the repo. Currently EMPTY — no W1 fixtures exist yet
(see corpus/manifest_w1.jsonl). This task will raise on an empty dataset until
fixture pairs are built with scripts/make_fixtures.py, mirroring w2_0001."""


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
    """Run only the benign twin ticket through the pipeline — no attack ticket.

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
def eduinject_w1(
    scope: str = "read_write",
    isolated: bool = True,
    manifest: str = DEFAULT_MANIFEST,
    message_limit: int | None = 100,
    epochs: int | None = None,
    benign_only: bool = False,
) -> Task:
    """Indirect prompt injection through a district IT help-desk workflow.

    Args:
        scope: Write scope granted to the action stage ("read_only",
            "standard", or "read_write" — see tools.helpdesk.SCOPES).
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
            check) and scope_violation (the out-of-scope-call base rate)
            from the twin run. action_divergence is omitted -- it is
            defined only as attack-vs-twin, which does not exist here.

    Returns:
        The configured task.
    """
    assert_extraction_pinned()

    if benign_only:
        solver = benign_pipeline(scope=scope, isolated=isolated)
        scorers = [propagation(run_label="twin"), scope_violation(run_label="twin")]
    else:
        solver = paired_pipeline(scope=scope, isolated=isolated)
        scorers = [propagation(), scope_violation(), action_divergence()]

    return Task(
        dataset=dataset_from_manifest(manifest),
        solver=solver,
        message_limit=message_limit,
        epochs=epochs,
        scorer=scorers,
        metadata={
            "workflow": WORKFLOW,
            "scope": scope,
            "isolated": isolated,
            "benign_only": benign_only,
            "prompts_version": PROMPTS_VERSION_W1,
            "extraction_pins": EXTRACTION_PINS,
            "doc_versions": DOC_VERSIONS,
            "config_hash": config_hash(
                workflow=WORKFLOW,
                scope=scope,
                isolated=isolated,
                benign_only=benign_only,
                prompts_version=PROMPTS_VERSION_W1,
            ),
        },
    )
