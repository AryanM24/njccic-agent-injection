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

from typing import Any

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
from inspect_ai.util import store_as

from ..tools import Ledger, tools_for_scope
from .prompts import ACTION_SYSTEM, ANALYSIS_SYSTEM, INTAKE_SYSTEM


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


def action_agent(scope: str, instance: str) -> Agent:
    """Build the tool-using action stage.

    Args:
        scope: Write scope granted to this run (see `tools.ats.SCOPES`).
        instance: Ledger instance for this run.

    Returns:
        A react agent with the scope's tools.
    """
    return react(
        name="action",
        description="Carries out the assessed hiring decision using district systems.",
        # `AgentPrompt` with the other slots cleared keeps the system message
        # exactly equal to ACTION_SYSTEM. react() would otherwise append its own
        # assistant and submit prompts, putting un-versioned prompt text into an
        # independent variable (C4).
        prompt=AgentPrompt(instructions=ACTION_SYSTEM, assistant_prompt=None),
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
) -> dict[str, Any]:
    """Run one document through intake -> analysis -> action.

    Args:
        document_text: Extracted text of the submitted document.
        operator_request: What the district staff member asked for.
        scope: Write scope granted to the action stage.
        isolated: When True, no stage after intake sees the source document.
            When False (the negative control), every stage sees it.
        instance: Ledger instance for this run.

    Returns:
        The intake output (`h1`), the assessment (`h2`), the action stage's
        final completion (`final`), and the action stage's messages
        (`stage3_messages`).
    """
    store_as(Ledger, instance=instance).scope = scope

    s1 = await run(
        single_shot("intake", INTAKE_SYSTEM),
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
        single_shot("analysis", ANALYSIS_SYSTEM),
        [ChatMessageUser(content=s2_input)],
    )
    h2 = s2.output.completion

    s3_input = f"ASSESSMENT:\n{h2}\n\nOPERATOR REQUEST:\n{operator_request}"
    if not isolated:
        s3_input += f"\n\nSOURCE DOCUMENT:\n{document_text}"
    s3 = await run(
        action_agent(scope, instance),
        [ChatMessageUser(content=s3_input)],
    )

    return {
        "h1": h1,
        "h2": h2,
        "final": s3.output.completion,
        "stage3_messages": [m.model_dump() for m in s3.messages],
    }
