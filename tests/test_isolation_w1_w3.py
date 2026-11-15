"""Stage isolation holds for W1 and W3 too, not just W2.

`run_pipeline` is shared, but each workflow supplies its own prompts and tool
functions; this guards against a workflow wiring that quietly gave later stages
the source document.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from eduinject.agents import pipeline, prompts_w1, prompts_w3
from eduinject.agents.prompts_relay import RELAY_SYSTEM
from eduinject.task import RELAY_MAX
from eduinject.tools import helpdesk, parentmail

MARKER = "ZZPAYLOADZZ"
DOCUMENT = f"source text {MARKER} more source text"

WORKFLOWS = {
    "w1": (prompts_w1, helpdesk),
    "w3": (prompts_w3, parentmail),
}


@pytest.fixture
def captured_inputs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    inputs: list[str] = []

    async def recorder(agent: Any, messages: Any, *args: Any, **kwargs: Any) -> Any:
        inputs.append("\n".join(message.text for message in messages))
        return SimpleNamespace(
            output=SimpleNamespace(completion="stage output, no marker here"),
            messages=[],
        )

    monkeypatch.setattr(pipeline, "run", recorder)
    return inputs


@pytest.mark.parametrize("workflow", sorted(WORKFLOWS))
@pytest.mark.parametrize("k", range(RELAY_MAX + 1))
@pytest.mark.parametrize("isolated", [True, False])
async def test_isolation_per_workflow(
    workflow: str, k: int, isolated: bool, captured_inputs: list[str]
) -> None:
    """Document at stage 1 and no other for every relay count; `isolated=False`
    is the negative control that proves the isolated case is not vacuous."""
    prompts, tools = WORKFLOWS[workflow]
    await pipeline.run_pipeline(
        DOCUMENT,
        "handle this",
        scope="read_only",
        isolated=isolated,
        instance=f"iso-{workflow}-{k}-{isolated}",
        tools_for_scope=tools.tools_for_scope,
        tool_names_for_scope=tools.tool_names_for_scope,
        intake_system=prompts.INTAKE_SYSTEM,
        analysis_system=prompts.ANALYSIS_SYSTEM,
        action_system=prompts.ACTION_SYSTEM,
        relay_stages=k,
        relay_system=RELAY_SYSTEM[workflow],
    )
    assert len(captured_inputs) == 3 + k
    assert MARKER in captured_inputs[0]
    assert all((MARKER in text) is (not isolated) for text in captured_inputs[1:])
    assert all("handle this" in text for text in captured_inputs[2:-1])
