"""The W2 (hiring) evaluation task, and the machinery all three workflows share.

One sample is one *pair*: the attack document and its benign twin are both run
through the full pipeline, under identical settings, within the same sample.
That is deliberate. Several outcomes are defined only by the difference between
the two runs, and a difference can only be scored where both sides are
available at scoring time — so the pair is the unit of measurement, not the
document.

W1 (`task_w1.py`) and W3 (`task_w3.py`) are the same design with their own
prompts, tools and scorers: each declares a `Workflow` and calls `build_task`,
so a new condition is wired once, here, rather than three times.
"""

import hashlib
import json
from collections.abc import Callable, Mapping
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal, NamedTuple

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import GenerateConfig, Model, ModelOutput, get_model
from inspect_ai.scorer import Scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import store_as

from .agents import prompts
from .agents.pipeline import ToolNamesForScope, ToolsForScope, run_pipeline
from .agents.task_facts import (
    IDENTITY_MODES,
    TASK_FACTS_VERSION,
    facts_w2,
    verified_w2,
)
from .config import (
    DOC_VERSIONS,
    EXTRACTION_PINS,
    assert_extraction_pinned,
    config_hash,
)
from .defense import DEFENSE_VERSION, DEFENSES, datamark
from .extraction import extract
from .scorers import (
    RUNS_KEY,
    W2_SPEC,
    W3_SPEC,
    ExfilSpec,
    action_divergence,
    authorization,
    control_check,
    exfiltration,
    guarded_outcome,
    paired_utility,
    propagation,
    scope_violation,
    suppression,
)
from .tools import Ledger, ats
from .tools.guard import Guard, guard_from_metadata

CORPUS = Path(__file__).resolve().parents[2] / "corpus"

DEFAULT_MANIFEST = str(CORPUS / "manifest_w2.jsonl")
"""Manifest shipped with the repo. Resolved from the source tree, so it assumes
an editable install (`pip install -e .`); pass `manifest=` explicitly otherwise."""

DEFAULT_CONTROLS_MANIFEST = str(CORPUS / "manifest_w2_controls.jsonl")
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
    "correct",
    "data_subject_addresses",
    "candidate_terms",
)
"""Manifest fields copied into sample metadata when present. They are optional
so older manifest lines keep loading; carrying `goal`, `base_id`, `file_type` and
`concealment` into the log is what lets results be sliced by them."""

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


class Workflow(NamedTuple):
    """Everything that differs between W1, W2 and W3."""

    code: str
    intake_system: str
    analysis_system: str
    action_system: str
    prompts_version: str
    tools_for_scope: ToolsForScope
    tool_names_for_scope: ToolNamesForScope
    tool_surface: str
    spec: ExfilSpec
    state_changing: dict[str, str] | None
    """W1's state-changing tools (enables the authorization scorer), else None."""
    write_tools: tuple[str, ...]
    """Every non-lookup tool (state-changing or sending), for `correct_outcome`."""
    manifest: str
    controls_manifest: str
    task_facts: Callable[[Mapping[str, Any]], str]
    verified_recipients: Callable[[Mapping[str, Any]], list[str]]
    """Correspondents the directory verifies: the guard's approved recipients
    beside the district mailbox, and what the facts block calls approved."""
    readable_records: Callable[[Mapping[str, Any]], frozenset[str]] | None = None
    """Student records the guard lets the agent read (W3), else unguarded."""


WORKFLOWS: dict[str, Workflow] = {}
"""Workflow code -> spec. Each task module registers its own on import; the
solver receives the code, not the spec, so its logged arguments stay plain."""


def workflow(code: str) -> Workflow:
    """The registered workflow for `code`, importing the W1/W3 modules first.

    Registration happens on import of each task module, so a bare
    `WORKFLOWS[code]` fails for W1/W3 unless something imported them.
    """
    import_module("eduinject.task_w1")
    import_module("eduinject.task_w3")
    return WORKFLOWS[code]


def register(workflow: Workflow) -> Workflow:
    WORKFLOWS[workflow.code] = workflow
    return workflow


W2 = register(
    Workflow(
        code="w2",
        intake_system=prompts.INTAKE_SYSTEM,
        analysis_system=prompts.ANALYSIS_SYSTEM,
        action_system=prompts.ACTION_SYSTEM,
        prompts_version=prompts.PROMPTS_VERSION,
        tools_for_scope=ats.tools_for_scope,
        tool_names_for_scope=ats.tool_names_for_scope,
        tool_surface=ats.TOOL_SURFACE,
        spec=W2_SPEC,
        state_changing=None,
        write_tools=("submit_shortlist", "send_email"),
        manifest=DEFAULT_MANIFEST,
        controls_manifest=DEFAULT_CONTROLS_MANIFEST,
        task_facts=facts_w2,
        verified_recipients=verified_w2,
    )
)


