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

from collections.abc import Callable
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
from inspect_ai.model import ChatMessageSystem, ChatMessageUser, get_model
from inspect_ai.tool import Tool
from inspect_ai.util import store_as

from ..scorers.outcomes import action_text
from ..tools.guard import Guard
from ..tools.ledger import Ledger

ToolsForScope = Callable[[str, str | None, Guard | None], list[Tool]]
ToolNamesForScope = Callable[[str], tuple[str, ...]]


@agent
def single_shot(name: str, system_prompt: str) -> Agent:
    """Build a one-generation, no-tools agent.

    Args:
        name: Display name for the stage (used in the transcript).
        system_prompt: System prompt for the stage.

    Returns:
        An agent that generates exactly once.
    """

    async def execute(state: AgentState) -> AgentState:
        """Generate a single response to the stage input and return."""
        state.messages.insert(0, ChatMessageSystem(content=system_prompt))
        output = await get_model().generate(state.messages)
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

    Returns:
        A react agent with the scope's tools.
    """
    return react(
        name="action",
        description="Carries out the assessed request using district systems.",
        # `AgentPrompt` with the other slots cleared keeps the system message
        # exactly equal to action_system. react() would otherwise append its
        # own assistant and submit prompts, putting un-versioned prompt text
        # into an independent variable (C4).
        prompt=AgentPrompt(instructions=action_system, assistant_prompt=None),
        tools=tools_for_scope(scope, instance, guard),
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
    if usage is None:
        return None
    return {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}


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

    Returns:
        `stages` (one `Stage` per stage, in order: `intake`, `analysis`,
        `relay_1` ... `relay_k`, `action`), the action stage's final completion
        (`final`), its messages (`stage3_messages`) and `status`.
    """
    if relay_stages and relay_system is None:
        raise ValueError("relay_stages > 0 needs a relay_system prompt")
    ledger = store_as(Ledger, instance=instance)
    ledger.scope = scope
    ledger.granted_tools = list(tool_names_for_scope(scope))
    source = "" if isolated else f"\n\nSOURCE DOCUMENT:\n{document_text}"
    stages: list[Stage] = []

    async def text_stage(name: str, system: str, stage_input: str) -> str:
        state = await run(
            single_shot(name, system), [ChatMessageUser(content=stage_input)]
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
        return output

    prev = await text_stage(
        "intake",
        intake_system,
        f"OPERATOR REQUEST:\n{operator_request}\n\n"
        f"SUBMITTED DOCUMENT (extracted):\n{document_text}",
    )
    prev = await text_stage(
        "analysis",
        analysis_system,
        f"INTAKE OUTPUT:\n{prev}\n\nOPERATOR REQUEST:\n{operator_request}{source}",
    )
    for i in range(1, relay_stages + 1):
        prev = await text_stage(
            f"relay_{i}",
            relay_system or "",
            f"PREVIOUS STAGE OUTPUT:\n{prev}\n\n"
            f"OPERATOR REQUEST:\n{operator_request}{source}",
        )

    s3_input = f"ASSESSMENT:\n{prev}\n\nOPERATOR REQUEST:\n{operator_request}"
    if task_facts:
        s3_input += f"\n\n{task_facts}"
    s3_input += source
    s3 = await run(
        action_agent(scope, instance, tools_for_scope, action_system, guard),
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
            "usage": _usage(s3),
        }
    )
    return result
