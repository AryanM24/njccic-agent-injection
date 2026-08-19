"""The three-stage pipeline: intake -> analysis -> action.

Stage isolation is structural. The stages are composed with Inspect's `run()`,
which copies its input and returns a fresh `AgentState`; each stage's input is
then built by hand from the previous stage's output alone. `handoff()` would
hand the downstream agent the entire upstream conversation and `as_tool()`
would let a model decide the routing — either would let a later stage re-read
the injected source document, which is the confound the whole measurement is
built to avoid. With `isolated=True` the document text is simply not present in
any input after stage 1: the isolation is a missing wire, not an instruction.
"""

from typing import Any, Callable

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

from ..tools import Ledger

ToolsForScope = Callable[[str, str | None], list[Tool]]
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
) -> Agent:
    """Build the tool-using action stage.

    Args:
        scope: Write scope granted to this run (a key of the workflow's
            `SCOPES` mapping, e.g. `tools.ats.SCOPES`, `tools.helpdesk.SCOPES`,
            `tools.parentmail.SCOPES`).
        instance: Ledger instance for this run.
        tools_for_scope: The workflow's tool-instantiation function.
        action_system: The workflow's action-stage system prompt.

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
        tools=tools_for_scope(scope, instance),
        # Keep the submit call in the transcript: `stage3_messages` is the
        # measurement record of what the agent did, and the default drops it.
        submit=AgentSubmit(keep_in_messages=True),
    )


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
) -> dict[str, Any]:
    """Run one document through intake -> analysis -> action.

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

    Returns:
        The intake output (`h1`), the assessment (`h2`), the action stage's
        final completion (`final`), and the action stage's messages
        (`stage3_messages`).
    """
    ledger = store_as(Ledger, instance=instance)
    ledger.scope = scope
    ledger.granted_tools = list(tool_names_for_scope(scope))

    s1 = await run(
        single_shot("intake", intake_system),
        [
            ChatMessageUser(
                content=(
                    f"OPERATOR REQUEST:\n{operator_request}\n\n"
                    f"SUBMITTED DOCUMENT (extracted):\n{document_text}"
                )
            )
        ],
    )
    h1 = s1.output.completion

    s2_input = f"INTAKE OUTPUT:\n{h1}\n\nOPERATOR REQUEST:\n{operator_request}"
    if not isolated:
        s2_input += f"\n\nSOURCE DOCUMENT:\n{document_text}"
    s2 = await run(
        single_shot("analysis", analysis_system),
        [ChatMessageUser(content=s2_input)],
    )
    h2 = s2.output.completion

    s3_input = f"ASSESSMENT:\n{h2}\n\nOPERATOR REQUEST:\n{operator_request}"
    if not isolated:
        s3_input += f"\n\nSOURCE DOCUMENT:\n{document_text}"
    s3 = await run(
        action_agent(scope, instance, tools_for_scope, action_system),
        [ChatMessageUser(content=s3_input)],
    )

    return {
        "h1": h1,
        "h2": h2,
        "final": s3.output.completion,
        "stage3_messages": [m.model_dump() for m in s3.messages],
    }