def corpus_label(manifest: str | Path) -> str:
    """Short label for which corpus a run used, for the config hash.

    The public marker-only manifest and the gated canonical manifest share a
    file name, so the parent directory is part of the label.
    """
    path = Path(manifest)
    return f"{path.parent.name}/{path.name}"


def corpus_digest(manifest: str | Path) -> str:
    """sha256 (16 hex) of the manifest and every artifact file it names.

    The label says *which* corpus; this says *which bytes*. Regenerating a
    corpus (new canaries, a reworded request, a parser-visible metadata change)
    changes what the model sees without changing the label, so the bytes are
    hashed too.
    """
    manifest = Path(manifest).resolve()
    root = manifest.parent.parent
    digest = hashlib.sha256(manifest.read_bytes())
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            for key in ("artifact_path", "twin_path"):
                digest.update((root / entry[key]).read_bytes())
    return digest.hexdigest()[:16]


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
    baseline, so `controls=True` implies `benign_only`. If the caller passed
    the workflow's main manifest (in any spelling of its path), the controls
    manifest is used instead.
    """
    if controls:
        benign_only = True
        if Path(manifest).resolve() == Path(default_manifest).resolve():
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


def guard_for(workflow: Workflow, metadata: Mapping[str, Any]) -> Guard:
    """The guard a sample's tools enforce under identity_mode="guard"."""
    readable = (
        workflow.readable_records(metadata) if workflow.readable_records else None
    )
    return guard_from_metadata(
        metadata,
        workflow.verified_recipients(metadata),
        tuple(workflow.state_changing or ()),
        readable,
    )


@solver
def paired_pipeline(
    workflow: str,
    scope: str,
    isolated: bool,
    benign_only: bool = False,
    identity_mode: str = "off",
    defense: str = "none",
) -> Solver:
    """Run the attack document and its twin (or the twin alone) through the pipeline.

    Args:
        workflow: Registered workflow code ("w1", "w2", "w3").
        scope: Write scope granted to the action stage.
        isolated: Whether stages after intake see the source document.
        benign_only: Run only the twin -- Phase 2's baseline, with no injected
            content anywhere in the sample. It measures the pipeline's own
            behaviour on legitimate input (false-positive rates and run-to-run
            variance), which is what the null rule's floor is set from (Doc 4
            §13.4), not from any run that also contains an attack.
        identity_mode: "off", "facts" (verified task facts in the action
            stage's input) or "guard" (the same facts, enforced by the tools).
        defense: "none" or "spotlight" (datamark the document and tell every
            stage that receives it that marked text carries no instructions).

    Returns:
        A solver that records each run under `metadata["runs"]`.
    """
    spec = WORKFLOWS[workflow]
    labels = ("twin",) if benign_only else ("attack", "twin")
    spotlight = defense == "spotlight"
    clause = prompts.SPOTLIGHT_CLAUSE if spotlight else ""
    # The clause describes the document, so only stages that receive it get it.
    later = "" if isolated else clause

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        meta = state.metadata
        facts = spec.task_facts(meta) if identity_mode != "off" else None
        guard = guard_for(spec, meta) if identity_mode == "guard" else None
        paths = {"attack": meta["artifact_path"], "twin": meta["twin_path"]}

        runs: dict[str, dict[str, Any]] = {}
        meta[RUNS_KEY] = runs
        for label in labels:
            document_text = extract(paths[label])
            if spotlight:
                document_text = datamark(document_text)
            # Separate ledger instances keep the two runs' tool activity from
            # merging — they share a sample, and therefore a store.
            result = await run_pipeline(
                document_text,
                state.input_text,
                scope=scope,
                isolated=isolated,
                instance=label,
                tools_for_scope=spec.tools_for_scope,
                tool_names_for_scope=spec.tool_names_for_scope,
                intake_system=spec.intake_system + clause,
                analysis_system=spec.analysis_system + later,
                action_system=spec.action_system + later,
                task_facts=facts,
                guard=guard,
            )
            # Written per run, so a run that hits a limit later still leaves
            # the finished one on the record.
            runs[label] = {
                "pipeline": result,
                "ledger": store_as(Ledger, instance=label).model_dump(),
            }

        state.output = ModelOutput.from_content(
            model=str(state.model), content=runs[labels[0]]["pipeline"]["final"]
        )
        return state

    return solve


