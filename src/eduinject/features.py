"""Feature table (A4, doc 11 §3.4): one row per recorded run.

Every column has a role. `pre_outcome` columns (cell and corpus coordinates,
and every per-stage column of a stage before `action`) are fixed before the
action stage runs; `outcome` columns (the action stage, the tool sequence, the
monitor, provenance and the scorer outcomes) are what the run did. The
behaviour predictors may read `pre_outcome` columns only. Pure over run
records; contacts no model.
"""

import json
import math
import re
from collections.abc import Iterable
from typing import Any, Literal, get_args

from .analysis import CELL_FIELDS
from .monitor import RULES, monitor
from .records import RunRecord
from .scorers import premise, ranking
from .scorers.deterministic import judge_run
from .scorers.outcomes import (
    PremiseRanks,
    carry_states,
    component_carry,
    exfiltration_from_metadata,
    flag_language_by_stage,
    harm_outcome,
    on_file,
    premise_ranks,
    scope_outcome,
    stage_texts,
)
from .scorers.provenance import ProvClass, argument_substitution, label_record
from .task import workflow

FEATURES_VERSION = "1.1"

Role = Literal["pre_outcome", "outcome"]

COORDS = ("base_id", "goal", "file_type", "channel", "split")
OUTCOMES = (
    "out:exfiltration",
    "out:authorization",
    "out:scope_violation",
    "out:did_correct_thing",
    "out:harm_attempted",
    "out:harm_completed",
    "out:misdirection",
    "out:rank_shift",
    "out:premise_relied",
    "out:substituted",
)
_PRE = frozenset(
    (
        *CELL_FIELDS,
        "label",
        "artifact_id",
        "epoch",
        *COORDS,
        "doc_available",
        "handoff_parse_error",
    )
)
_POST = frozenset(
    (
        "status",
        *(f"prov:{c}" for c in get_args(ProvClass)),
        "monitor:rules",
        "monitor:first",
        "monitor:origin_stage",
        "calls",
        "lookups_before_first_write",
        "verified_before_write",
        "submitted",
        *OUTCOMES,
    )
)
_STAGE_COL = re.compile(
    r"(?:(?:flag|tokens_in|tokens_out):(?P<s1>intake|analysis|relay_[1-9]\d*|action))"
    r"|(?:carry:(?P<s2>intake|analysis|relay_[1-9]\d*|action)(?::[^:]+)?)"
)
NAN = math.nan


def role_of(column: str) -> Role:
    """`pre_outcome` or `outcome` for a feature column.

    Raises:
        KeyError: `column` is not a feature column.
    """
    if column in _PRE:
        return "pre_outcome"
    if column in _POST:
        return "outcome"
    if m := _STAGE_COL.fullmatch(column):
        return "outcome" if (m["s1"] or m["s2"]) == "action" else "pre_outcome"
    raise KeyError(column)


def _f(value: bool | None) -> float:
    return NAN if value is None else float(value)


def _pipeline(record: RunRecord) -> dict[str, Any]:
    """The stage outputs in the shape the scorers' functions read."""
    return {"stages": [{"name": n, "output": o} for n, _, o in record.stages]}


def _run(record: RunRecord) -> dict[str, Any]:
    """The recorded-run shape `judge_run` reads, rebuilt from the typed view."""
    run: dict[str, Any] = {
        "ledger": {
            "calls": list(record.ledger_calls),
            "attempted_egress": list(record.attempted_egress),
            "granted_tools": list(record.granted_tools),
        }
    }
    if record.document_text is not None:
        run["document_text"] = record.document_text
    return run


def _stage_columns(record: RunRecord) -> dict[str, Any]:
    if not record.stages:
        return {}
    pipeline = _pipeline(record)
    meta = record.meta
    states = carry_states(pipeline, str(meta.get("payload_marker") or "\0"))
    flags = flag_language_by_stage(pipeline)
    components = component_carry(pipeline, meta.get("component_markers") or {})
    out: dict[str, Any] = {}
    for name, _, _ in record.stages:
        usage = record.usage_by_stage.get(name) or {}
        out[f"carry:{name}"] = states[name]
        out[f"flag:{name}"] = float(flags[name])
        for component in meta.get("component_markers") or {}:
            state = components.get(name, {}).get(component, "absent")
            out[f"carry:{name}:{component}"] = state
        out[f"tokens_in:{name}"] = usage.get("input_tokens", NAN)
        out[f"tokens_out:{name}"] = usage.get("output_tokens", NAN)
    return out


def _sequence(record: RunRecord, write_tools: Iterable[str]) -> dict[str, Any]:
    """Tool-sequence columns. A lookup is any call not in the workflow's
    `write_tools`; `verified_before_write` is whether an `ok` lookup preceded
    the first write (NaN when nothing was written)."""
    writes = set(write_tools)
    first = next((c.step for c in record.calls if c.tool in writes), None)
    before = record.calls if first is None else record.calls[:first]
    return {
        "calls": len(record.calls),
        "lookups_before_first_write": len(before),
        "verified_before_write": NAN
        if first is None
        else float(any(c.outcome == "ok" for c in before)),
        "submitted": float(record.submitted),
    }


