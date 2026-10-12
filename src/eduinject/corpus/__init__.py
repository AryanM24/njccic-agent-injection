"""Corpus support code: the placeholder marker and the gated-payload loader.

Release policy (docs/design/05, README C3): the public repository carries only
the placeholder marker. Realistic injection wording is Tier 1 and lives in a
git-ignored module, `eduinject/corpus/payloads.py`, which exists only on
workstations cleared to hold it. Nothing in the tracked tree imports that
module unconditionally -- every consumer goes through `load_gated_payloads()`,
which returns None when the module is absent.
"""

MARKER = "ZZPAYLOADZZ"
"""Harmless sentinel placed in every attack artifact so propagation is
detectable without any instruction text being present."""

GOALS: tuple[str, ...] = (
    "unauthorized_approval",
    "data_theft",
    "warning_suppression",
    "cross_agent_propagation",
)
"""Attacker-goal labels used in manifests (docs/design/04 taxonomy names)."""


def load_gated_payloads() -> dict[str, dict[str, str]] | None:
    """Load the gated payload table if this workstation holds it.

    Returns:
        ``{workflow: {goal: text}}`` for workflows "w1", "w2" and "w3", or None
        when the git-ignored `payloads.py` is not present (the normal state of
        a fresh clone).

    Raises:
        ValueError: If the module exists but is malformed -- a gated file that
            silently half-loads would produce a corpus that looks canonical and
            is not.
    """
    try:
        from . import payloads  # type: ignore[attr-defined]
    except ImportError:
        return None

    table = getattr(payloads, "PAYLOADS", None)
    if not isinstance(table, dict):
        raise ValueError("eduinject.corpus.payloads must define a PAYLOADS dict")
    for workflow in ("w1", "w2", "w3"):
        entries = table.get(workflow)
        if not isinstance(entries, dict) or set(entries) != set(GOALS):
            raise ValueError(
                f"PAYLOADS['{workflow}'] must map exactly the goals {sorted(GOALS)}"
            )
        for goal, text in entries.items():
            if MARKER not in text:
                raise ValueError(
                    f"PAYLOADS['{workflow}']['{goal}'] must contain the marker "
                    f"'{MARKER}' so propagation stays measurable"
                )
    return table
