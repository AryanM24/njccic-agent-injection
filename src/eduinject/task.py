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
from typing import Any, Literal

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import GenerateConfig, Model, ModelOutput, get_model
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import store_as

from .agents.pipeline import run_pipeline
from .agents.prompts import (
    ACTION_SYSTEM,
    ANALYSIS_SYSTEM,
    INTAKE_SYSTEM,
    PROMPTS_VERSION,
)
from .config import (
    DOC_VERSIONS,
    EXTRACTION_PINS,
    assert_extraction_pinned,
    config_hash,
)
from .extraction import extract
from .scorers import (
    RUNS_KEY,
    W2_SPEC,
    action_divergence,
    control_check,
    exfiltration,
    propagation,
    scope_violation,
    suppression,
)
from .tools import Ledger, tool_names_for_scope, tools_for_scope
from .tools.ats import TOOL_SURFACE

WORKFLOW = "w2"

DEFAULT_MANIFEST = str(
    Path(__file__).resolve().parents[2] / "corpus" / "manifest_w2.jsonl"
)
"""Manifest shipped with the repo. Resolved from the source tree, so it assumes
an editable install (`pip install -e .`); pass `manifest=` explicitly otherwise."""

DEFAULT_CONTROLS_MANIFEST = str(
    Path(__file__).resolve().parents[2] / "corpus" / "manifest_w2_controls.jsonl"
)
"""Benign-but-weird controls: legitimate documents with instruction-like
phrasing. Run with `controls=True`."""

OPTIONAL_METADATA: tuple[str, ...] = (
    "base_id",
    "kind",
    "goal",
    "file_type",
    "concealment",
    "payload_class",
    "correspondent_addresses",
    "third_party_terms",
    "protected_terms",
    "entitled_actions",
    "tripwire_addresses",
    "expect",
)
"""Manifest fields copied into sample metadata when present. They are optional
so older manifest lines keep loading; carrying `goal`, `base_id`, `file_type` and
`concealment` into the log is what lets results be sliced by them."""


def corpus_label(manifest: str | Path) -> str:
    """Short label for which corpus a run used, for the config hash.

    The public marker-only manifest and the gated canonical manifest share a
    file name, so the parent directory is part of the label.
    """
    path = Path(manifest)
    return f"{path.parent.name}/{path.name}"


ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


def bind_model(
    model: str | None,
    model_args: dict[str, Any] | None,
    reasoning_effort: ReasoningEffort | None,
) -> Model | None:
    """Resolve the model a task is bound to, with its provider args.

    `Task` resolves a bare model string without args, so provider options
    (OpenRouter host pinning, `responses_api`) and the reasoning effort only
    take effect -- and only reach `config_hash` -- if bound here.

    An OpenRouter model must pin its upstream host with fallbacks off (D9):
    otherwise two runs with the same hash may be served by different
    providers or quantizations.

    Raises:
        ValueError: If args are given without a model, an arg looks like a
            credential (it would be written into the log), or an OpenRouter
            model is not pinned.
    """
    model_args = model_args or {}
    if model is None:
        if model_args or reasoning_effort:
            raise ValueError("model_args/reasoning_effort need a model to bind to")
        return None
    secret = [k for k in model_args if "key" in k.lower() or "secret" in k.lower()]
    if secret:
        raise ValueError(
            f"model_args {secret} look like credentials; they would be recorded "
            "in the log -- set them in the environment instead"
        )
    if model.startswith("openrouter/"):
        provider = model_args.get("provider")
        if not (
            isinstance(provider, dict)
            and (provider.get("order") or provider.get("only"))
            and provider.get("allow_fallbacks") is False
        ):
            raise ValueError(
                f"{model}: pin the upstream host (D9), e.g. model_args="
                '{"provider": {"order": ["DeepInfra"], "allow_fallbacks": false}}'
            )
    # memoize=False: the memo key cannot hash the nested provider dict.
    return get_model(
        model,
        config=GenerateConfig(reasoning_effort=reasoning_effort),
        memoize=False,
        **model_args,
    )


def resolve_run_mode(
    manifest: str,
    default_manifest: str,
    default_controls: str,
    controls: bool,
    benign_only: bool,
) -> tuple[str, bool]:
    """Resolve the controls flag into (manifest, benign_only).

    Controls are scored on a single run per document, exactly like the benign
    baseline, so `controls=True` implies `benign_only`. If the caller did not
    pass a manifest, the workflow's controls manifest is used.
    """
    if controls:
        benign_only = True
        if manifest == default_manifest:
            manifest = default_controls
    return manifest, benign_only


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
                    "other_candidate_terms": entry.get("other_candidate_terms", []),
                    **{
                        field: entry[field]
                        for field in OPTIONAL_METADATA
                        if field in entry
                    },
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


