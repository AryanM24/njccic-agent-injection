"""The load-bearing test: stage isolation is structural, not instructed.

`run_pipeline` is exercised with Inspect's `run()` replaced by a recorder, so
no model is contacted and the assertion is purely about which text reaches
which stage's input.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from eduinject.agents import pipeline

MARKER = "ZZPAYLOADZZ"
DOCUMENT = f"resume text {MARKER} more resume text"
REQUEST = "rank these"


def _message_text(messages: Any) -> str:
    return "\n".join(message.text for message in messages)


@pytest.fixture
def captured_inputs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace `pipeline.run` with a recorder and collect each stage's input."""
    inputs: list[str] = []

    async def recorder(agent: Any, messages: Any, *args: Any, **kwargs: Any) -> Any:
        inputs.append(_message_text(messages))
        return SimpleNamespace(
            output=SimpleNamespace(completion="stage output, no marker here"),
            messages=[],
        )

    monkeypatch.setattr(pipeline, "run", recorder)
    return inputs


async def test_isolated_true(captured_inputs: list[str]) -> None:
    await pipeline.run_pipeline(
        DOCUMENT,
        REQUEST,
        scope="read_only",
        isolated=True,
        instance="t",
    )

    assert len(captured_inputs) == 3
    assert MARKER in captured_inputs[0]
    assert MARKER not in captured_inputs[1]
    assert MARKER not in captured_inputs[2]


async def test_isolated_false(captured_inputs: list[str]) -> None:
    """Negative control. Without it, a bug that left stages 2 and 3 empty would
    make `test_isolated_true` pass while proving nothing."""
    await pipeline.run_pipeline(
        DOCUMENT,
        REQUEST,
        scope="read_only",
        isolated=False,
        instance="t-control",
    )

    assert len(captured_inputs) == 3
    assert MARKER in captured_inputs[0]
    assert MARKER in captured_inputs[1]
    assert MARKER in captured_inputs[2]
