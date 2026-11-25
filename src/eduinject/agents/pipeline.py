"""The staged pipeline: intake -> analysis -> relays (0..k) -> action.

Stage isolation is structural. The stages are composed with Inspect's `run()`,
which copies its input and returns a fresh `AgentState`; each stage's input is
then built by hand from the previous stage's output alone. `handoff()` would
hand the downstream agent the entire upstream conversation and `as_tool()`
would let a model decide the routing — either would let a later stage re-read
the injected source document, which is the confound the whole measurement is
built to avoid. With `isolated=True` the document text is simply not present in
any input after stage 1: the isolation is a missing wire, not an instruction.
"""

from collections.abc import Callable, Mapping
from typing import Any, TypedDict

from inspect_ai.agent import (
    Agent,
    AgentPrompt,
    AgentState,
    AgentSubmit,
    agent,
    agent_with,
    react,
    run,
)
from inspect_ai.model import (
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelUsage,
    ResponseSchema,
    get_model,
)
from inspect_ai.tool import Tool
from inspect_ai.util import json_schema, store_as
from pydantic import BaseModel

from ..scorers.outcomes import action_text
from ..tools.gate import GateContext, gate_context, gated_tools, note_message
from ..tools.guard import Guard
from ..tools.ledger import Ledger
from .handoff_schemas import AnalysisHandoff, IntakeHandoff, parse_handoff
from .prompts_handoff import TYPED_ACTION_CLAUSE, TYPED_OUTPUT_CLAUSE

ToolsForScope = Callable[[str, str | None, Guard | None], list[Tool]]
ToolNamesForScope = Callable[[str], tuple[str, ...]]


@agent
def single_shot(
    name: str,
    system_prompt: str,
    response_schema: ResponseSchema | None = None,
    model: Model | None = None,
) -> Agent:
    """Build a one-generation, no-tools agent.

    Args:
        name: Display name for the stage (used in the transcript).
        system_prompt: System prompt for the stage.
        response_schema: Structured output requested from the provider (typed
            hand-off). Providers without support ignore it; the prompt clause
            still states the shape.
        model: Model that generates (default: the task's model).

    Returns:
        An agent that generates exactly once.
    """
    config = GenerateConfig(response_schema=response_schema)

    async def execute(state: AgentState) -> AgentState:
        """Generate a single response to the stage input and return."""
        state.messages.insert(0, ChatMessageSystem(content=system_prompt))
        output = await (model or get_model()).generate(state.messages, config=config)
        state.output = output
        state.messages.append(output.message)
        return state

    return agent_with(execute, name=name)


def action_agent(
    scope: str,
    instance: str,
    tools_for_scope: ToolsForScope,
    action_system: str,
    guard: Guard | None = None,
    usage: list[ModelUsage] | None = None,
    gate: GateContext | None = None,
) -> Agent:
    """Build the tool-using action stage.

    Args:
        scope: Write scope granted to this run (a key of the workflow's
            `SCOPES` mapping, e.g. `tools.ats.SCOPES`, `tools.helpdesk.SCOPES`,
            `tools.parentmail.SCOPES`).
        instance: Ledger instance for this run.
        tools_for_scope: The workflow's tool-instantiation function.
        action_system: The workflow's action-stage system prompt.
        guard: Authorization guard the tools enforce, or None.
        usage: Receives the token usage of every generation of the loop.
        gate: The policy gate's context; when set, every tool is gated.

    Returns:
        A react agent with the scope's tools.
    """

    async def generate(state: AgentState, tools: list[Tool]) -> AgentState:
        """react()'s default generation step, recording each turn's usage."""
        output = await get_model().generate(state.messages, tools)
        if usage is not None and output.usage is not None:
            usage.append(output.usage)
        if gate is not None:
            note_message(gate, output.message)
        state.output = output
        state.messages.append(output.message)
        return state

    tools = tools_for_scope(scope, instance, guard)
    return react(
        name="action",
        description="Carries out the assessed request using district systems.",
        # `AgentPrompt` with the other slots cleared keeps the system message
        # exactly equal to action_system. react() would otherwise append its
        # own assistant and submit prompts, putting un-versioned prompt text
        # into an independent variable (C4).
        prompt=AgentPrompt(instructions=action_system, assistant_prompt=None),
        tools=tools if gate is None else gated_tools(tools, gate, instance),
        model=generate,
        # Keep the submit call in the transcript: `stage3_messages` is the
        # measurement record of what the agent did, and the default drops it.
        submit=AgentSubmit(keep_in_messages=True),
    )


