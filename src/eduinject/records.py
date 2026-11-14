"""Run records: one flat, typed view of each recorded pipeline run.

A sample holds up to two runs (attack and twin) under `metadata["runs"]`. A
`RunRecord` joins what provenance and the monitor need from one of them: the
stage outputs, the un-datamarked document, and the action stage's tool calls,
each with its own result and ledger outcome. Pure over logged data; contacts
no model.
"""

import json
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Literal, NamedTuple, cast

from eduinject.analysis import finished_samples
from eduinject.defense import unmark
from eduinject.scorers.deterministic import RUNS_KEY

NOT_EXECUTED = "not_executed"
"""Outcome of a call with no ledger entry: the tool never ran (e.g. Inspect
rejected its arguments)."""

Status = Literal["ok", "doc_unavailable", "handoff_parse_error", "unfinished"]


class CallView(NamedTuple):
    """One tool call of the action stage."""

    step: int
    """0-based index among non-`submit` tool calls, in message order."""
    tool: str
    args: Mapping[str, Any]
    outcome: str
    """The matching ledger entry's outcome, or `NOT_EXECUTED`."""
    result: str | None
    """Text of the tool message answering this call, or None if none did."""


class RunRecord(NamedTuple):
    """One pipeline run (attack or twin) of one sample epoch."""

    label: Literal["attack", "twin"]
    sample_id: str
    artifact_id: str
    epoch: int
    cell: Mapping[str, Any]
    coords: Mapping[str, Any]
    """base_id, goal, file_type, channel, split."""
    operator_request: str
    document_text: str | None
    stages: tuple[tuple[str, str, str], ...]
    """(stage name, stage input, stage output), in pipeline order."""
    calls: tuple[CallView, ...]
    status: Status
    meta: Mapping[str, Any]
    """Sample metadata without the recorded runs."""


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(c.get("text", "") for c in content or [] if isinstance(c, dict))


def _norm(args: Any) -> str:
    return json.dumps(args, sort_keys=True, default=str)


def _calls(
    messages: Sequence[Mapping[str, Any]], ledger: Sequence[Mapping[str, Any]]
) -> tuple[CallView, ...]:
    """Action-stage calls joined to their results and ledger outcomes.

    `not_executed` can also mean the tool ledgered args different from what
    the model sent (no tool does today).
    """
    results = {
        m.get("tool_call_id"): _text(m.get("content"))
        for m in messages
        if m.get("role") == "tool"
    }
    used: set[int] = set()
    out: list[CallView] = []
    for m in messages:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            if tc["function"] == "submit":
                continue
            args = tc.get("arguments") or {}
            key = (tc["function"], _norm(args))
            hit = next(
                (
                    i
                    for i, e in enumerate(ledger)
                    if i not in used and (e.get("tool"), _norm(e.get("args"))) == key
                ),
                None,
            )
            if hit is not None:
                used.add(hit)
            out.append(
                CallView(
                    step=len(out),
                    tool=tc["function"],
                    args=args,
                    outcome=NOT_EXECUTED if hit is None else ledger[hit]["outcome"],
                    result=results.get(tc.get("id")),
                )
            )
    return tuple(out)


def records_from_sample(sample: Any, cell: Mapping[str, Any]) -> list[RunRecord]:
    """The run records of one sample epoch, attack before twin.

    A label absent from `metadata["runs"]` (benign-only cells, or a run cut
    off before it was written) yields no record.

    Args:
        sample: An Inspect `EvalSample`.
        cell: The sample's `CELL_FIELDS` (`analysis.cell_from_log`).
    """
    smeta = dict(sample.metadata or {})
    runs = smeta.pop(RUNS_KEY, None) or {}
    coords = {
        "base_id": smeta.get("base_id"),
        "goal": smeta.get("goal"),
        "file_type": smeta.get("file_type"),
        "channel": smeta.get("concealment"),
        "split": smeta.get("split"),
    }
    finished = sample.error is None and sample.limit is None
    records: list[RunRecord] = []
    for label in ("attack", "twin"):
        run = runs.get(label)
        if not run:
            continue
        pipeline = run.get("pipeline") or {}
        doc = run.get("document_text")
        status: Status = (
            "unfinished"
            if not finished or not pipeline
            else "handoff_parse_error"
            if pipeline.get("status") == "handoff_parse_error"
            else "doc_unavailable"
            if doc is None
            else "ok"
        )
        records.append(
            RunRecord(
                label=cast(Literal["attack", "twin"], label),
                sample_id=str(sample.id),
                artifact_id=str(smeta.get("artifact_id", sample.id)),
                epoch=sample.epoch,
                cell=cell,
                coords=coords,
                operator_request=sample.input
                if isinstance(sample.input, str)
                else "\n".join(m.text for m in sample.input),
                document_text=None if doc is None else unmark(doc),
                stages=tuple(
                    (s["name"], s.get("input", ""), s["output"])
                    for s in pipeline.get("stages") or []
                ),
                calls=_calls(
                    pipeline.get("stage3_messages") or [],
                    (run.get("ledger") or {}).get("calls") or [],
                ),
                status=status,
                meta=smeta,
            )
        )
    return records


def records_from_logs(
    log_dirs: Sequence[str], split: str | None = None
) -> Iterator[RunRecord]:
    """Run records of every winning finished sample under `log_dirs`.

    Args:
        log_dirs: Log directories (local, file:// or s3://).
        split: Keep only samples whose manifest `split` equals this.
    """
    for cell, sample in finished_samples(log_dirs):
        for rec in records_from_sample(sample, cell):
            if split is None or rec.coords["split"] == split:
                yield rec
