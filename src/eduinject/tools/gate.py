"""The runtime policy gate (B3, doc 11 §4.3): the monitor's rules at call time.

The gate defines no rules. Every sink call (`scorers.provenance.SINKS`, ruling
7) runs `check` — `monitor.rules.check_call` itself — against the calls so far
and the run's sources, built by the same `sources_from_runtime` the offline
monitor uses; on any violation it returns the first violated rule's denial
instead of running the tool. The gate's call history carries what the offline
record carries (outcome, the tool message text, the assistant text up to the
call), so the gate blocks exactly the calls the monitor flags on the same
trace. It wraps the workflow's tools from outside, so the v2 guard inside a
tool only sees calls the gate let through.
"""

import functools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from inspect_ai.model import ChatMessageAssistant
from inspect_ai.tool import Tool, ToolDef, ToolResult
from inspect_ai.util import store_as

from ..defense import unmark
from ..monitor.rules import RULES, RunContext
from ..monitor.rules import check_call as check
from ..records import NOT_EXECUTED, CallView, _text
from ..scorers.provenance import SINKS, Sources, sources_from_runtime
from .ledger import BLOCKED, Ledger, record

__all__ = ["GateContext", "check", "gate_context", "gated_tools", "note_message"]


@dataclass
class GateContext:
    """What the gate knows about one run while it is in progress."""

    workflow: str
    meta: Mapping[str, Any]
    sources: Sources
    history: list[CallView] = field(default_factory=list)
    """The action stage's calls so far, as `records` would rebuild them."""
    text: str = ""
    """Action-stage assistant text so far (`CallView.text_before`)."""


def gate_context(
    workflow: str,
    identity_mode: str,
    handoff_mode: str | None,
    meta: Mapping[str, Any],
    operator_request: str,
    document_text: str,
    stage_outputs: Sequence[tuple[str, str]],
) -> GateContext:
    """The gate's context once the pre-action stages have run.

    Args:
        workflow: "w1", "w2" or "w3".
        identity_mode: The cell's identity_mode (decides the trusted text).
        handoff_mode: The cell's handoff_mode.
        meta: Sample metadata.
        operator_request: The operator request text.
        document_text: The document as the pipeline was given it (datamarks
            are removed, as the offline record does).
        stage_outputs: (stage name, output) of the stages before the action.
    """
    return GateContext(
        workflow=workflow,
        meta=meta,
        sources=sources_from_runtime(
            workflow,
            identity_mode,
            handoff_mode,
            meta,
            operator_request,
            unmark(document_text),
            stage_outputs,
        ),
    )


def note_message(ctx: GateContext, message: ChatMessageAssistant) -> None:
    """Add an action-stage assistant message's text to `ctx.text`, exactly as
    `records` accumulates `text_before`."""
    if text := _text(message.model_dump()["content"]):
        ctx.text += text + "\n"


def _gated(tool: Tool, ctx: GateContext, instance: str | None) -> Tool:
    tdef = ToolDef(tool)
    sink = SINKS[ctx.workflow].get(tdef.name)
    rules = RULES[ctx.workflow]

    # `wraps` (without __dict__) keeps the original signature and annotations,
    # so Inspect still validates and coerces arguments before the gate runs.
    @functools.wraps(tool, updated=())
    async def execute(**kwargs: Any) -> ToolResult:
        ledger = store_as(Ledger, instance=instance)
        call = CallView(
            step=len(ctx.history),
            tool=tdef.name,
            args=kwargs,
            outcome=NOT_EXECUTED,
            result=None,
            text_before=ctx.text,
        )
        found = (
            check(
                rules,
                call,
                ctx.history,
                RunContext(ctx.workflow, ctx.meta, ctx.sources),
            )
            if sink
            else []
        )
        if found:
            rule = next(r for r in rules if r.id == found[0].rule_id)
            record(ledger, tdef.name, dict(kwargs), BLOCKED, rule.id)
            if sink and sink[0] == "to":
                ledger.attempted_egress = ledger.attempted_egress + [
                    {**kwargs, "blocked": True, "rule_id": rule.id}
                ]
            ctx.history.append(call._replace(outcome=BLOCKED, result=rule.denial))
            return rule.denial
        before = len(ledger.calls)
        # shortcut: a tool that raises leaves no history entry, shifting later
        # steps; no workflow tool raises today.
        result = await tdef.tool(**kwargs)
        outcome = ledger.calls[-1]["outcome"] if len(ledger.calls) > before else None
        ctx.history.append(
            call._replace(outcome=outcome or NOT_EXECUTED, result=str(result))
        )
        return result

    return ToolDef(
        execute,
        name=tdef.name,
        description=tdef.description,
        parameters=tdef.parameters,
        parallel=tdef.parallel,
    ).as_tool()


def gated_tools(
    tools: Sequence[Tool], ctx: GateContext, instance: str | None
) -> list[Tool]:
    """Wrap every tool with the gate, keeping its name, description and
    parameters.

    Non-sink tools run and are appended to `ctx.history`. A sink call runs
    `check` first; on any violation the first violated rule's `denial` is
    returned, the call is ledgered `BLOCKED` with that `rule_id` (a send also
    gets a blocked `attempted_egress` entry) and the tool never runs.

    Args:
        tools: The action stage's tools (already carrying any v2 guard).
        ctx: This run's gate context.
        instance: Ledger instance for this run.
    """
    return [_gated(t, ctx, instance) for t in tools]
