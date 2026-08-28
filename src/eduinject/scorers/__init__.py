"""Deterministic scorers and the pure outcome functions behind them.

A model-graded judge is deliberately absent: with only a placeholder marker in
the corpus there is no injected instruction for a judge to detect adoption of.
It lands with the first real payloads.
"""

from .deterministic import (
    RUNS_KEY,
    action_divergence,
    exfiltration,
    propagation,
    scope_violation,
)
from .outcomes import (
    ENTITLEMENT,
    T2_TERMS,
    DivergenceOutcome,
    EgressMessage,
    ExfiltrationOutcome,
    PropagationOutcome,
    ScopeOutcome,
    action_text,
    exfiltration_outcome,
    marker_propagation,
    payload_tier,
    scope_outcome,
    twin_divergence,
)

__all__ = [
    "ENTITLEMENT",
    "RUNS_KEY",
    "T2_TERMS",
    "DivergenceOutcome",
    "EgressMessage",
    "ExfiltrationOutcome",
    "PropagationOutcome",
    "ScopeOutcome",
    "action_divergence",
    "action_text",
    "exfiltration",
    "exfiltration_outcome",
    "marker_propagation",
    "payload_tier",
    "propagation",
    "scope_outcome",
    "scope_violation",
    "twin_divergence",
]
