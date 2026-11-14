"""Spotlighting by datamarking (defense="spotlight"), the prompt-level baseline.

Datamarking (Hines et al. 2024, "Defending Against Indirect Prompt Injection
Attacks With Spotlighting") interleaves a marker character through untrusted
text, and the system prompt tells the model that marked text is data, never
instructions. It is the comparison point for structural isolation: a defense
that asks the model to behave, against one that removes the wire.

The system-prompt clause lives in `agents/prompts.py` (C4); this module holds
only the transformation, so the scorers can undo it without importing agents.
"""

import re

DEFENSE_VERSION = "1.0"
"""Version of the marking scheme and its prompt clause. Folded into the hash."""

DEFENSES: tuple[str, ...] = ("none", "spotlight")

DATAMARK = "\ue000"
"""U+E000, the first Private Use Area code point: the marker Hines et al.
recommend over the caret they illustrate with. It never occurs in real text, so
an injection cannot pre-mark itself with an ordinary character."""

_RUNS = re.compile(r"[ \t]+")


def datamark(text: str) -> str:
    """Replace every run of spaces/tabs in `text` with the datamark.

    Hines et al. replace all whitespace. Newlines are kept here so a ticket's
    or resume's line structure survives (doc 10 §4); the payload marker holds
    no whitespace, so verbatim propagation stays detectable.
    """
    return _RUNS.sub(DATAMARK, text)


def unmark(text: str) -> str:
    """Undo datamarking so scorers match terms a model copied from marked text."""
    return text.replace(DATAMARK, " ")
