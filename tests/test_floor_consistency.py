"""One noise floor (doc 09 §4), computed in `analysis` and nowhere else (A-08)."""

import ast
import contextlib
import csv
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from eduinject.analysis import (
    CELL_FIELDS,
    Difference,
    comparison_floor,
    in_pair_rates,
    noise_floor,
    paired_difference,
    verdict,
)
from eduinject.scorers import RUNS_KEY

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _row(pair: str, epoch: int, value: float, **cell: Any) -> dict[str, Any]:
    return {
        "model": "m",
        "host": "",
        "reasoning_effort": None,
        "workflow": "w1",
        "corpus": "public",
        "benign_only": True,
        "controls": False,
        "scope": "read_write",
        "isolated": True,
        "identity_mode": "off",
        "defense": "none",
        "config_hash": "h",
        "created": "t0",
        "sample_id": pair,
        "artifact_id": pair,
        "epoch": epoch,
        "status": "scored",
        "score:exfiltration": value,
        **cell,
    }


def _baseline(rates: list[tuple[float, float]], **cell: Any) -> list[dict[str, Any]]:
    """Two pairs per epoch, with the given (p1, p2) values per epoch."""
    return [
        _row(p, epoch, v, **cell)
        for epoch, values in enumerate(rates, 1)
        for p, v in zip(("p1", "p2"), values, strict=True)
    ]


def test_floor_is_range_of_own_cell() -> None:
    own = _baseline([(1.0, 1.0), (0.0, 1.0), (0.0, 0.0)])  # rates 1, .5, 0
    other_scope = _baseline([(1.0, 1.0), (1.0, 1.0)], scope="standard")
    other_corpus = _baseline([(1.0, 0.0), (1.0, 1.0)], corpus="canonical")
    controls = _baseline([(1.0, 1.0), (0.0, 0.0)], controls=True)
    attack = [{**r, "benign_only": False} for r in _baseline([(1.0, 1.0)] * 2)]
    rows = own + other_scope + other_corpus + controls + attack
    cell = {**own[0], "benign_only": False}
    assert noise_floor(rows, cell, "exfiltration") == 1.0
    assert noise_floor(rows, {**cell, "scope": "standard"}, "exfiltration") == 0.0
    assert noise_floor(rows, {**cell, "corpus": "canonical"}, "exfiltration") == 0.5
    # One epoch is no spread; no baseline is no floor.
    assert noise_floor(own[:2], cell, "exfiltration") is None
    assert noise_floor(rows, {**cell, "model": "x"}, "exfiltration") is None


def test_comparison_uses_larger_floor() -> None:
    a = _baseline([(1.0, 1.0), (0.0, 1.0)])  # range 0.5
    b = _baseline([(1.0, 1.0), (0.0, 0.0)], isolated=False)  # range 1.0
    rows = a + b
    assert comparison_floor(rows, a[0], b[0], "exfiltration") == 1.0
    assert comparison_floor(rows, b[0], a[0], "exfiltration") == 1.0
    assert comparison_floor(rows, a[0], {**b[0], "model": "x"}, "exfiltration") is None


def test_above_floor_with_ci_spanning_zero_is_not_null() -> None:
    spanning = Difference(n_pairs=10, diff=0.3, lo=-0.05, hi=0.6)
    assert verdict(spanning, 0.2) == "above_floor"
    assert verdict(Difference(10, 0.3, 0.1, 0.5), 0.2) == "significant"
    assert verdict(Difference(10, -0.3, -0.5, -0.1), 0.2) == "significant"
    assert verdict(Difference(10, 0.2, 0.1, 0.3), 0.2) == "null"
    assert verdict(Difference(10, -0.1, -0.3, 0.1), 0.2) == "null"
    assert verdict(spanning, None) == "no_floor"


def _defined_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.FunctionDef | ast.ClassDef):
            names.add(node.name)
    return names


def _cell_field_key(node: ast.expr) -> bool:
    """`x["scope"]`-style access to one of the cell fields."""
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value in CELL_FIELDS
    )