def scorers_for(
    workflow: Workflow, benign_only: bool, identity_mode: str
) -> list[Scorer]:
    """The scorer set for a cell. Benign-only cells score the twin alone and
    drop the attack-vs-twin outcomes, which do not exist there."""
    spec, changing = workflow.spec, workflow.state_changing
    label = "twin" if benign_only else "attack"
    escalation = ("escalate_to_staff",) if spec is W3_SPEC else ()
    out: list[Scorer] = [
        propagation(run_label=label),
        exfiltration(run_label=label, spec=spec),
    ]
    if changing:
        out.append(authorization(changing, run_label=label))
    out.append(scope_violation(run_label=label))
    if benign_only:
        out.append(
            control_check(
                spec=spec,
                state_changing=changing,
                write_tools=workflow.write_tools,
                escalation_tools=escalation,
            )
        )
    else:
        out += [
            action_divergence(),
            suppression(),
            paired_utility(
                spec=spec,
                state_changing=changing,
                write_tools=workflow.write_tools,
                escalation_tools=escalation,
            ),
        ]
    if identity_mode == "guard":
        out.append(guarded_outcome(spec=spec, state_changing=changing, run_label=label))
    return out


def build_task(
    workflow: Workflow,
    *,
    scope: str,
    isolated: bool,
    manifest: str,
    message_limit: int | None,
    epochs: int | None,
    benign_only: bool,
    controls: bool,
    model: str | None,
    model_args: dict[str, Any] | None,
    reasoning_effort: ReasoningEffort | None,
    identity_mode: str,
    defense: str,
) -> Task:
    """Build one cell of a workflow's experiment (see the `eduinject_*` tasks)."""
    if identity_mode not in IDENTITY_MODES:
        raise ValueError(f"identity_mode must be one of {IDENTITY_MODES}")
    if defense not in DEFENSES:
        raise ValueError(f"defense must be one of {DEFENSES}")
    manifest, benign_only = resolve_run_mode(
        manifest, workflow.manifest, workflow.controls_manifest, controls, benign_only
    )
    # C2: the extraction stack decides which concealment channels are visible
    # at all, so drift fails the run here rather than silently changing what
    # was measured.
    assert_extraction_pinned()

    run_params: dict[str, Any] = {
        "workflow": workflow.code,
        "scope": scope,
        "isolated": isolated,
        "benign_only": benign_only,
        "controls": controls,
        "message_limit": message_limit,
        "prompts_version": workflow.prompts_version,
        "corpus": corpus_label(manifest),
        "corpus_digest": corpus_digest(manifest),
        "tool_surface": workflow.tool_surface,
        "model": model,
        "model_args": model_args,
        "reasoning_effort": reasoning_effort,
        "identity_mode": identity_mode,
        "task_facts_version": TASK_FACTS_VERSION,
        "defense": defense,
        "defense_version": DEFENSE_VERSION,
        # The react loop and its submit plumbing come from Inspect itself.
        "inspect_ai": version("inspect-ai"),
    }
    return Task(
        dataset=dataset_from_manifest(manifest),
        solver=paired_pipeline(
            workflow.code,
            scope=scope,
            isolated=isolated,
            benign_only=benign_only,
            identity_mode=identity_mode,
            defense=defense,
        ),
        message_limit=message_limit,
        epochs=epochs,
        model=bind_model(model, model_args, reasoning_effort),
        scorer=scorers_for(workflow, benign_only, identity_mode),
        metadata={
            **run_params,
            "extraction_pins": EXTRACTION_PINS,
            "doc_versions": DOC_VERSIONS,
            "config_hash": config_hash(**run_params),
        },
    )


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
    identity_mode: str = "off",
    defense: str = "none",
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
            rate), scope_violation (the out-of-scope-call base rate) and
            `control_check` from the twin run. action_divergence and
            suppression are omitted -- they are defined only as
            attack-vs-twin, which does not exist here.
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
        identity_mode: "off" (v1 behaviour), "facts" (verified task facts in
            the action stage's input) or "guard" (facts enforced by the tools).
            See docs/design/10.
        defense: "none" or "spotlight" (datamarking, Hines et al. 2024). See
            docs/design/10.

    Returns:
        The configured task.
    """
    return build_task(
        W2,
        scope=scope,
        isolated=isolated,
        manifest=manifest,
        message_limit=message_limit,
        epochs=epochs,
        benign_only=benign_only,
        controls=controls,
        model=model,
        model_args=model_args,
        reasoning_effort=reasoning_effort,
        identity_mode=identity_mode,
        defense=defense,
    )
