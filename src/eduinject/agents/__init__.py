"""The three-stage agent pipeline and its versioned system prompts."""

from .pipeline import action_agent, run_pipeline, single_shot
from .prompts import (
    ACTION_SYSTEM,
    ANALYSIS_SYSTEM,
    INTAKE_SYSTEM,
    PROMPTS_VERSION,
)

__all__ = [
    "ACTION_SYSTEM",
    "ANALYSIS_SYSTEM",
    "INTAKE_SYSTEM",
    "PROMPTS_VERSION",
    "action_agent",
    "run_pipeline",
    "single_shot",
]
