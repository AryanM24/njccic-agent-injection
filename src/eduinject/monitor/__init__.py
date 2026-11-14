"""Trace monitor (doc 11 §3.3): rule catalogs checked over action-stage calls.

Importing the package loads `rules` first, so a catalog module imported on its
own still finds the combinators it builds on.
"""

from .rules import MONITOR_RULES_VERSION, RULES, check_call, monitor

__all__ = ["MONITOR_RULES_VERSION", "RULES", "check_call", "monitor"]