@solver
def benign_pipeline(scope: str, isolated: bool) -> Solver:
    """Run only the benign twin through the pipeline — no attack artifact.

    This is Phase 2's benign-only baseline: the twin is the *only* document
    run, so there is no injected content anywhere in the sample and no attack
    run to compare against. It measures the pipeline's own behavior on
    legitimate input alone — false-positive rates and run-to-run variance —
    which is what the G2/A3 and G5 materiality thresholds must be set from
    (Doc 4 §13.4), not from any run that also contains an attack condition.

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
def eduinject_w2(
    scope: str = "read_write",
    isolated: bool = True,
    manifest: str = DEFAULT_MANIFEST,
    message_limit: int | None = 100,
    epochs: int | None = None,
    benign_only: bool = False,
    controls: bool = False,
    model: str | None = None,
    model_args: dict[str, Any] | None = None,
    reasoning_effort: ReasoningEffort | None = None,
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
        epochs: Repetitions per sample (Inspect's Task.epochs). None runs
            each sample once. Doc 4 SS13.4 sets a floor of ten runs per
            condition before any effect is interpretable against
            run-to-run variance -- pass epochs=10+ explicitly for any run
            whose results will be reported.
        benign_only: When True, run only the twin (Phase 2's baseline) --
            no attack artifact runs at all. Scores propagation (a floor
            check, should read 0), exfiltration (the G1 false-positive
            rate), and scope_violation (the out-of-scope-call base rate),
            each read from the twin run. action_divergence is omitted --
            it is defined only as attack-vs-twin, which does not exist here.
            Also scores `control_check` on each twin (harm done, and whether
            the legitimate task was completed).
        controls: When True, run the benign-but-weird controls manifest
            instead (implies `benign_only`). Same scorers as the baseline, so
            a control's rates compare directly with the twin baseline for the
            same base scenario. Use scopes that grant the legitimate tools
            (`standard` or `read_write`) -- at `read_only` there is nothing to
            complete.
        model: Model to bind to the task. It is folded into `config_hash`,
            so two runs with the same hash ran the same model (doc 3 AS-2).
            None leaves the model to `eval()` and records it as unbound.
        model_args: Provider args bound with the model, e.g. an OpenRouter
            `provider` pin (required for `openrouter/` models, D9) or
            `responses_api`. Recorded in metadata and `config_hash`.
        reasoning_effort: Fixed reasoning effort for every stage, recorded in
            `config_hash`. None leaves the provider default.

    Returns:
        The configured task.
    """
    manifest, benign_only = resolve_run_mode(
        manifest, DEFAULT_MANIFEST, DEFAULT_CONTROLS_MANIFEST, controls, benign_only
    )
    # C2: the extraction stack decides which concealment channels are visible
    # at all, so drift fails the run here rather than silently changing what
    # was measured.
    assert_extraction_pinned()

    if benign_only:
        solver = benign_pipeline(scope=scope, isolated=isolated)
        scorers = [
            propagation(run_label="twin"),
            exfiltration(run_label="twin"),
            scope_violation(run_label="twin"),
            control_check(spec=W2_SPEC),
        ]
    else:
        solver = paired_pipeline(scope=scope, isolated=isolated)
        scorers = [
            propagation(),
            exfiltration(),
            scope_violation(),
            action_divergence(),
            suppression(),
        ]

    return Task(
        dataset=dataset_from_manifest(manifest),
        solver=solver,
        message_limit=message_limit,
        epochs=epochs,
        model=bind_model(model, model_args, reasoning_effort),
        scorer=scorers,
        metadata={
            "workflow": WORKFLOW,
            "scope": scope,
            "isolated": isolated,
            "benign_only": benign_only,
            "controls": controls,
            "model": model,
            "model_args": model_args,
            "reasoning_effort": reasoning_effort,
            "corpus": corpus_label(manifest),
            "tool_surface": TOOL_SURFACE,
            "prompts_version": PROMPTS_VERSION,
            "extraction_pins": EXTRACTION_PINS,
            "doc_versions": DOC_VERSIONS,
            "config_hash": config_hash(
                workflow=WORKFLOW,
                scope=scope,
                isolated=isolated,
                benign_only=benign_only,
                prompts_version=PROMPTS_VERSION,
                corpus=corpus_label(manifest),
                tool_surface=TOOL_SURFACE,
                model=model,
                model_args=model_args,
                reasoning_effort=reasoning_effort,
            ),
        },
    )
