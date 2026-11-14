"""No model-visible string may betray that the run is a test or name internal ids."""

import importlib
import inspect
import json
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from inspect_ai.tool import ToolDef

from eduinject.agents import prompts, prompts_w1, prompts_w3
from eduinject.agents.task_facts import facts_w1, facts_w2, facts_w3
from eduinject.corpus import CANARIES, MARKER
from eduinject.extraction import extract
from eduinject.tools import directory_w1, directory_w3
from eduinject.tools.guard import ToolFactory

ROOT = Path(__file__).resolve().parents[1]
GENERATORS = [
    "make_fixtures_v2.py",
    "make_fixtures_w1.py",
    "make_fixtures_w3.py",
    "make_fixtures_controls.py",
]
FACTS = {"w1": facts_w1, "w2": facts_w2, "w3": facts_w3}
TOOL_MODULES = ["ats", "helpdesk", "parentmail"]

TELLS = [
    r"\bw[123]c?_\d{4}\b",
    r"\bb[1-9]\b",
    r"eduinject",
    r"canar(?:y|ies)",
    *map(re.escape, CANARIES),
    r"\b(?:test|testing|synthetic|mock|fixture|placeholder|simulat\w*|evaluation)\b",
    r"pypdf|reportlab|python-docx",
]
TELL_RE = re.compile("|".join(TELLS), re.IGNORECASE)


@pytest.fixture(scope="module")
def corpus_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A freshly generated public corpus, so the scan does not depend on the repo's."""
    root = tmp_path_factory.mktemp("corpus")
    for script in GENERATORS:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), "--out-root", str(root)],
            check=True,
            capture_output=True,
            env={"PYTHONPATH": str(ROOT / "src"), "PATH": ""},
        )
    return root


def _tool_strings() -> Iterator[tuple[str, str]]:
    for name in TOOL_MODULES:
        module = importlib.import_module(f"eduinject.tools.{name}")
        for attr, obj in vars(module).items():
            if attr.isupper() and isinstance(obj, str) and attr != "TOOL_SURFACE":
                yield f"tools.{name}.{attr}", obj
            if attr.isupper() and isinstance(obj, dict):
                for key, val in obj.items():
                    if isinstance(val, str):
                        yield f"tools.{name}.{attr}[{key}]", val
        factories: list[ToolFactory] = [
            f for scope in module.SCOPES.values() for f in scope
        ]
        for factory in factories:
            tdef = ToolDef(factory())
            yield f"tool:{tdef.name}", tdef.description
            for pname, param in tdef.parameters.properties.items():
                yield f"tool:{tdef.name}.{pname}", param.description or ""
        # Fixed return strings: the literal after `return` / `or`.
        for lit in re.findall(
            r"(?:return|refusal or)\s+(f?\"[^\"\n]+\")", inspect.getsource(module)
        ):
            yield f"tools.{name}.return", lit
    guard_src = inspect.getsource(importlib.import_module("eduinject.tools.guard"))
    for lit in re.findall(r"(f?\"[^\"\n]{12,}\")", guard_src):
        yield "tools.guard.literal", lit


def model_visible_strings(corpus_root: Path) -> Iterator[tuple[str, str]]:
    """Every string a model can see, as (source label, text)."""
    for manifest in sorted((corpus_root / "corpus").glob("manifest_*.jsonl")):
        controls = manifest.stem.endswith("_controls")
        for line in manifest.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            wf = "w" + manifest.stem.split("_w")[1][0]
            tag = f"{manifest.stem}:{row['artifact_id']}"
            yield f"{tag}:operator_request", row["operator_request"]
            yield f"{tag}:facts", FACTS[wf](row)
            # Controls have no attack arm: artifact and twin are the same file.
            paths = (
                {"twin": row["twin_path"]}
                if controls
                else {
                    "attack": row["artifact_path"],
                    "twin": row["twin_path"],
                }
            )
            for kind, rel in paths.items():
                yield f"{tag}:{kind}", extract(corpus_root / rel)
    for acct in directory_w1.ACCOUNTS:
        yield f"w1.account:{acct}", directory_w1.render_account(acct)
    for tag in directory_w1.ASSETS:
        yield f"w1.asset:{tag}", directory_w1.render_asset(tag)
    for sid, student in directory_w3.STUDENTS.items():
        yield f"w3.record:{sid}", directory_w3.render_student_record(sid)
        for g in student["guardians"]:
            yield f"w3.guardian:{sid}", directory_w3.render_guardian(g["email"])
    for mod in (prompts, prompts_w1, prompts_w3):
        for attr in ("INTAKE_SYSTEM", "ANALYSIS_SYSTEM", "ACTION_SYSTEM"):
            yield f"{mod.__name__}.{attr}", getattr(mod, attr)
    yield "prompts.SPOTLIGHT_CLAUSE", prompts.SPOTLIGHT_CLAUSE
    yield from _tool_strings()


def test_no_internal_ids_or_tells(corpus_root: Path) -> None:
    hits = []
    for label, text in model_visible_strings(corpus_root):
        # Reserved example-* domains are the allowed, deliberate fixture convention.
        scrubbed = re.sub(r"example-[\w.-]+|example\.\w+", "", text)
        hits += [f"{label}: {m.group(0)!r}" for m in TELL_RE.finditer(scrubbed)]
    assert hits == []


def test_marker_only_in_attack_documents(corpus_root: Path) -> None:
    leaks = [
        label
        for label, text in model_visible_strings(corpus_root)
        if MARKER in text and not label.endswith(":attack")
    ]
    assert leaks == []
    assert any(
        MARKER in text
        for label, text in model_visible_strings(corpus_root)
        if label.endswith(":attack")
    )