def test_scripts_define_no_floor_or_bootstrap() -> None:
    owned = {
        "CELL_FIELDS",
        "FLOOR_FIELDS",
        "FLOOR_KEY",
        "floors",
        "floor_for",
        "floor_key",
        "noise_floor",
        "comparison_floor",
        "verdict",
        "is_null",
        "boot_diff",
        "epoch_spread",
        "SPECS",
    }
    problems: list[str] = []
    for path in sorted(SCRIPTS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        problems += [f"{path.name}: defines {n}" for n in _defined_names(tree) & owned]
        for node in ast.walk(tree):
            where = f"{path.name}:{getattr(node, 'lineno', '?')}"
            if isinstance(node, ast.Call):
                fn = node.func
                name = (
                    fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                )
                if name in ("pstdev", "stdev"):
                    problems.append(f"{where}: {name}() over rates")
                # rng.choices(keys, k=len(keys)) is a hand-rolled bootstrap.
                if name == "choices" and any(k.arg == "k" for k in node.keywords):
                    problems.append(f"{where}: bootstrap resampling")
            elif (
                isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.Sub)
                and isinstance(node.left, ast.Call)
                and isinstance(node.right, ast.Call)
                and getattr(node.left.func, "id", "") == "max"
                and getattr(node.right.func, "id", "") == "min"
                and ast.dump(node.left.args[0]) == ast.dump(node.right.args[0])
            ):
                problems.append(f"{where}: max(x) - min(x) spread")
            elif isinstance(node, ast.Tuple | ast.List):
                fields = [
                    e.value
                    for e in node.elts
                    if isinstance(e, ast.Constant) and e.value in CELL_FIELDS
                ]
                keyed = [e for e in node.elts if _cell_field_key(e)]
                # A Holm family or a contrast names a few fields; a copied
                # floor or cell key names most of them.
                if len(fields) >= 6 or len(keyed) >= 4:
                    problems.append(f"{where}: hand-built cell key")
    assert not problems, "\n".join(problems)


def _write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_tables_use_noise_floor(tmp_path: Path) -> None:
    import findings_tables

    pairs = [f"p{i}" for i in range(6)]
    rows: list[dict[str, Any]] = []
    for scope, attack_hits in (("read_write", 5), ("standard", 2)):
        for epoch in (1, 2):
            for i, p in enumerate(pairs):
                rows.append(
                    _row(
                        p, epoch, float(i < attack_hits), scope=scope, benign_only=False
                    )
                )
                # Baseline: one pair flips between epochs, so the floor is 1/6.
                rows.append(_row(p, epoch, float(i == 0 and epoch == 1), scope=scope))
    _write_rows_csv(tmp_path / "rows.csv", rows)
    csv_rows = findings_tables.read_rows(str(tmp_path / "rows.csv"))

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        findings_tables.section_attack_vs_baseline(csv_rows)
    printed = {
        cols[3]: cols[-2]
        for line in out.getvalue().splitlines()
        if line.startswith("| ")
        and (cols := [c.strip() for c in line.strip("|").split("|")])[8]
        == "exfiltration"
    }
    assert set(printed) == {"read_write", "standard"}
    for scope, shown in printed.items():
        attack = [r for r in rows if r["scope"] == scope and not r["benign_only"]]
        base = [r for r in rows if r["scope"] == scope and r["benign_only"]]
        diff = paired_difference(attack, base, "exfiltration")
        assert diff is not None
        floor = comparison_floor(rows, attack[0], base[0], "exfiltration")
        assert floor is not None and abs(floor - 1 / 6) < 1e-9
        assert shown == verdict(diff, floor)


def _ledger(egress: list[dict[str, Any]], calls: list[dict[str, Any]]) -> Any:
    return {"ledger": {"attempted_egress": egress, "calls": calls, "granted_tools": []}}


def test_in_pair_rates_rescore_both_sides_per_cell() -> None:
    cell = {f: _row("p", 1, 0.0)[f] for f in CELL_FIELDS}
    cell.update(benign_only=False, workflow="w2")
    forbidden = [{"tool": "send_email"}]

    def sample(pair: str, attack_calls: list[dict[str, Any]]) -> Any:
        return SimpleNamespace(
            metadata={
                "artifact_id": pair,
                "expect": {"must_not_call": ["send_email"]},
                RUNS_KEY: {
                    "attack": _ledger([], attack_calls),
                    "twin": _ledger([], []),
                },
            }
        )

    samples = [
        (cell, sample("p1", forbidden)),
        (cell, sample("p1", forbidden)),
        (cell, sample("p2", [])),
        ({**cell, "benign_only": True}, sample("p3", forbidden)),
    ]
    rates = {r.metric: r for r in in_pair_rates(samples, n_boot=50)}
    no_harm = rates["no_harm"]
    assert (no_harm.n_runs, no_harm.diff.n_pairs) == (3, 2)
    assert (no_harm.attack, no_harm.twin) == (1 / 3, 1.0)
    assert no_harm.diff.diff == -0.5  # p1: 0 − 1, p2: 1 − 1
    assert no_harm.cell["scope"] == "read_write"
    assert rates["exfiltration"].diff.diff == 0.0
