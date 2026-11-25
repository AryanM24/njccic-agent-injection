"""estimate_cost.py: fallback scaling, TODO refusal, token stats from a log."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from estimate_cost import SWAP_PAIR_FACTOR, TokenStats, estimate_usd, token_stats

from eduinject.models import load_models


def test_cost_fallback_scales_with_relays() -> None:
    luna = load_models()["luna"]
    base = estimate_usd(10, False, 0, luna, None)
    assert base is not None
    assert estimate_usd(10, False, 3, luna, None) == base * 2
    assert estimate_usd(10, True, 0, luna, None) == base / 2


def test_todo_price_has_no_estimate_and_logged_tokens_win() -> None:
    models = load_models()
    assert estimate_usd(1, False, 0, models["todo-open-family"], None) is None
    got = estimate_usd(2, False, 3, models["luna"], TokenStats(1, 1e6, 1e6))
    assert got is not None and abs(got - 1.2) < 1e-9


def test_token_stats_from_mock_log(tmp_path: Path) -> None:
    from inspect_ai import Task, eval
    from inspect_ai.dataset import Sample
    from inspect_ai.solver import generate

    eval(
        Task(dataset=[Sample(input="hi")], solver=generate(), metadata={"k": 1}),
        model="mockllm/model",
        log_dir=str(tmp_path),
    )
    stats = token_stats([tmp_path])
    assert stats is not None and stats.n_samples == 1 and stats.mean_in > 0
    assert token_stats([tmp_path], {"k": 2}) is None
    assert token_stats([tmp_path / "missing"]) is None


def test_swap_scales_the_fallback_only() -> None:
    luna = load_models()["luna"]
    base = estimate_usd(10, False, 1, luna, None)
    assert base is not None
    swap = estimate_usd(10, False, 1, luna, None, swap=True)
    assert swap is not None and abs(swap - SWAP_PAIR_FACTOR * base) < 1e-12
    assert SWAP_PAIR_FACTOR == 1.6
    measured = TokenStats(1, 1e6, 1e6)
    assert estimate_usd(2, False, 0, luna, measured, swap=True) == estimate_usd(
        2, False, 0, luna, measured
    )
