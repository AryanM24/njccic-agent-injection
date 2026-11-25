"""The models registry: `configs/models.json`, the one record of which models
the study runs, on which host, at what list price.

Host pin and price are part of the measurement (an unpinned OpenRouter host can
silently change quantization), so they live in one reviewed file rather than in
a script. Entries still marked `"TODO"` are placeholders for families nobody
has pinned yet; they load, but `ModelEntry.todo` is set and callers refuse them
rather than guess a pin or a price.
"""

import json
from pathlib import Path
from typing import Any, NamedTuple

CONFIGS = Path(__file__).resolve().parents[2] / "configs"


class ModelEntry(NamedTuple):
    """One registry row. `provider` is the OpenRouter pin; prices are USD per 1M tokens."""

    name: str
    model: str
    family: str
    open_weight: bool
    provider: Any
    reasoning_effort: str
    price_in: Any
    price_out: Any
    price_source: str
    note: str
    todo: bool
    held_out: bool = False
    """Never run on dev scenarios; needs a matching freeze (doc 14 §10)."""


def load_models(path: Path = CONFIGS / "models.json") -> dict[str, ModelEntry]:
    """Load the registry keyed by name."""
    entries: dict[str, ModelEntry] = {}
    for row in json.loads(path.read_text())["models"]:
        todo = "TODO" in (
            row["model"],
            row["family"],
            row["provider"],
            row["price_in"],
            row["price_out"],
        )
        entries[row["name"]] = ModelEntry(**row, todo=todo)
    return entries