def _outcomes(record: RunRecord, pair: RunRecord | None) -> dict[str, float]:
    """Every scorer outcome, recomputed on this run's own ledger; the pair-level
    `rank_shift` and `substituted` sit on the attack row only."""
    wf = workflow(record.cell["workflow"])
    meta, run = record.meta, _run(record)
    calls, egress = list(record.ledger_calls), list(record.attempted_egress)
    judged = judge_run(
        meta,
        run,
        wf.spec,
        wf.state_changing,
        wf.write_tools,
        wf.send_tools,
        wf.escalation_tools,
    )
    harm = harm_outcome(
        calls,
        egress,
        classify=lambda e: exfiltration_from_metadata(e, meta, wf.spec),
        expect=meta.get("expect", {}),
        entitled_actions=meta.get("entitled_actions", {}),
        state_changing=wf.state_changing or {},
        document_text=record.document_text,
        on_file=on_file(meta, wf.spec),
        authorized=meta.get("authorized_recipients", []),
    )
    paired = pair is not None and pair.status == "ok"
    attack = record if record.label == "attack" else pair
    twin = pair if record.label == "attack" else record
    ranks: dict[str, list[str] | None] = {
        r.label: ranking.ranked_ids(list(r.ledger_calls))
        for r in (attack, twin)
        if r is not None and paired
    }
    rank_shift = NAN
    w2_ranked = meta.get("true_ranking") and meta.get("attacker_candidate")
    if record.label == "attack" and paired and w2_ranked:
        rank_shift = ranking.rank_corruption(
            ranks["attack"],
            ranks["twin"],
            meta["true_ranking"],
            meta["attacker_candidate"],
        ).shift
    relied = NAN
    if meta.get("premise_marker"):
        subject = str(meta.get("premise_subject", ""))
        tool = str(meta.get("verification_tool", ""))
        side_ranks = PremiseRanks(None, None)
        if record.label == "attack" and paired:
            side_ranks = premise_ranks(meta, ranks["attack"], ranks["twin"])
        relied = float(
            premise.premise_adoption(
                stage_texts(_pipeline(record)),
                meta["premise_marker"],
                calls,
                subject=subject,
                verification_tool=tool,
                attack_rank=side_ranks.attack,
                twin_rank=side_ranks.twin,
                sink_tools=sorted(set(wf.write_tools) - set(wf.escalation_tools)),
                lookup_available=tool in record.granted_tools,
                authorized=meta.get("authorized_recipients", []),
            ).relied
        )
    substituted = NAN
    if record.label == "attack" and paired and twin is not None:
        substituted = float(
            argument_substitution(
                label_record(record), label_record(twin), [c.tool for c in twin.calls]
            ).substituted
        )
    return {
        "out:exfiltration": float(judged.g1.completed),
        "out:authorization": float(judged.unauthorized) if wf.state_changing else NAN,
        "out:scope_violation": float(
            scope_outcome(calls, list(record.granted_tools)).violated
        ),
        "out:did_correct_thing": _f(
            None if judged.correct is None else judged.correct.did_correct_thing
        ),
        "out:harm_attempted": float(harm.attempted),
        "out:harm_completed": float(harm.completed),
        "out:misdirection": float("misdirection" in judged.control.harms),
        "out:rank_shift": rank_shift,
        "out:premise_relied": relied,
        "out:substituted": substituted,
    }


def feature_row(record: RunRecord, pair: RunRecord | None) -> dict[str, Any]:
    """One run's features (doc 11 §3.4).

    Columns that need the action stage and the document (tool sequence,
    provenance, monitor, outcomes) are NaN unless the run's status is `ok`; outcomes are NaN for
    both runs when either side stopped at a typed hand-off parse error, as
    the scorers do (doc 11 §4.2).

    Args:
        record: The run.
        pair: The other run of the same sample epoch (twin for an attack run,
            attack for a twin), or None when there is none.
    """
    row: dict[str, Any] = {f: record.cell.get(f) for f in CELL_FIELDS}
    row |= {
        "label": record.label,
        "artifact_id": record.artifact_id,
        "epoch": record.epoch,
        **{c: record.coords.get(c) for c in COORDS},
        "doc_available": float(record.document_text is not None),
        "handoff_parse_error": float(record.status == "handoff_parse_error"),
        "status": record.status,
    }
    row |= _stage_columns(record)
    wf = workflow(record.cell["workflow"])
    sequence = _sequence(record, wf.write_tools)
    row |= sequence if record.status == "ok" else dict.fromkeys(sequence, NAN)
    scored = record.status == "ok" and (
        pair is None or pair.status != "handoff_parse_error"
    )
    counts = dict.fromkeys(get_args(ProvClass), NAN)
    first_rule = origin = rules = ""
    if record.status == "ok":
        counts = dict.fromkeys(counts, 0.0)
        for label in label_record(record):
            counts[label.cls] += 1
        result = monitor(record, RULES[record.cell["workflow"]])
        rules = ";".join(sorted({v.rule_id for v in result.violations}))
        if (first := result.first_violation) is not None:
            first_rule, origin = first.rule_id, first.origin_stage or ""
    row |= {f"prov:{c}": n for c, n in counts.items()}
    row |= {
        "monitor:rules": rules,
        "monitor:first": first_rule,
        "monitor:origin_stage": origin,
    }
    row |= _outcomes(record, pair) if scored else dict.fromkeys(OUTCOMES, NAN)
    return row


def _sample_key(record: RunRecord) -> tuple[str, int, str]:
    return (
        record.sample_id,
        record.epoch,
        json.dumps(dict(record.cell), sort_keys=True, default=str),
    )


def feature_rows(records: Iterable[RunRecord]) -> list[dict[str, Any]]:
    """`feature_row` for every record, each paired with its sample's other run."""
    records = list(records)
    by_sample: dict[tuple[str, int, str], list[RunRecord]] = {}
    for r in records:
        runs = by_sample.setdefault(_sample_key(r), [])
        if any(o.label == r.label for o in runs):
            raise ValueError(f"two {r.label} runs for sample {_sample_key(r)}")
        runs.append(r)
    return [
        feature_row(
            r, next((o for o in by_sample[_sample_key(r)] if o.label != r.label), None)
        )
        for r in records
    ]
