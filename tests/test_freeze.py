"""Freeze digest, file and script (doc 14 §10): a mismatch is always refused."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from eduinject import freeze
from eduinject.freeze import (
    FREEZE_PATHS,
    ROOT,
    FreezeEntry,
    freeze_problems,
    load_freeze,
    tree_digest,
)
from eduinject.models import load_models

sys.path.insert(0, str(ROOT / "scripts"))

PATTERNS = ("src/eduinject/**/*.py", "configs/**/*.json")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    _write(root / "src/eduinject/a.py", "A = 1\n")
    _write(root / "src/eduinject/sub/b.py", "B = 1\n")
    _write(root / "configs/models.json", "{}\n")
    _write(root / "configs/freeze.json", '{"version": "1", "entries": []}\n')
    return root


def _entry(root: Path, **over: Any) -> dict[str, Any]:
    entry = {
        "digest": tree_digest(root),
        "commit": "c" * 40,
        "date": "2026-12-01",
        "candidates": ["gate_open"],
        "references": ["not_isolated"],
        "held_out": ["gemini-3.8-flash"],
        "note": "first freeze",
    }
    return {**entry, **over}


def _freeze_file(root: Path, *entries: dict[str, Any]) -> Path:
    return _write(
        root / "configs/freeze.json",
        json.dumps({"version": "1", "entries": list(entries)}),
    )


def test_digest_is_stable_and_order_independent(tree: Path, tmp_path: Path) -> None:
    assert tree_digest(tree) == tree_digest(tree, tuple(reversed(FREEZE_PATHS)))
    other = tmp_path / "copy"
    # The same files created in the reverse order, so directory order differs.
    for path in sorted((p for p in tree.rglob("*") if p.is_file()), reverse=True):
        _write(other / path.relative_to(tree), path.read_text(encoding="utf-8"))
    assert tree_digest(other) == tree_digest(tree)
    assert len(tree_digest(tree)) == 64


def test_digest_changes_with_one_byte_in_a_frozen_file(tree: Path) -> None:
    before = tree_digest(tree)
    _write(tree / "src/eduinject/sub/b.py", "B = 2\n")
    assert tree_digest(tree) != before


def test_digest_changes_when_a_frozen_file_is_added_renamed_or_removed(
    tree: Path,
) -> None:
    seen = {tree_digest(tree)}
    added = _write(tree / "src/eduinject/corpus/payloads.py", "")
    seen.add(tree_digest(tree))
    added.rename(added.with_name("other.py"))
    seen.add(tree_digest(tree))
    (tree / "src/eduinject/a.py").unlink()
    seen.add(tree_digest(tree))
    assert len(seen) == 4


def test_digest_ignores_the_freeze_file_and_pycache(tree: Path) -> None:
    before = tree_digest(tree)
    _freeze_file(tree, _entry(tree))
    _write(tree / "src/eduinject/__pycache__/a.py", "junk")
    _write(tree / "src/eduinject/._a.py", "macOS metadata")
    assert tree_digest(tree) == before


def test_digest_ignores_an_unfrozen_file(tree: Path) -> None:
    before = tree_digest(tree)
    _write(tree / "README.md", "hello")
    assert tree_digest(tree) == before


@pytest.mark.parametrize(
    "path",
    [
        "configs/severity_weights.json",
        "scripts/run_sweep.py",
        "scripts/ceiling.py",
        "scripts/analyze.py",
        "scripts/build_features.py",
        "scripts/behavior_models.py",
        "scripts/_corpus_bases_w1.py",
        "scripts/_fixtures_common.py",
        "scripts/make_fixtures_w1.py",
        "corpus/manifest_w1.jsonl",
        "corpus/benign/ticket_0001_attack.docx",
        "corpus/canonical/manifest_w1.jsonl",
        "corpus/canonical/w1/ticket_0001_attack.docx",
    ],
)
def test_every_part_of_the_held_out_test_is_frozen(tree: Path, path: str) -> None:
    before = tree_digest(tree)
    _write(tree / path, "x")
    assert tree_digest(tree) != before


def test_the_repositorys_frozen_files_exist() -> None:
    for pattern in FREEZE_PATHS:
        if not pattern.startswith("corpus/canonical"):  # gated; absent here
            assert any(ROOT.glob(pattern)), pattern


def test_problems_when_no_entry(tree: Path) -> None:
    path = tree / "configs/freeze.json"
    assert freeze_problems(tree, path) == ["no freeze entry"]


def test_problems_when_the_file_is_missing_or_empty(tree: Path) -> None:
    path = tree / "configs/freeze.json"
    path.write_text("", encoding="utf-8")
    assert freeze_problems(tree, path)
    path.unlink()
    assert freeze_problems(tree, path)


def test_problems_when_digest_differs(tree: Path) -> None:
    path = _freeze_file(tree, _entry(tree))
    frozen = tree_digest(tree)
    _write(tree / "src/eduinject/a.py", "A = 2\n")
    assert freeze_problems(tree, path) == [
        (
            f"tree digest {tree_digest(tree)} differs from the frozen {frozen} "
            "(entry of 2026-12-01)"
        )
    ]


def test_problems_empty_when_matching(tree: Path) -> None:
    path = _freeze_file(tree, _entry(tree))
    assert freeze_problems(tree, path) == []


def test_only_the_last_entry_counts(tree: Path) -> None:
    path = _freeze_file(tree, _entry(tree), _entry(tree, digest="0" * 64))
    assert len(freeze_problems(tree, path)) == 1


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[]",
        "null",
        "{}",
        '{"version": "1"}',
        '{"version": "2", "entries": []}',
        '{"version": "1", "entries": {}}',
        '{"version": "1", "entries": ["x"]}',
        '{"version": "1", "entries": [{"digest": "x"}]}',
    ],
)
def test_malformed_file_raises(tree: Path, text: str) -> None:
    path = _write(tree / "configs/freeze.json", text)
    with pytest.raises(ValueError):
        load_freeze(path)
    assert freeze_problems(tree, path)


@pytest.mark.parametrize(
    "over",
    [
        {"digest": "abc"},
        {"digest": None},
        {"candidates": "gate_open"},
        {"held_out": [1]},
        {"note": 3},
        {"extra": "field"},
    ],
)
def test_malformed_entry_raises(tree: Path, over: dict[str, Any]) -> None:
    path = _freeze_file(tree, _entry(tree, **over))
    with pytest.raises(ValueError):
        load_freeze(path)


def test_the_repository_starts_with_no_entry() -> None:
    """Until the PI freezes, every confirm run is refused."""
    if not load_freeze():
        assert freeze_problems() == ["no freeze entry"]


# --------------------------------------------------------------------------
# scripts/freeze.py
# --------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            *args,
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tree: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`tree` as a committed git repository, with the script pointed at it."""
    script = _script()
    _git(tree, "init", "-q")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-q", "-m", "x")
    monkeypatch.setattr(script, "ROOT", tree)
    monkeypatch.setattr(script, "FREEZE_FILE", tree / "configs/freeze.json")
    return tree


