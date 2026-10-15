"""Stage isolation holds for W1 and W3 too, not just W2.

`run_pipeline` is shared, but each workflow supplies its own prompts and tool
functions; this guards against a workflow wiring that quietly gave later stages
the source document.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from eduinject.agents import pipeline, prompts_w1, prompts_w3
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
@pytest.mark.parametrize("isolated", [True, False])
async def test_isolation_per_workflow(
    workflow: str, isolated: bool, captured_inputs: list[str]
) -> None:
    prompts, tools = WORKFLOWS[workflow]
    await pipeline.run_pipeline(
        DOCUMENT,
        "handle this",
        scope="read_only",
        isolated=isolated,
        instance=f"iso-{workflow}-{isolated}",
        tools_for_scope=tools.tools_for_scope,
        tool_names_for_scope=tools.tool_names_for_scope,
        intake_system=prompts.INTAKE_SYSTEM,
        analysis_system=prompts.ANALYSIS_SYSTEM,
        action_system=prompts.ACTION_SYSTEM,
    )
    assert len(captured_inputs) == 3
    assert MARKER in captured_inputs[0]
    # The negative control is what proves the isolated case is not vacuous.
    assert (MARKER in captured_inputs[1]) is (not isolated)
    assert (MARKER in captured_inputs[2]) is (not isolated)
