"""The W3 (parent correspondence) evaluation task.

Structurally identical to task.py's W2 task — same paired-sample design, same
scorers, same isolation mechanism — with W3's prompts and mock tools (an
external-attacker, correspondence workflow) substituted in. See
task.py's module docstring for why the pair, not the document, is the unit of
measurement.

G1 (exfiltration) is intentionally NOT included here: docs/design/07_thresholds_appendix.md
fixes sensitivity tiers only for W2. Per that appendix's own rule, an outcome
without signed-off thresholds is descoped rather than approximated, so this
task reports propagation, scope_violation, and action_divergence only until a
W3 tiering table is written and signed.
"""

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset
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
from .scorers import RUNS_KEY, action_divergence, propagation, scope_violation
from .task import dataset_from_manifest
from .tools import Ledger
from .tools.parentmail import tool_names_for_scope, tools_for_scope

WORKFLOW = "w3"

DEFAULT_MANIFEST = str(
    Path(__file__).resolve().parents[2] / "corpus" / "manifest_w3.jsonl"
)
"""Manifest shipped with the repo. Currently EMPTY — no W3 fixtures exist yet
(see corpus/manifest_w3.jsonl). This task will raise on an empty dataset until
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


@task
def eduinject_w3(
    scope: str = "read_write",
    isolated: bool = True,
    manifest: str = DEFAULT_MANIFEST,
    message_limit: int | None = 100,
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

    Returns:
        The configured task.
    """
    assert_extraction_pinned()

    return Task(
        dataset=dataset_from_manifest(manifest),
        solver=paired_pipeline(scope=scope, isolated=isolated),
        message_limit=message_limit,
        scorer=[propagation(), scope_violation(), action_divergence()],
        metadata={
            "workflow": WORKFLOW,
            "scope": scope,
            "isolated": isolated,
            "prompts_version": PROMPTS_VERSION_W3,
            "extraction_pins": EXTRACTION_PINS,
            "doc_versions": DOC_VERSIONS,
            "config_hash": config_hash(
                workflow=WORKFLOW,
                scope=scope,
                isolated=isolated,
                prompts_version=PROMPTS_VERSION_W3,
            ),
        },
    )