def _script() -> Any:
    # scripts/freeze.py, not the package module of the same name.
    import importlib

    return importlib.import_module("freeze")


WRITE = ["write", "--candidate", "gate_open", "typed_gate"]
WRITE += ["--reference", "not_isolated", "--note"]


def test_write_appends_and_never_rewrites(repo: Path) -> None:
    script, path = _script(), repo / "configs/freeze.json"
    assert script.main(["check"]) == 5
    assert script.main([*WRITE, "one", "--date", "2026-12-01"]) == 0
    (first,) = load_freeze(path)
    assert first == FreezeEntry(
        digest=tree_digest(repo),
        commit=_git(repo, "rev-parse", "HEAD"),
        date="2026-12-01",
        candidates=("gate_open", "typed_gate"),
        references=("not_isolated",),
        held_out=("gemini-3.8-flash",),
        note="one",
    )
    assert script.main(["check"]) == 0
    _write(repo / "src/eduinject/a.py", "A = 2\n")
    _git(repo, "commit", "-q", "-am", "fix")
    assert script.main(["check"]) == 5
    assert script.main([*WRITE, "two"]) == 0
    entries = load_freeze(path)
    assert entries[0] == first and [e.note for e in entries] == ["one", "two"]
    assert script.main(["check"]) == 0


@pytest.mark.parametrize(
    "change",
    ["src/eduinject/a.py", "src/eduinject/new/pkg.py", "configs/models.json"],
)
def test_write_refuses_uncommitted_frozen_changes(repo: Path, change: str) -> None:
    _write(repo / change, "changed\n")
    before = (repo / "configs/freeze.json").read_bytes()
    assert _script().main([*WRITE, "x"]) == 2
    assert (repo / "configs/freeze.json").read_bytes() == before


def test_write_refuses_a_deleted_or_staged_frozen_file(repo: Path) -> None:
    _git(repo, "rm", "-q", "src/eduinject/a.py")
    assert _script().main([*WRITE, "x"]) == 2


def test_write_ignores_unfrozen_changes(repo: Path) -> None:
    _write(repo / "README.md", "notes")
    assert _script().main([*WRITE, "x"]) == 0


def test_write_refuses_a_malformed_or_missing_file(repo: Path) -> None:
    path = repo / "configs/freeze.json"
    path.write_text("{}", encoding="utf-8")
    assert _script().main([*WRITE, "x"]) == 2
    assert path.read_text(encoding="utf-8") == "{}"
    path.unlink()
    assert _script().main([*WRITE, "x"]) == 2
    assert not path.exists()


def test_write_refuses_outside_git(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = _script()
    monkeypatch.setattr(script, "ROOT", tree)
    monkeypatch.setattr(script, "FREEZE_FILE", tree / "configs/freeze.json")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tree.parent))
    assert script.main([*WRITE, "x"]) == 2
    assert load_freeze(tree / "configs/freeze.json") == []


@pytest.mark.parametrize("missing", ["--candidate", "--reference", "--note"])
def test_write_needs_candidate_reference_and_note(missing: str) -> None:
    argv = ["write", "--candidate", "a", "--reference", "b", "--note", "c"]
    i = argv.index(missing)
    with pytest.raises(SystemExit):
        _script().main(argv[:i] + argv[i + 2 :])


def test_write_refuses_a_bad_date(repo: Path) -> None:
    with pytest.raises(SystemExit):
        _script().main([*WRITE, "x", "--date", "tomorrow"])


def test_only_the_held_out_model_is_marked() -> None:
    held = {n for n, e in load_models().items() if e.held_out}
    assert held == {"gemini-3.8-flash"}


def test_freeze_module_is_stdlib_only() -> None:
    """The check must run wherever a sweep can start."""
    source = Path(str(freeze.__file__)).read_text(encoding="utf-8")
    assert "inspect_ai" not in source and "from ." not in source
