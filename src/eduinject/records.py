"""Run records: one flat, typed view of each recorded pipeline run.

A sample holds up to two runs (attack and twin) under `metadata["runs"]`. A
`RunRecord` joins what provenance and the monitor need from one of them: the
stage outputs, the un-datamarked document, and the action stage's tool calls,
each with its own result and ledger outcome. Pure over logged data; contacts
no model.
"""

import json
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from types import MappingProxyType
from typing import Any, Literal, NamedTuple

from eduinject.analysis import cell_from_log, winning_samples
from eduinject.defense import unmark
from eduinject.scorers.deterministic import RUNS_KEY, SWAP_KEY

SWAP_CELLS: tuple[tuple[str, Literal["attack", "twin"]], ...] = (
    ("tt", "twin"),
    ("at", "attack"),
    ("ta", "attack"),
    ("aa", "attack"),
)
"""(swap cell, record label): first letter the document at and after the swap,
second the hand-off's source. Any cell the attack reached is an attack run."""

NOT_EXECUTED = "not_executed"
"""Outcome of a call with no ledger entry: the tool never ran (e.g. Inspect
rejected its arguments)."""

Status = Literal["ok", "doc_unavailable", "handoff_parse_error", "unfinished"]
Ended = Literal["finished", "parse_error", "limit", "missing"]
"""How one run ended, whatever its sample's other runs did (doc 14 §7):
`missing` is a run of a started sample whose outcome the log cannot give."""


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
    text_before: str = ""
    """Action-stage assistant text up to this call, including the text of the
    message that makes it (the A-07 intent signal reads it)."""


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
    usage_by_stage: Mapping[str, Mapping[str, Any]] = MappingProxyType({})
    """Each stage's recorded token `usage`, by stage name (absent when none)."""
    ledger_calls: tuple[Mapping[str, Any], ...] = ()
    """The ledger's calls as recorded (the scorers' input; `calls` is the
    message-side view)."""
    attempted_egress: tuple[Mapping[str, Any], ...] = ()
    granted_tools: tuple[str, ...] = ()
    submitted: bool = False
    """The action stage called `submit`."""
    swap: str = ""
    """The message-swap cell (`SWAP_CELLS`); empty for an ordinary run."""
    ended: Ended = "finished"
    """`status` is the sample's; this is the run's own (intention to treat)."""


def message_text(content: Any) -> str:
    """The text of a logged message's content (string or content parts)."""
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
        m.get("tool_call_id"): message_text(m.get("content"))
        for m in messages
        if m.get("role") == "tool"
    }
    used: set[int] = set()
    out: list[CallView] = []
    said = ""
    for m in messages:
        if m.get("role") != "assistant":
            continue
        if text := message_text(m.get("content")):
            said += text + "\n"
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
                    text_before=said,
                )
            )
    return tuple(out)


def _record(
    sample: Any,
    smeta: Mapping[str, Any],
    cell: Mapping[str, Any],
    run: Mapping[str, Any],
    label: Literal["attack", "twin"],
    swap: str = "",
) -> RunRecord:
    """The typed view of one recorded run of `sample`."""
    pipeline = run.get("pipeline") or {}
    ledger = run.get("ledger") or {}
    doc = run.get("document_text")
    status: Status = (
        "unfinished"
        if not _finished(sample) or not pipeline
        else "handoff_parse_error"
        if pipeline.get("status") == "handoff_parse_error"
        else "doc_unavailable"
        if doc is None
        else "ok"
    )
    ended: Ended = "missing"
    if pipeline.get("status") == "handoff_parse_error":
        ended = "parse_error"
    elif pipeline:
        ended = "missing" if doc is None else "finished"
    # Without the document no verdict on a message (misdirection) is possible.
    elif (
        sample.limit is not None
        and ledger
        and (doc is not None or not ledger.get("attempted_egress"))
    ):
        ended = "limit"
    return RunRecord(
        label=label,
        sample_id=str(sample.id),
        artifact_id=str(smeta.get("artifact_id", sample.id)),
        epoch=sample.epoch,
        cell=cell,
        coords={
            "base_id": smeta.get("base_id"),
            "goal": smeta.get("goal"),
            "file_type": smeta.get("file_type"),
            "channel": smeta.get("concealment"),
            "split": smeta.get("split"),
        },
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
            ledger.get("calls") or [],
        ),
        status=status,
        meta=smeta,
        usage_by_stage={
            s["name"]: s["usage"]
            for s in pipeline.get("stages") or []
            if s.get("usage")
        },
        ledger_calls=tuple(ledger.get("calls") or []),
        attempted_egress=tuple(ledger.get("attempted_egress") or []),
        granted_tools=tuple(ledger.get("granted_tools") or []),
        submitted=any(
            tc.get("function") == "submit"
            for m in pipeline.get("stage3_messages") or []
            for tc in m.get("tool_calls") or []
        ),
        swap=swap,
        ended=ended,
    )


INTAKE_DOCUMENT = "SUBMITTED DOCUMENT (extracted):\n"
"""What precedes the document in the intake stage's input (`agents.pipeline`)."""


