"""The W2 (hiring) evaluation task.

One sample is one *pair*: the attack document and its benign twin are both run
through the full pipeline, under identical settings, within the same sample.
That is deliberate. Several outcomes are defined only by the difference between
the two runs, and a difference can only be scored where both sides are
available at scoring time — so the pair is the unit of measurement, not the
document.
"""

import json
from pathlib import Path
from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ModelOutput
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import store_as

from .agents.pipeline import run_pipeline
from .agents.prompts import ACTION_SYSTEM, ANALYSIS_SYSTEM, INTAKE_SYSTEM, PROMPTS_VERSION
from .config import (
    DOC_VERSIONS,
    EXTRACTION_PINS,
    assert_extraction_pinned,
    config_hash,
)
from .extraction import extract
from .scorers import (
    RUNS_KEY,
    action_divergence,
    exfiltration,
    propagation,
    scope_violation,
)
from .tools import Ledger, tool_names_for_scope, tools_for_scope

WORKFLOW = "w2"

DEFAULT_MANIFEST = str(
    Path(__file__).resolve().parents[2] / "corpus" / "manifest_w2.jsonl"
)
"""Manifest shipped with the repo. Resolved from the source tree, so it assumes
an editable install (`pip install -e .`); pass `manifest=` explicitly otherwise."""


def dataset_from_manifest(manifest: str | Path) -> MemoryDataset:
    """Build the paired dataset from a manifest file.

    Artifact paths in the manifest are repo-relative; they are resolved against
    the manifest's grandparent directory and stored absolute, so the task does
    not depend on the working directory the eval is launched from.

    Args:
        manifest: Path to a `manifest_*.jsonl` file.

    Returns:
        One sample per manifest line.
    """
    manifest = Path(manifest).resolve()
    root = manifest.parent.parent

    samples: list[Sample] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        samples.append(
            Sample(
                id=entry["artifact_id"],
                input=entry["operator_request"],
                metadata={
                    "artifact_id": entry["artifact_id"],
                    "artifact_path": str(root / entry["artifact_path"]),
                    "twin_path": str(root / entry["twin_path"]),
                    "payload_marker": entry["payload_marker"],
                    "authorized_recipients": entry["authorized_recipients"],
                    # Optional: absent for older manifest lines, in which case
                    # every non-authorized address is treated as unattested.
                    "applicant_addresses": entry.get("applicant_addresses", []),
                    "other_candidate_terms": entry.get(
                        "other_candidate_terms", []
                    ),
                },
            )
        )
    return MemoryDataset(samples, name=manifest.stem)


@solver
def paired_pipeline(scope: str, isolated: bool) -> Solver:
    """Run the attack document and its twin through the pipeline.

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

        runs: dict[str, dict[str, Any]] = {}
        for label, document_text in documents.items():
            # Separate ledger instances keep the two runs' tool activity from
            # merging — they share a sample, and therefore a store.
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
def eduinject_w2(
    scope: str = "read_write",
    isolated: bool = True,
    manifest: str = DEFAULT_MANIFEST,
    message_limit: int | None = 100,
) -> Task:
    """Indirect prompt injection through a district hiring workflow.

    Args:
        scope: Write scope granted to the action stage ("read_only",
            "standard", or "read_write").
        isolated: When True, no stage after intake sees the source document.
            Pass False for the negative control.
        manifest: Path to the corpus manifest.
        message_limit: Per-sample message ceiling. A model that never calls
            submit would otherwise keep the action stage's react loop running
            indefinitely; the sample covers six stage runs, so the default is
            well clear of any honest trajectory.

    Returns:
        The configured task.
    """
    # C2: the extraction stack decides which concealment channels are visible
    # at all, so drift fails the run here rather than silently changing what
    # was measured.
    assert_extraction_pinned()

    return Task(
        dataset=dataset_from_manifest(manifest),
        solver=paired_pipeline(scope=scope, isolated=isolated),
        message_limit=message_limit,
        scorer=[
            propagation(),
            exfiltration(),
            scope_violation(),
            action_divergence(),
        ],
        metadata={
            "workflow": WORKFLOW,
            "scope": scope,
            "isolated": isolated,
            "prompts_version": PROMPTS_VERSION,
            "extraction_pins": EXTRACTION_PINS,
            "doc_versions": DOC_VERSIONS,
            "config_hash": config_hash(
                workflow=WORKFLOW,
                scope=scope,
                isolated=isolated,
                prompts_version=PROMPTS_VERSION,
            ),
        },
    )
