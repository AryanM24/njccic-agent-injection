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
from inspect_ai.tool import Tool
from inspect_ai.util import store_as

from .agents import prompts
from .agents.handoff_schemas import HANDOFF_VERSION, trusted_fields
from .agents.pipeline import (
    HANDOFF_MODES,
    ToolNamesForScope,
    ToolsForScope,
    run_pipeline,
)
from .agents.prompts_handoff import HANDOFF_PROMPTS_VERSION
from .agents.prompts_relay import RELAY_PROMPTS_VERSION, RELAY_SYSTEM
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
from .monitor import MONITOR_RULES_VERSION
from .scorers import (
    RUNS_KEY,
    W2_SPEC,
    ExfilSpec,
    action_divergence,
    argument_provenance,
    authorization,
    control_check,
    exfiltration,
    harm,
    misdirection,
    paired_utility,
    premise_adoption,
    propagation,
    rank_corruption,
    scope_violation,
    suppression,
)
from .scorers.deterministic import SWAP_KEY
from .scorers.outcomes import stage_names
from .scorers.provenance import PROVENANCE_VERSION
from .tools import ats
from .tools.guard import Guard, guard_from_metadata
from .tools.ledger import Ledger

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
    "payload_set",
    "correspondent_addresses",
    "third_party_terms",
    "protected_terms",
    "entitled_actions",
    "tripwire_addresses",
    "expect",
    "correct",
    "data_subject_addresses",
    "candidate_terms",
    "on_file_addresses",
    "component_markers",
    "premise_marker",
    "premise_subject",
    "verification_tool",
    "split",
    "requester_id",
    "sender_address",
    "posting_id",
    "candidate_roster",
    "true_ranking",
    "attacker_candidate",
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
    send_tools: tuple[str, ...]
    """The subset of `write_tools` that sends mail, for `correct_outcome`."""
    manifest: str
    controls_manifest: str
    task_facts: Callable[[Mapping[str, Any]], str]
    verified_recipients: Callable[[Mapping[str, Any]], list[str]]
    """Correspondents the directory verifies: the guard's approved recipients
    beside the district mailbox, and what the facts block calls approved."""
    readable_records: Callable[[Mapping[str, Any]], frozenset[str]] | None = None
    """Student records the guard lets the agent read (W3), else unguarded."""
    escalation_tools: tuple[str, ...] = ()
    """Tools that escalate to staff (W3), for `correct_outcome`; empty where a
    send to an authorized recipient is the escalation."""
    verification_tools: tuple[Callable[..., Tool], ...] = ()
    """Lookups `verification_tools=True` adds (W2); empty where the workflow
    already has them, which makes the parameter a `ValueError`."""
    verification_surface: str | None = None
    """`tool_surface` when the verification lookups are granted."""


RELAY_MAX = 3
HandoffMode = Literal["free_text", "typed"]

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


def register(wf: Workflow) -> Workflow:
    WORKFLOWS[wf.code] = wf
    return wf


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
        send_tools=("send_email",),
        manifest=DEFAULT_MANIFEST,
        controls_manifest=DEFAULT_CONTROLS_MANIFEST,
        task_facts=facts_w2,
        verified_recipients=verified_w2,
        verification_tools=ats.VERIFICATION_TOOLS,
        verification_surface=ats.TOOL_SURFACE_VERIFY,
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


def tools_with_verification(
    workflow: Workflow, enabled: bool
) -> tuple[ToolsForScope, ToolNamesForScope]:
    """The workflow's scope functions, with its verification lookups appended at
    every scope when `enabled` (C3); unchanged otherwise."""
    if not enabled:
        return workflow.tools_for_scope, workflow.tool_names_for_scope
    extra = workflow.verification_tools

    def tools(scope: str, instance: str | None, guard: Guard | None) -> list[Tool]:
        added = [f(instance=instance, guard=guard) for f in extra]
        return [*workflow.tools_for_scope(scope, instance, guard), *added]

    def names(scope: str) -> tuple[str, ...]:
        added = tuple(f.__name__ for f in extra)
        return (*workflow.tool_names_for_scope(scope), *added)

    return tools, names


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


