"""The three-stage agent pipeline and its versioned system prompts."""

from .pipeline import action_agent, run_pipeline, single_shot
from .prompts import (
    ACTION_SYSTEM,
    ANALYSIS_SYSTEM,
    INTAKE_SYSTEM,
    PROMPTS_VERSION,
)

__all__ = [
    "single_shot",
    "action_agent",
    "run_pipeline",
    "PROMPTS_VERSION",
    "INTAKE_SYSTEM",
    "ANALYSIS_SYSTEM",
    "ACTION_SYSTEM",
]
