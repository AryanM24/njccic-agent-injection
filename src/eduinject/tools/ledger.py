"""The per-run ledger of mock tool activity.

The ledger is the measurement record: what the action agent called and what it
tried to send outside the district. A model declining to act leaves no entry;
the guard's and the policy gate's refusals are marked on the call itself
(`DENIED`, `BLOCKED`).
"""

from typing import Any

from inspect_ai.util import StoreModel
from pydantic import Field

DENIED = "denied_by_guard"
"""Ledger outcome for a call the tool guard refused (tools/guard.py)."""

UNDELIVERABLE = "undeliverable"
"""Ledger outcome for a send with a syntactically invalid recipient: nothing
was delivered to anyone on that message."""

BLOCKED = "blocked_by_policy"
"""Ledger outcome for a call the policy gate refused (tools/gate.py): the tool
never ran. The entry also carries the refusing `rule_id`."""


class Ledger(StoreModel):
    """Record of a single pipeline run's tool activity."""

    scope: str = "read_only"
    """Write scope the action stage was granted."""

    granted_tools: list[str] = Field(default_factory=list)
    """Names of the tools actually instantiated for this run's scope.

    Set by `run_pipeline` at construction time, from whichever workflow's
    `tool_names_for_scope` was passed in. Recording the resolved names here —
    rather than having the scorer re-resolve `scope` against a hardcoded
    tool module — is what lets `scope_violation` work unchanged across W1,
    W2, and W3, each of which grants a different tool set per scope.
    """

    calls: list[dict[str, Any]] = Field(default_factory=list)
    """Every mock tool call, in order."""

    attempted_egress: list[dict[str, Any]] = Field(default_factory=list)
    """Messages the agent tried to send outside the pipeline."""


def record(
    ledger: Ledger,
    name: str,
    args: dict[str, Any],
    outcome: str,
    rule_id: str | None = None,
) -> None:
    """Append a tool call to the ledger.

    Args:
        ledger: Ledger for this run.
        name: Tool name.
        args: Arguments the model supplied.
        outcome: What the mock tool did (e.g. "ok", "recorded_not_sent").
        rule_id: The monitor rule that blocked the call (`BLOCKED` only).
    """
    entry: dict[str, Any] = {"tool": name, "args": args, "outcome": outcome}
    if rule_id is not None:
        entry["rule_id"] = rule_id
    # Reassign rather than .append(): the store tracks assignment to the field
    # and can miss an in-place mutation of the list it handed back.
    ledger.calls = ledger.calls + [entry]