SWAP_CELLS = {
    "attack": ("attack", "attack"),
    "twin": ("twin", "twin"),
    "at": ("attack", "twin"),
    "ta": ("twin", "attack"),
}
"""Swap run label -> (document at and after the swap, hand-off source). Doc 14
§4's `aa` and `tt` are the sample's ordinary `attack` and `twin` runs."""


@solver
def paired_pipeline(
    workflow: str,
    scope: str,
    isolated: bool,
    benign_only: bool = False,
    identity_mode: str = "off",
    defense: str = "none",
    relay_stages: int = 0,
    handoff_mode: HandoffMode = "free_text",
    gate: bool = False,
    verification_tools: bool = False,
    reader_model: str | None = None,
    reader_model_args: dict[str, Any] | None = None,
    reader_effort: ReasoningEffort | None = None,
    swap_stage: str | None = None,
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
        relay_stages: Extra relay stages between analysis and action (0..3).
        handoff_mode: "free_text" or "typed" stage hand-off.
        gate: Enable the monitor gate on the action stage's calls.
        verification_tools: Grant the workflow's verification lookups.
        reader_model: Model for every stage before action (default: the task's).
        reader_model_args: Provider args bound with the reader.
        reader_effort: Reasoning effort bound with the reader.
        swap_stage: First stage of the message swap (doc 14 §4), or None. The
            stages before it run once per document, the rest once per
            `SWAP_CELLS` entry on those hand-offs.

    Returns:
        A solver that records each run under `metadata["runs"]` (and a swap's
        cross runs under `metadata["swap_runs"]`).
    """
    spec = WORKFLOWS[workflow]
    tools_for_scope, tool_names_for_scope = tools_with_verification(
        spec, verification_tools
    )
    labels = ("twin",) if benign_only else ("attack", "twin")
    reader = (
        bind_model(reader_model, reader_model_args, reader_effort)
        if reader_model
        else None
    )
    spotlight = defense == "spotlight"
    clause = prompts.SPOTLIGHT_CLAUSE if spotlight else ""
    # The clause describes the document, so only stages that receive it get it.
    later = "" if isolated else clause

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        meta = state.metadata
        typed = handoff_mode == "typed"
        # Typed hand-off: the trusted record replaces the facts block (ruling 2).
        facts = spec.task_facts(meta) if identity_mode != "off" and not typed else None
        trusted = trusted_fields(workflow, meta).model_dump_json() if typed else None
        guard = guard_for(spec, meta) if identity_mode == "guard" else None
        paths = {"attack": meta["artifact_path"], "twin": meta["twin_path"]}

        async def run_one(document: str, instance: str, **splice: Any) -> Any:
            return await run_pipeline(
                datamark(document) if spotlight else document,
                state.input_text,
                scope=scope,
                isolated=isolated,
                instance=instance,
                tools_for_scope=tools_for_scope,
                tool_names_for_scope=tool_names_for_scope,
                intake_system=spec.intake_system + clause,
                analysis_system=spec.analysis_system + later,
                action_system=spec.action_system + later,
                task_facts=facts,
                guard=guard,
                relay_stages=relay_stages,
                relay_system=RELAY_SYSTEM[workflow] + later,
                handoff_mode=handoff_mode,
                trusted_block=trusted,
                gate=gate,
                gate_meta={
                    k: v for k, v in meta.items() if k not in (RUNS_KEY, SWAP_KEY)
                },
                workflow=workflow,
                identity_mode=identity_mode,
                reader=reader,
                **splice,
            )

        # Separate ledger instances keep the runs' tool activity from merging:
        # they share a sample, and therefore a store.
        def recorded(document: str, instance: str, result: Any) -> dict[str, Any]:
            return {
                "document_text": document,
                "pipeline": result,
                "ledger": store_as(Ledger, instance=instance).model_dump(),
            }

        # Written per run, so a run that hits a limit later still leaves the
        # finished ones on the record.
        runs: dict[str, dict[str, Any]] = {}
        meta[RUNS_KEY] = runs
        if swap_stage is None:
            for label in labels:
                document = extract(paths[label])
                result = await run_one(document, label)
                runs[label] = recorded(document, label, result)
        else:
            cross: dict[str, dict[str, Any]] = {}
            meta[SWAP_KEY] = cross
            docs = {d: extract(paths[d]) for d in labels}
            prefixes = {
                m: await run_one(docs[m], "prefix", stop_before=swap_stage)
                for m in labels
            }
            for label, (d, m) in SWAP_CELLS.items():
                # Any cell an attack-derived wire reached is scored on (and
                # gated by) the attack document.
                scored = docs["twin" if label == "twin" else "attack"]
                both = (prefixes[m], *prefixes.values())
                failed = [p for p in both if p["status"] != "ok"]
                if failed:
                    # One unparsed hand-off leaves no block: nothing is spent
                    # on the rest, and no cell shows another's stages.
                    result = {**failed[0], "stages": prefixes[m]["stages"]}
                    ledger = store_as(Ledger, instance=label)
                    ledger.scope = scope
                    ledger.granted_tools = list(tool_names_for_scope(scope))
                else:
                    result = await run_one(
                        docs[d], label, resume=prefixes[m], gate_document=scored
                    )
                (runs if label in labels else cross)[label] = {
                    **recorded(scored, label, result),
                    "action_document": d,
                }

        state.output = ModelOutput.from_content(
            model=str(state.model), content=runs[labels[0]]["pipeline"]["final"]
        )
        return state

    return solve


def scorers_for(
    workflow: Workflow,
    benign_only: bool,
    relay_stages: int = 0,
    identity_mode: str = "off",
    handoff_mode: str = "free_text",
) -> list[Scorer]:
    """The scorer set for a cell. Benign-only cells score the twin alone and
    drop the attack-vs-twin outcomes, which do not exist there."""
    spec, changing = workflow.spec, workflow.state_changing
    label = "twin" if benign_only else "attack"
    out: list[Scorer] = [
        propagation(run_label=label, relay_stages=relay_stages),
        exfiltration(run_label=label, spec=spec),
    ]
    if changing:
        out.append(authorization(changing, run_label=label))
    out.append(scope_violation(run_label=label))
    out.append(misdirection(run_label=label, spec=spec))
    if benign_only:
        out.append(
            control_check(
                spec=spec,
                state_changing=changing,
                write_tools=workflow.write_tools,
                send_tools=workflow.send_tools,
                escalation_tools=workflow.escalation_tools,
            )
        )
    else:
        out += [
            action_divergence(),
            suppression(),
            argument_provenance(workflow.code, identity_mode, handoff_mode),
            paired_utility(
                spec=spec,
                state_changing=changing,
                write_tools=workflow.write_tools,
                send_tools=workflow.send_tools,
                escalation_tools=workflow.escalation_tools,
            ),
        ]
        if workflow.code == "w2":
            out.append(rank_corruption())
        sinks = set(workflow.write_tools) - set(workflow.escalation_tools)
        out.append(premise_adoption(sink_tools=sorted(sinks)))
    out.append(harm(spec=spec, state_changing=changing, run_label=label))
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
    relay_stages: int = 0,
    handoff_mode: HandoffMode = "free_text",
    gate: bool = False,
    verification_tools: bool = False,
    reader_model: str | None = None,
    reader_model_args: dict[str, Any] | None = None,
    swap_stage: str | None = None,
) -> Task:
    """Build one cell of a workflow's experiment (see the `eduinject_*` tasks)."""
    if identity_mode not in IDENTITY_MODES:
        raise ValueError(f"identity_mode must be one of {IDENTITY_MODES}")
    if defense not in DEFENSES:
        raise ValueError(f"defense must be one of {DEFENSES}")
    if (
        not isinstance(relay_stages, int)
        or isinstance(relay_stages, bool)
        or not 0 <= relay_stages <= RELAY_MAX
    ):
        raise ValueError(f"relay_stages must be an int in 0..{RELAY_MAX}")
    if handoff_mode not in HANDOFF_MODES:
        raise ValueError(f"handoff_mode must be one of {HANDOFF_MODES}")
    if not isinstance(gate, bool):
        raise ValueError("gate must be a bool")  # noqa: TRY004
    if not isinstance(verification_tools, bool):
        raise ValueError("verification_tools must be a bool")  # noqa: TRY004
    if handoff_mode == "typed" and identity_mode == "facts":
        raise ValueError(
            'handoff_mode="typed" cannot combine with identity_mode="facts": '
            "typed hand-off already carries the verified facts"
        )
    if verification_tools and not workflow.verification_tools:
        raise ValueError(
            f"verification_tools: {workflow.code} has no verification tools to add"
        )
    manifest, benign_only = resolve_run_mode(
        manifest, workflow.manifest, workflow.controls_manifest, controls, benign_only
    )
    if reader_model_args and reader_model is None:
        raise ValueError("reader_model_args need a reader_model to bind to")
    # Reader = actor is the ordinary cell, so it must hash and pool as one.
    if (reader_model, reader_model_args or None) == (model, model_args or None):
        reader_model = None
    if reader_model is None:
        reader_model_args = None
    if swap_stage is not None:
        if swap_stage not in (later := stage_names(relay_stages)[1:]):
            raise ValueError(f"swap_stage must be None or one of {later}")
        if isolated:
            raise ValueError(
                "swap_stage needs isolated=False: the swapped stage must see the "
                "document"
            )
        if benign_only:
            raise ValueError(
                "swap_stage needs attack/twin pairs: not benign_only or controls"
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
        "tool_surface": (
            workflow.verification_surface
            if verification_tools
            else workflow.tool_surface
        ),
        "model": model,
        "model_args": model_args,
        "reasoning_effort": reasoning_effort,
        "identity_mode": identity_mode,
        "task_facts_version": TASK_FACTS_VERSION,
        "defense": defense,
        "defense_version": DEFENSE_VERSION,
        "relay_stages": relay_stages,
        "relay_prompts_version": RELAY_PROMPTS_VERSION,
        "handoff_mode": handoff_mode,
        "handoff_version": HANDOFF_VERSION,
        "handoff_prompts_version": HANDOFF_PROMPTS_VERSION,
        "gate": gate,
        "monitor_rules_version": MONITOR_RULES_VERSION,
        "provenance_version": PROVENANCE_VERSION,
        "verification_tools": verification_tools,
        "reader_model": reader_model,
        "reader_model_args": reader_model_args,
        "swap_stage": swap_stage,
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
            relay_stages=relay_stages,
            handoff_mode=handoff_mode,
            gate=gate,
            verification_tools=verification_tools,
            reader_model=reader_model,
            reader_model_args=reader_model_args,
            reader_effort=reasoning_effort,
            swap_stage=swap_stage,
        ),
        message_limit=message_limit,
        epochs=epochs,
        model=bind_model(model, model_args, reasoning_effort),
        scorer=scorers_for(
            workflow, benign_only, relay_stages, identity_mode, handoff_mode
        ),
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
    relay_stages: int = 0,
    handoff_mode: HandoffMode = "free_text",
    gate: bool = False,
    verification_tools: bool = False,
    reader_model: str | None = None,
    reader_model_args: dict[str, Any] | None = None,
    swap_stage: str | None = None,
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
        relay_stages: Extra relay stages between analysis and action (0..3).
        handoff_mode: "free_text" or "typed" stage hand-off.
        gate: Monitor gate on the action stage's calls.
        verification_tools: Grant the workflow's verification lookups (W2).
        reader_model: Model for intake, analysis and relays (doc 14 §5), at the
            same `reasoning_effort`; the action stage stays on `model`. None, or
            the same model with the same args, is the ordinary cell.
        reader_model_args: Provider args bound with the reader (host pin).
        swap_stage: First stage of the message swap (doc 14 §4): `analysis`,
            `relay_i` or `action`. Needs `isolated=False`. `message_limit` is
            per conversation, so the two extra runs do not consume it.

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
        relay_stages=relay_stages,
        handoff_mode=handoff_mode,
        gate=gate,
        verification_tools=verification_tools,
        reader_model=reader_model,
        reader_model_args=reader_model_args,
        swap_stage=swap_stage,
    )