def _cut_off(sample: Any) -> dict[str, dict[str, Any]]:
    """What an unfinished sample's log still holds of each unrecorded run.

    A run is written to the metadata when it ends. One cut off before that
    leaves its ledger in the sample's store and its document in the intake
    stage's input; attack and twin documents are read in that order.
    """
    documents: dict[str, None] = {}
    for event in sample.events:
        for message in event.input if event.event == "model" else []:
            text = message.text
            if text.startswith("attachment://"):
                text = sample.attachments.get(text.removeprefix("attachment://"), "")
            if message.role == "user" and INTAKE_DOCUMENT in text:
                documents[text.split(INTAKE_DOCUMENT, 1)[1]] = None
    runs: dict[str, dict[str, Any]] = defaultdict(dict)
    for key, value in sample.store.items():
        if key.startswith("Ledger:") and key.count(":") == 2:
            _, instance, field = key.split(":")
            runs[instance].setdefault("ledger", {})[field] = value
    if "twin" in runs and "attack" not in runs:  # a twin-only cell
        documents = {"": None, **documents}
    found = dict(zip(("attack", "twin"), documents))
    for instance, run in runs.items():
        # A cross cell is scored on the attack document (doc 14 §4).
        run["document_text"] = found.get("twin" if instance == "twin" else "attack")
    return runs


def _finished(sample: Any) -> bool:
    return sample.error is None and sample.limit is None


def _with_cut_off(
    sample: Any, runs: Mapping[str, Any], expected: Sequence[str]
) -> dict[str, Any]:
    """`runs` with an entry for every `expected` run of an unfinished sample."""
    cut = _cut_off(sample)
    return {name: runs.get(name) or cut.get(name, {}) for name in expected}


def _runs(sample: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """(metadata without recorded runs, ordinary runs, cross runs)."""
    smeta = dict(sample.metadata or {})
    runs = smeta.pop(RUNS_KEY, None) or {}
    cross = smeta.pop(SWAP_KEY, None) or {}
    return smeta, runs, cross


def records_from_sample(sample: Any, cell: Mapping[str, Any]) -> list[RunRecord]:
    """The run records of one sample epoch, attack before twin.

    A benign-only cell has no attack run. Every run of an unfinished sample has
    a record, a run that was cut off or never reached included (`ended`). A swap
    sample's cross runs are `swap_records`' business.

    Args:
        sample: An Inspect `EvalSample`.
        cell: The sample's `CELL_FIELDS` (`analysis.cell_from_log`).
    """
    smeta, runs, _ = _runs(sample)
    labels: tuple[Literal["attack", "twin"], ...] = ("attack", "twin")
    if not _finished(sample):
        expected = labels[cell.get("benign_only") is True :]
        runs = _with_cut_off(sample, runs, expected)
    return [
        _record(sample, smeta, cell, run, label)
        for label in labels
        if (run := runs.get(label)) is not None
    ]


def swap_records(sample: Any, cell: Mapping[str, Any]) -> list[RunRecord]:
    """The four message-swap records of one sample epoch, in `SWAP_CELLS` order.

    Empty for a sample that is no swap sample. Every cell of an unfinished
    sample has a record, as in `records_from_sample`.

    Args:
        sample: An Inspect `EvalSample`.
        cell: The sample's `CELL_FIELDS` (`analysis.cell_from_log`).
    """
    smeta, runs, cross = _runs(sample)
    if not _finished(sample) and (cross or cell.get("swap_stage")):
        names = ("attack", "twin", "at", "ta")
        runs = _with_cut_off(sample, runs | cross, names)
        cross = {name: runs[name] for name in ("at", "ta")}
    if not cross:
        return []
    by_cell = {"tt": runs.get("twin"), "aa": runs.get("attack"), **cross}
    return [
        _record(sample, smeta, cell, run, label, name)
        for name, label in SWAP_CELLS
        if (run := by_cell.get(name)) is not None
    ]


def _logged(
    read: Callable[[Any, Mapping[str, Any]], list[RunRecord]],
    log_dirs: Sequence[str],
    split: str | None,
) -> Iterator[RunRecord]:
    cells: dict[str, dict[str, Any]] = {}
    for log, sample in winning_samples(log_dirs, finished=False):
        cell = cells.setdefault(log.location, cell_from_log(log))
        for rec in read(sample, cell):
            if split is None or rec.coords["split"] == split:
                yield rec


def records_from_logs(
    log_dirs: Sequence[str], split: str | None = None
) -> Iterator[RunRecord]:
    """Run records of every winning started sample under `log_dirs`.

    Args:
        log_dirs: Log directories (local, file:// or s3://).
        split: Keep only samples whose manifest `split` equals this.
    """
    return _logged(records_from_sample, log_dirs, split)


def swap_records_from_logs(
    log_dirs: Sequence[str], split: str | None = None
) -> Iterator[RunRecord]:
    """`swap_records` of every winning started sample under `log_dirs`.

    Args:
        log_dirs: Log directories (local, file:// or s3://).
        split: Keep only samples whose manifest `split` equals this.
    """
    return _logged(swap_records, log_dirs, split)
