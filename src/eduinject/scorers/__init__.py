"""Deterministic scorers and the pure outcome functions behind them.

A model-graded judge is deliberately absent: the public corpus carries only a
placeholder marker, so there is no injected instruction for a judge to detect
adoption of. It lands with the first canonical (gated) payloads. Until then the
G5 scorer records raw signals only (S1-S3 need the judge).
"""

from typing import TYPE_CHECKING, Any

from .outcomes import (
    FLAG_PHRASES,
    T2_TERMS,
    W1_SPEC,
    W2_SPEC,
    W3_SPEC,
    AuthorizationOutcome,
    CarryState,
    ControlOutcome,
    CorrectOutcome,
    DivergenceOutcome,
    EgressMessage,
    ExfilSpec,
    ExfiltrationOutcome,
    HarmOutcome,
    MisdirectionOutcome,
    ScopeOutcome,
    SuppressionOutcome,
    SurfacingOutcome,
    action_text,
    authorization_outcome,
    carry_states,
    classify_payload,
    component_carry,
    control_outcome,
    correct_outcome,
    exfiltration_outcome,
    flag_language_by_stage,
    harm_outcome,
    is_leak,
    is_policy_disclosure,
    misdirection_outcome,
    payload_tier,
    propagation_depth,
    scope_outcome,
    stage_names,
    stage_texts,
    suppression_outcome,
    surfacing,
    twin_divergence,
)
from .premise import (
    VERIFIED_PHRASES,
    VERIFIED_PHRASES_VERSION,
    PremiseAdoption,
    asserts_verified,
)
from .ranking import RankCorruption, kendall_tau, ranked_ids

if TYPE_CHECKING:
    from .deterministic import (
        RUNS_KEY,
        action_divergence,
        authorization,
        control_check,
        exfiltration,
        harm,
        misdirection,
        paired_utility,
        premise_adoption,
        propagation,
        rank_corruption,
        scope_violation,
        suppression,
    )

_DETERMINISTIC = frozenset(
    (
        "RUNS_KEY",
        "action_divergence",
        "authorization",
        "control_check",
        "exfiltration",
        "harm",
        "misdirection",
        "paired_utility",
        "premise_adoption",
        "propagation",
        "rank_corruption",
        "scope_violation",
        "suppression",
    )
)


def __getattr__(name: str) -> Any:
    # `deterministic` loads Inspect; deferring it keeps `outcomes` Inspect-free.
    if name in _DETERMINISTIC:
        from . import deterministic

        return getattr(deterministic, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "FLAG_PHRASES",
    "RUNS_KEY",
    "T2_TERMS",
    "VERIFIED_PHRASES",
    "VERIFIED_PHRASES_VERSION",
    "W1_SPEC",
    "W2_SPEC",
    "W3_SPEC",
    "AuthorizationOutcome",
    "CarryState",
    "ControlOutcome",
    "CorrectOutcome",
    "DivergenceOutcome",
    "EgressMessage",
    "ExfilSpec",
    "ExfiltrationOutcome",
    "HarmOutcome",
    "MisdirectionOutcome",
    "PremiseAdoption",
    "RankCorruption",
    "ScopeOutcome",
    "SuppressionOutcome",
    "SurfacingOutcome",
    "action_divergence",
    "action_text",
    "asserts_verified",
    "authorization",
    "authorization_outcome",
    "carry_states",
    "classify_payload",
    "component_carry",
    "control_check",
    "control_outcome",
    "correct_outcome",
    "exfiltration",
    "exfiltration_outcome",
    "flag_language_by_stage",
    "harm",
    "harm_outcome",
    "is_leak",
    "is_policy_disclosure",
    "kendall_tau",
    "misdirection",
    "misdirection_outcome",
    "paired_utility",
    "payload_tier",
    "premise_adoption",
    "propagation",
    "propagation_depth",
    "rank_corruption",
    "ranked_ids",
    "scope_outcome",
    "scope_violation",
    "stage_names",
    "stage_texts",
    "suppression",
    "suppression_outcome",
    "surfacing",
    "twin_divergence",
]