class Usage(TypedDict):
    """Token usage of one stage's generation."""

    input_tokens: int
    output_tokens: int


class Stage(TypedDict):
    """One stage's record: its name, the input built for it, and its output."""

    name: str
    input: str
    output: str
    usage: Usage | None


def _usage(state: Any) -> Usage | None:
    # getattr: the isolation tests' recorder returns a bare namespace.
    usage = getattr(state.output, "usage", None)
    return _total([usage]) if usage is not None else None


def _total(usages: list[ModelUsage]) -> Usage | None:
    if not usages:
        return None
    return {
        "input_tokens": sum(u.input_tokens for u in usages),
        "output_tokens": sum(u.output_tokens for u in usages),
    }


class _HandoffParseError(Exception):
    """A typed stage's output failed validation; carries the stage name."""


HANDOFF_MODES = ("free_text", "typed")

HANDOFF_SCHEMAS: dict[str, type[BaseModel]] = {
    "intake": IntakeHandoff,
    "analysis": AnalysisHandoff,
}
"""Typed hand-off output schema by stage kind; relays use "analysis"."""


async def run_pipeline(
    document_text: str,
    operator_request: str,
    *,
    scope: str,
    isolated: bool,
    instance: str,
    tools_for_scope: ToolsForScope,
    tool_names_for_scope: ToolNamesForScope,
    intake_system: str,
    analysis_system: str,
    action_system: str,
    task_facts: str | None = None,
    guard: Guard | None = None,
    relay_stages: int = 0,
    relay_system: str | None = None,
    handoff_mode: str = "free_text",
    trusted_block: str | None = None,
    gate: bool = False,
    gate_meta: Mapping[str, Any] | None = None,
    workflow: str | None = None,
    identity_mode: str = "off",
    reader: Model | None = None,
) -> dict[str, Any]:
    """Run one document through intake -> analysis -> relays -> action.

    This function is workflow-agnostic by design: it is shared across W1, W2,
    and W3 rather than forked per workflow, so a change to stage isolation or
    to how the ledger is populated only has to be made once. Each workflow
    supplies its own prompts and tools; nothing workflow-specific is imported
    here.

    Args:
        document_text: Extracted text of the submitted document.
        operator_request: What the district staff member asked for.
        scope: Write scope granted to the action stage.
        isolated: When True, no stage after intake sees the source document.
            When False (the negative control), every stage sees it.
        instance: Ledger instance for this run.
        tools_for_scope: The workflow's tool-instantiation function (e.g.
            `tools.ats.tools_for_scope`).
        tool_names_for_scope: The workflow's tool-name-resolution function,
            used only to record which tools this run's scope granted — kept
            separate from `tools_for_scope` because the scorer needs names,
            not live `Tool` objects.
        intake_system: The workflow's intake-stage system prompt.
        analysis_system: The workflow's analysis-stage system prompt.
        action_system: The workflow's action-stage system prompt.
        task_facts: Verified facts for the action stage (identity_mode
            "facts"/"guard"), built from the manifest and directories by the
            caller. They never pass through the document path, so a document
            cannot forge or overwrite them.
        guard: Authorization guard the action stage's tools enforce.
        relay_stages: Relay stages between analysis and action (doc 11 §4.1).
            Each sees only the previous stage's output and the operator
            request (plus the document when not isolated).
        relay_system: The workflow's relay system prompt; required when
            `relay_stages` > 0.
        handoff_mode: "free_text", or "typed" (doc 11 §4.2): every pre-action
            stage must emit JSON matching its schema, parsed once; the action
            stage gets `trusted_block` and the validated assessment.
        trusted_block: The trusted case record as JSON (`trusted_fields`),
            built from the manifest and directories by the caller; required
            when typed. It replaces `task_facts`.
        gate: Put the policy gate (doc 11 §4.3) in front of the action stage's
            tools, outside the guard.
        gate_meta: Sample metadata the gate's rules read; required with `gate`.
        workflow: Workflow code ("w1", "w2", "w3"); required with `gate`.
        identity_mode: The cell's identity_mode, which decides the trusted
            text the gate's provenance check counts.
        reader: Model that runs every stage before action (doc 14 §5); the
            action stage always runs on the task's model. None: the task's
            model runs every stage.

    Returns:
        `stages` (one `Stage` per stage, in order: `intake`, `analysis`,
        `relay_1` ... `relay_k`, `action`), the action stage's final completion
        (`final`), its messages (`stage3_messages`) and `status` (`ok`, or
        `handoff_parse_error` with the failing stage in `failed_stage`; later
        stages are then not run).
    """
    if relay_stages and relay_system is None:
        raise ValueError("relay_stages > 0 needs a relay_system prompt")
    if handoff_mode not in HANDOFF_MODES:
        raise ValueError(f"handoff_mode must be one of {HANDOFF_MODES}")
    typed = handoff_mode == "typed"
    if typed and (trusted_block is None or task_facts is not None):
        raise ValueError("typed hand-off needs trusted_block and no task_facts")
    if gate and (gate_meta is None or workflow is None):
        raise ValueError("gate needs gate_meta and workflow")
    ledger = store_as(Ledger, instance=instance)
    ledger.scope = scope
    ledger.granted_tools = list(tool_names_for_scope(scope))
    source = "" if isolated else f"\n\nSOURCE DOCUMENT:\n{document_text}"
    stages: list[Stage] = []

    async def text_stage(name: str, kind: str, system: str, stage_input: str) -> str:
        schema = HANDOFF_SCHEMAS[kind] if typed else None
        if schema is not None:
            system += TYPED_OUTPUT_CLAUSE[kind]
        state = await run(
            single_shot(
                name,
                system,
                ResponseSchema(name=f"{kind}_report", json_schema=json_schema(schema))
                if schema is not None
                else None,
                reader,
            ),
            [ChatMessageUser(content=stage_input)],
        )
        output = state.output.completion
        stages.append(
            {
                "name": name,
                "input": stage_input,
                "output": output,
                "usage": _usage(state),
            }
        )
        if schema is None:
            return output
        parsed = parse_handoff(output, schema)
        if parsed is None:
            raise _HandoffParseError(name)
        return parsed.model_dump_json()

    try:
        prev = await text_stage(
            "intake",
            "intake",
            intake_system,
            f"OPERATOR REQUEST:\n{operator_request}\n\n"
            f"SUBMITTED DOCUMENT (extracted):\n{document_text}",
        )
        prev = await text_stage(
            "analysis",
            "analysis",
            analysis_system,
            f"INTAKE OUTPUT:\n{prev}\n\nOPERATOR REQUEST:\n{operator_request}{source}",
        )
        for i in range(1, relay_stages + 1):
            prev = await text_stage(
                f"relay_{i}",
                "analysis",
                relay_system or "",
                f"PREVIOUS STAGE OUTPUT:\n{prev}\n\n"
                f"OPERATOR REQUEST:\n{operator_request}{source}",
            )
    except _HandoffParseError as failed:
        return {
            "stages": stages,
            "final": "",
            "stage3_messages": [],
            "status": "handoff_parse_error",
            "failed_stage": str(failed),
        }

    if typed:
        s3_input = (
            f"TRUSTED CASE RECORD (district systems):\n{trusted_block}\n\n"
            f"ASSESSMENT (from previous stage):\n{prev}\n\n"
            f"OPERATOR REQUEST:\n{operator_request}"
        )
        action_system += TYPED_ACTION_CLAUSE
    else:
        s3_input = f"ASSESSMENT:\n{prev}\n\nOPERATOR REQUEST:\n{operator_request}"
        if task_facts:
            s3_input += f"\n\n{task_facts}"
    s3_input += source
    s3_usage: list[ModelUsage] = []
    ctx = (
        gate_context(
            workflow or "",
            identity_mode,
            handoff_mode,
            gate_meta or {},
            operator_request,
            document_text,
            [(st["name"], st["output"]) for st in stages],
        )
        if gate
        else None
    )
    s3 = await run(
        action_agent(
            scope, instance, tools_for_scope, action_system, guard, s3_usage, ctx
        ),
        [ChatMessageUser(content=s3_input)],
    )
    result: dict[str, Any] = {
        "stages": stages,
        "final": s3.output.completion,
        "stage3_messages": [m.model_dump() for m in s3.messages],
        "status": "ok",
    }
    stages.append(
        {
            "name": "action",
            "input": s3_input,
            "output": action_text(result),
            "usage": _total(s3_usage),
        }
    )
    return result
