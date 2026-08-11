"""The per-run ledger of mock tool activity.

The ledger is the measurement record: what the action agent called, what it
tried to send outside the district, and what it declined to do.
"""

from typing import Any

from inspect_ai.util import StoreModel
from pydantic import Field


class Ledger(StoreModel):
    """Record of a single pipeline run's tool activity."""

    scope: str = "read_only"
    """Write scope the action stage was granted."""

    calls: list[dict[str, Any]] = Field(default_factory=list)
    """Every mock tool call, in order."""

    attempted_egress: list[dict[str, Any]] = Field(default_factory=list)
    """Messages the agent tried to send outside the pipeline."""

    refused: list[dict[str, Any]] = Field(default_factory=list)
    """Actions the agent declined to take."""


def record(
    ledger: Ledger, name: str, args: dict[str, Any], outcome: str
) -> None:
    """Append a tool call to the ledger.

    Args:
        ledger: Ledger for this run.
        name: Tool name.
        args: Arguments the model supplied.
        outcome: What the mock tool did (e.g. "ok", "recorded_not_sent").
    """
    # Reassign rather than .append(): the store tracks assignment to the field
    # and can miss an in-place mutation of the list it handed back.
    ledger.calls = ledger.calls + [
        {"tool": name, "args": args, "outcome": outcome}
    ]
