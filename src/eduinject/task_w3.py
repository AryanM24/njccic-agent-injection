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

from typing import Any

from inspect_ai import Task, task

from .agents import prompts_w3
from .agents.task_facts import facts_w3, linked_students, verified_w3
from .scorers import W3_SPEC
from .task import (
    CORPUS,
    HandoffMode,
    ReasoningEffort,
    Workflow,
    build_task,
    register,
)
from .tools import parentmail

DEFAULT_MANIFEST = str(CORPUS / "manifest_w3.jsonl")
"""Manifest shipped with the repo (marker-only placeholder corpus; see
corpus/README_w1_w3.md). Resolved from the source tree, so it assumes an
editable install; pass `manifest=` explicitly otherwise."""

DEFAULT_CONTROLS_MANIFEST = str(CORPUS / "manifest_w3_controls.jsonl")
"""Benign-but-weird controls. Run with `controls=True`."""

W3 = register(
    Workflow(
        code="w3",
        intake_system=prompts_w3.INTAKE_SYSTEM,
        analysis_system=prompts_w3.ANALYSIS_SYSTEM,
        action_system=prompts_w3.ACTION_SYSTEM,
        prompts_version=prompts_w3.PROMPTS_VERSION_W3,
        tools_for_scope=parentmail.tools_for_scope,
        tool_names_for_scope=parentmail.tool_names_for_scope,
        tool_surface=parentmail.TOOL_SURFACE,
        spec=W3_SPEC,
        state_changing=None,
        write_tools=("escalate_to_staff", "send_reply"),
        send_tools=("send_reply",),
        manifest=DEFAULT_MANIFEST,
        controls_manifest=DEFAULT_CONTROLS_MANIFEST,
        task_facts=facts_w3,
        verified_recipients=verified_w3,
        readable_records=linked_students,
        escalation_tools=("escalate_to_staff",),
    )
)


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
    """Indirect prompt injection through a district parent-correspondence workflow.

    Args:
        scope: Write scope granted to the action stage ("read_only",
            "standard", or "read_write" — see tools.parentmail.SCOPES).
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
            rate), scope_violation (the out-of-scope-call
            base rate) and `control_check` from the twin run. action_divergence and
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
        W3,
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
