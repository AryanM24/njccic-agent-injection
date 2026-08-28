"""

Implements the trace log schema; writes two append-only JSONL files:

  conditions.jsonl  -- one row per experimental condition (written once)
  events.jsonl      -- one row per atomic event (prompt/completion/tool
                        call/tool result/inter-agent message/judge score)

Usage (**note**):

    from eduinject.tracelog import TraceLogger, ConditionConfig

    logger = TraceLogger(log_dir="logs/run_2026-08-10")

    config = ConditionConfig(
        condition_id="vec-email_goal-exfil_tech-invisible_perm-high_hard-none",
        attack_vector="email_attachment",
        attacker_goal="data_theft",
        delivery_technique="white_on_white_text",
        tool_permission_level="high",
        system_prompt_hardening="none",
        agent_count=3,
        agent_roster=["intake", "analysis", "action"],
        model_ids={"intake": "openrouter/anthropic/claude-sonnet-4-6",
                   "analysis": "openrouter/anthropic/claude-sonnet-4-6",
                   "action": "openrouter/anthropic/claude-sonnet-4-6"},
        is_control=False,
        is_baseline=False,
        target_workflow="parent_email_summarizing",
        screening_design_flagged=True,
    )
    config_hash = logger.register_condition(config)

    trace = logger.new_trace(config_hash, repetition_index=4,
                              corpus_file_id="file_0234")

    trace.log_attack_metadata(
        injected_payload_id="payload_0512",
        attack_vector="email_attachment",
        attacker_goal="data_theft",
        delivery_technique="white_on_white_text",
        is_benign_twin=False,
        is_benign_but_weird=False,
    )

    p = trace.log_prompt(agent_id="intake", agent_hop_index=0,
                          role="system", content="...", input_tokens=812)
    c = trace.log_completion(agent_id="intake", agent_hop_index=0,
                              content="...", output_tokens=244,
                              latency_ms=1830, stop_reason="end_turn",
                              parent_event_id=p)
    tc = trace.log_tool_call(agent_id="analysis", agent_hop_index=1,
                              tool_name="gmail.send",
                              tool_args={"to": "x@y.com", "body": "..."},
                              requested_scope="send_email",
                              granted_scope="send_email",
                              is_destructive=True,
                              action_taken="logged_and_refused")
    trace.log_tool_result(agent_id="analysis", agent_hop_index=1,
                           tool_name="gmail.send", result_status="refused",
                           result_content="blocked by policy",
                           parent_event_id=tc)
    trace.log_inter_agent_message(from_agent="intake", to_agent="analysis",
                                   content="...", carried_injection=True,
                                   injection_verbatim=False)
    trace.log_judge_score(judge_model_id="openrouter/anthropic/claude-sonnet-4-6",
                           attack_success=True, attack_goal_achieved="data_theft",
                           confidence=0.86, rationale="...", rubric_version="1.0")
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

SCHEMA_VERSION = "1.0"

EventType = Literal[
    "prompt",
    "completion",
    "tool_call",
    "tool_result",
    "inter_agent_message",
    "judge_score",
    "attack_metadata",
    "correction",
]

ActionTaken = Literal["executed", "logged_and_refused", "error"]
ResultStatus = Literal["success", "refused", "error"]


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _canonical_json(obj: dict) -> str:
    """Stable serialization so identical configs always hash the same."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def compute_config_hash(config: dict) -> str:
    digest = hashlib.sha256(_canonical_json(config).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


@dataclass
class ConditionConfig:
    condition_id: str
    attack_vector: str
    attacker_goal: str
    delivery_technique: str
    tool_permission_level: str
    system_prompt_hardening: str
    agent_count: int
    agent_roster: list[str]
    model_ids: dict[str, str]
    is_control: bool = False
    is_baseline: bool = False
    target_workflow: str = ""
    screening_design_flagged: bool = False

    def hashable_fields(self) -> dict:
        """Only fields that affect model behavior go into the hash.
        condition_id is a human label and is deliberately excluded."""
        return {
            "attack_vector": self.attack_vector,
            "attacker_goal": self.attacker_goal,
            "delivery_technique": self.delivery_technique,
            "tool_permission_level": self.tool_permission_level,
            "system_prompt_hardening": self.system_prompt_hardening,
            "agent_count": self.agent_count,
            "agent_roster": self.agent_roster,
            "model_ids": self.model_ids,
        }


class _JsonlWriter:
    """Thread-safe append-only JSONL writer."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, obj: dict) -> None:
        line = json.dumps(obj, separators=(",", ":"))
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


class TraceLogger:
    """Top-level logger for a single run. Owns conditions.jsonl and
    events.jsonl and hands out Trace objects for individual pipeline
    executions."""

    def __init__(self, log_dir: str, run_id: str | None = None):
        self.log_dir = Path(log_dir)
        self.run_id = run_id or f"run_{_utcnow_iso().replace(':', '-')}_{uuid.uuid4().hex[:6]}"
        self._conditions_writer = _JsonlWriter(self.log_dir / "conditions.jsonl")
        self._events_writer = _JsonlWriter(self.log_dir / "events.jsonl")
        self._event_counter = 0
        self._counter_lock = threading.Lock()
        self._registered_hashes: set[str] = set()

    def _next_event_id(self) -> str:
        with self._counter_lock:
            self._event_counter += 1
            return f"evt_{self._event_counter:06d}"

    def register_condition(self, config: ConditionConfig) -> str:
        """Writes the condition to conditions.jsonl (once per unique
        config_hash) and returns the config_hash to use when creating
        traces under this condition."""
        config_hash = compute_config_hash(config.hashable_fields())
        if config_hash not in self._registered_hashes:
            row = {
                "schema_version": SCHEMA_VERSION,
                "config_hash": config_hash,
                "created_at": _utcnow_iso(),
                **asdict(config),
            }
            self._conditions_writer.write(row)
            self._registered_hashes.add(config_hash)
        return config_hash

    def new_trace(
        self,
        config_hash: str,
        repetition_index: int,
        corpus_file_id: str | None = None,
    ) -> Trace:
        trace_id = f"trace_{uuid.uuid4().hex[:8]}"
        return Trace(
            logger=self,
            trace_id=trace_id,
            config_hash=config_hash,
            repetition_index=repetition_index,
            corpus_file_id=corpus_file_id,
        )

    def _write_event(self, envelope: dict, payload: dict) -> str:
        event_id = self._next_event_id()
        row = {
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "run_id": self.run_id,
            "timestamp": _utcnow_iso(),
            **envelope,
            "payload": payload,
        }
        self._events_writer.write(row)
        return event_id


@dataclass
class Trace:
    """One Intake -> Analysis -> Action pipeline execution. Every log_*
    call here writes one line to events.jsonl and returns its event_id,
    so you can chain parent_event_id for causal links (e.g. a tool_result
    pointing back at its tool_call)."""

    logger: TraceLogger
    trace_id: str
    config_hash: str
    repetition_index: int
    corpus_file_id: str | None = None

    def _envelope(self, agent_id: str, agent_hop_index: int, event_type: EventType,
                  parent_event_id: str | None, corpus_file_id: str | None) -> dict:
        return {
            "trace_id": self.trace_id,
            "repetition_index": self.repetition_index,
            "config_hash": self.config_hash,
            "agent_id": agent_id,
            "agent_hop_index": agent_hop_index,
            "event_type": event_type,
            "parent_event_id": parent_event_id,
            "corpus_file_id": corpus_file_id if corpus_file_id is not None else self.corpus_file_id,
        }

    def log_prompt(self, agent_id: str, agent_hop_index: int, role: str,
                    content: str, input_tokens: int,
                    parent_event_id: str | None = None) -> str:
        envelope = self._envelope(agent_id, agent_hop_index, "prompt", parent_event_id, None)
        payload = {"role": role, "content": content, "input_tokens": input_tokens}
        return self.logger._write_event(envelope, payload)

    def log_completion(self, agent_id: str, agent_hop_index: int, content: str,
                        output_tokens: int, latency_ms: int, stop_reason: str,
                        parent_event_id: str | None = None) -> str:
        envelope = self._envelope(agent_id, agent_hop_index, "completion", parent_event_id, None)
        payload = {
            "content": content,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
            "stop_reason": stop_reason,
        }
        return self.logger._write_event(envelope, payload)

    def log_tool_call(self, agent_id: str, agent_hop_index: int, tool_name: str,
                       tool_args: dict, requested_scope: str, granted_scope: str,
                       is_destructive: bool, action_taken: ActionTaken,
                       parent_event_id: str | None = None) -> str:
        envelope = self._envelope(agent_id, agent_hop_index, "tool_call", parent_event_id, None)
        payload = {
            "tool_name": tool_name,
            "tool_args": tool_args,
            "requested_scope": requested_scope,
            "granted_scope": granted_scope,
            "is_destructive": is_destructive,
            "action_taken": action_taken,
        }
        return self.logger._write_event(envelope, payload)

    def log_tool_result(self, agent_id: str, agent_hop_index: int, tool_name: str,
                         result_status: ResultStatus, result_content: str,
                         parent_event_id: str) -> str:
        envelope = self._envelope(agent_id, agent_hop_index, "tool_result", parent_event_id, None)
        payload = {
            "tool_name": tool_name,
            "result_status": result_status,
            "result_content": result_content,
        }
        return self.logger._write_event(envelope, payload)

    def log_inter_agent_message(self, from_agent: str, to_agent: str, content: str,
                                 carried_injection: bool, injection_verbatim: bool,
                                 agent_hop_index: int = 0,
                                 parent_event_id: str | None = None) -> str:
        envelope = self._envelope(from_agent, agent_hop_index, "inter_agent_message",
                                   parent_event_id, None)
        payload = {
            "from_agent": from_agent,
            "to_agent": to_agent,
            "content": content,
            "carried_injection": carried_injection,
            "injection_verbatim": injection_verbatim,
        }
        return self.logger._write_event(envelope, payload)

    def log_judge_score(self, judge_model_id: str, attack_success: bool,
                         attack_goal_achieved: str, confidence: float,
                         rationale: str, rubric_version: str) -> str:
        envelope = self._envelope("judge", -1, "judge_score", None, None)
        payload = {
            "judge_model_id": judge_model_id,
            "scored_trace_id": self.trace_id,
            "attack_success": attack_success,
            "attack_goal_achieved": attack_goal_achieved,
            "confidence": confidence,
            "rationale": rationale,
            "rubric_version": rubric_version,
        }
        return self.logger._write_event(envelope, payload)

    def log_attack_metadata(self, injected_payload_id: str, attack_vector: str,
                             attacker_goal: str, delivery_technique: str,
                             is_benign_twin: bool, is_benign_but_weird: bool) -> str:
        envelope = self._envelope("system", 0, "attack_metadata", None, None)
        payload = {
            "injected_payload_id": injected_payload_id,
            "attack_vector": attack_vector,
            "attacker_goal": attacker_goal,
            "delivery_technique": delivery_technique,
            "is_benign_twin": is_benign_twin,
            "is_benign_but_weird": is_benign_but_weird,
        }
        return self.logger._write_event(envelope, payload)

    def log_correction(self, corrects_event_id: str, reason: str, corrected_payload: dict) -> str:
        envelope = self._envelope("system", -1, "correction", corrects_event_id, None)
        payload = {"corrects_event_id": corrects_event_id, "reason": reason,
                    "corrected_payload": corrected_payload}
        return self.logger._write_event(envelope, payload)