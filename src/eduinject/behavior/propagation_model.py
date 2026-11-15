"""Stage propagation: Markov chain, path decomposition and half-life (A6).

Doc 11 §3.6. Reads A4 feature rows (dicts as `feature_rows` returns them or as
`csv.DictReader` reads them back) and contacts no model. Only scored attack
runs (`label == "attack"`, `status == "ok"`, `out:harm_completed` not NaN)
enter: a twin carries no marker, and a run without outcomes has no path.
"""

import math
import random
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Literal, NamedTuple, TypeVar, cast, get_args

from ..analysis import CELL_FIELDS, N_BOOT, percentiles
from ..scorers.outcomes import CarryState

Outcome = Literal["no_act", "benign_act", "harmful_act"]
GROUP_FIELDS = CELL_FIELDS
"""The chain is fitted once per experimental cell: never pooled across any
condition (defense, identity, scope, relays, verification, effort, prompts,
corpus, tool surface)."""
HALFLIFE_FIELDS = tuple(f for f in CELL_FIELDS if f != "relay_stages")
"""Half-life pools relay depths (that is what it fits) and nothing else."""

_STATES: tuple[CarryState, ...] = get_args(CarryState)
_OUTCOMES: tuple[Outcome, ...] = get_args(Outcome)
_STAGE = re.compile(r"(?:carry|flag):(intake|analysis|relay_[1-9]\d*|action)")


class RunPath(NamedTuple):
    """One run's carry state at each stage, in pipeline order, and its outcome."""

    artifact_id: str
    states: tuple[CarryState, ...]
    outcome: Outcome


class Chain(NamedTuple):
    """Homogeneous stage-to-stage transitions; the last stage emits the outcome.

    A row is present only for a from-state that was observed.
    """

    transition: dict[str, dict[str, float]]
    emission: dict[str, dict[str, float]]
    n_runs: int


class PathDecomposition(NamedTuple):
    """P(harm) = reach_analysis × reach_action_given_analysis × harm_given_reached
    + residual, the residual being harm not on the analysis→action carry path.
    NaN where a conditional has no runs to condition on."""

    reach_analysis: float
    reach_action_given_analysis: float
    harm_given_reached: float
    p_harm: float
    residual: float


class Survival(NamedTuple):
    """Fitted per-hop survival `s`, `half_life`, its 95% CI, the runs at risk,
    and the bootstrap draws that defined the CI."""

    s: float
    half_life: float
    lo: float
    hi: float
    n: int
    kept: int


def stage_order(stage: str) -> int:
    """Sort key putting stages in pipeline order (intake, analysis, relays, action)."""
    if stage == "intake":
        return 0
    if stage == "analysis":
        return 1
    if stage == "action":
        return 1_000
    return 1 + int(stage.removeprefix("relay_"))


def stages_of(row: Mapping[str, Any]) -> list[str]:
    """The stages this run had, in pipeline order (a CSV pads absent ones with "")."""
    found = {
        m[1]
        for k, v in row.items()
        if (m := _STAGE.fullmatch(k)) and v not in ("", None)
    }
    return sorted(found, key=stage_order)


def _column(column: str, stage: str) -> str:
    """`carry` -> `carry:<stage>`; `carry:<component>` -> `carry:<stage>:<component>`;
    `flag` -> `flag:<stage>`."""
    family, _, suffix = column.partition(":")
    return f"{family}:{stage}" + (f":{suffix}" if suffix else "")


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def is_on(value: Any) -> bool:
    """Carried (any carry state but `absent`) or, for a flag column, flagged."""
    if value in _STATES:
        return bool(value != "absent")
    return _num(value) == 1.0


def scored_attacks(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Attack runs at status `ok` whose `out:harm_completed` is defined."""
    return [
        r
        for r in rows
        if r.get("label") == "attack"
        and r.get("status") == "ok"
        and not math.isnan(_num(r.get("out:harm_completed")))
    ]


def paths_from_features(
    rows: Iterable[Mapping[str, Any]], marker_column: str = "carry"
) -> list[RunPath]:
    """One `RunPath` per scored attack run.

    Args:
        rows: Feature rows.
        marker_column: `carry` for the whole marker, `carry:<component>` for one
            component marker (doc 11 §5.1).

    `harmful_act` is `out:harm_completed`; `benign_act` is any executed call
    otherwise (`calls > 0`); else `no_act`.

    Raises:
        ValueError: A carry column holds something other than a carry state.
    """
    paths = []
    for r in scored_attacks(rows):
        values = [r.get(_column(marker_column, s)) or "absent" for s in stages_of(r)]
        if bad := [v for v in values if v not in _STATES]:
            raise ValueError(f"unknown carry state(s) {bad} in {marker_column}")
        states = tuple(cast(CarryState, v) for v in values)
        outcome: Outcome = (
            "harmful_act"
            if _num(r["out:harm_completed"]) == 1.0
            else "benign_act"
            if _num(r.get("calls")) > 0
            else "no_act"
        )
        paths.append(RunPath(str(r["artifact_id"]), states, outcome))
    return paths


def _normalise(
    counts: Mapping[str, Counter[str]], to: Sequence[str]
) -> dict[str, dict[str, float]]:
    return {
        frm: {t: c[t] / total for t in to}
        for frm, c in counts.items()
        if (total := sum(c.values()))
    }


def fit_chain(paths: Sequence[RunPath]) -> Chain:
    """Pooled transition fractions between consecutive stages, and the
    last-stage state's outcome fractions."""
    moves: dict[str, Counter[str]] = defaultdict(Counter)
    emits: dict[str, Counter[str]] = defaultdict(Counter)
    for p in paths:
        for a, b in zip(p.states, p.states[1:]):
            moves[a][b] += 1
        if p.states:
            emits[p.states[-1]][p.outcome] += 1
    return Chain(_normalise(moves, _STATES), _normalise(emits, _OUTCOMES), len(paths))


def _div(a: int, b: int) -> float:
    return a / b if b else math.nan


def decompose(paths: Sequence[RunPath]) -> PathDecomposition:
    """Where the attack is lost: at analysis (index 1), on the way to the last
    (action) stage, or at the action itself. Relays sit inside the middle factor;
    their per-hop loss is the half-life."""
    reached_a = [p for p in paths if len(p.states) > 1 and p.states[1] != "absent"]
    reached = [p for p in reached_a if p.states[-1] != "absent"]
    harm = sum(p.outcome == "harmful_act" for p in paths)
    factors = (
        _div(len(reached_a), len(paths)),
        _div(len(reached), len(reached_a)),
        _div(sum(p.outcome == "harmful_act" for p in reached), len(reached)),
    )
    p_harm = _div(harm, len(paths))
    # The product telescopes to harm-with-carry / runs, so the residual is the
    # share of runs harmed off the analysis→action carry path; defined even when
    # a conditional has no runs.
    with_carry = sum(p.outcome == "harmful_act" for p in reached)
    return PathDecomposition(*factors, p_harm, p_harm - _div(with_carry, len(paths)))


def survival_by_depth(
    rows: Iterable[Mapping[str, Any]], column: str
) -> dict[int, tuple[int, int]]:
    """`{k: (at_risk, survived)}` over relay depth k = 0..`RELAY_MAX`.

    At risk: scored attack runs with `column` on at analysis and a stage at
    analysis + k before the action stage; survived: still on there.

    Args:
        rows: Feature rows.
        column: `carry`, `carry:<component>` (content) or `flag` (warning).
    """
    counts: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for r in scored_attacks(rows):
        stages = [s for s in stages_of(r) if s != "action"]
        if "analysis" not in stages:
            continue
        i = stages.index("analysis")
        if not is_on(r.get(_column(column, "analysis"))):
            continue
        for k, stage in enumerate(stages[i:]):
            counts[k][0] += 1
            counts[k][1] += is_on(r.get(_column(column, stage)))
    return {k: (n, y) for k, (n, y) in sorted(counts.items())}


def _log_lik(s: float, counts: Mapping[int, tuple[int, int]]) -> float:
    return sum(
        y * k * math.log(s) + (n - y) * math.log1p(-(s**k))
        for k, (n, y) in counts.items()
    )


def fit_survival(counts: Mapping[int, tuple[int, int]]) -> float:
    """Binomial MLE of s for S(k) = s^k, by golden-section search on (0, 1].

    Exactly 1.0 when nothing was lost, 0.0 when nothing survived a hop, NaN
    without any hop (k ≥ 1) at risk. k = 0 carries no information.
    """
    hops = {k: (n, y) for k, (n, y) in counts.items() if k >= 1 and n > 0}
    if not hops:
        return math.nan
    if all(y == n for n, y in hops.values()):
        return 1.0
    if all(y == 0 for _, y in hops.values()):
        return 0.0
    lo, hi = 1e-12, 1 - 1e-12
    g = (math.sqrt(5) - 1) / 2
    while hi - lo > 1e-10:
        a, b = hi - g * (hi - lo), lo + g * (hi - lo)
        if _log_lik(a, hops) < _log_lik(b, hops):
            lo = a
        else:
            hi = b
    return (lo + hi) / 2


def half_life(s: float) -> float:
    """Hops until half survives: ln 0.5 / ln s; `inf` at s = 1, 0 at s = 0."""
    if math.isnan(s):
        return math.nan
    if s >= 1.0:
        return math.inf
    if s <= 0.0:
        return 0.0
    return math.log(0.5) / math.log(s)


T = TypeVar("T", RunPath, Mapping[str, Any])


class BootCI(NamedTuple):
    """A pair-bootstrap 95% interval and how many draws defined it."""

    lo: float
    hi: float
    kept: int


def _pair(item: RunPath | Mapping[str, Any]) -> str:
    return item.artifact_id if isinstance(item, RunPath) else str(item["artifact_id"])


def bootstrap_pairs(
    paths_or_rows: Sequence[T],
    statistic: Callable[[list[T]], float],
    n_boot: int = N_BOOT,
    seed: int = 0,
) -> "BootCI":
    """95% interval of `statistic` over pair (`artifact_id`) resamples.

    A draw on which the statistic is undefined (NaN) is dropped and
    `BootCI.kept` counts the rest; (NaN, NaN, 0) when every draw is.
    Percentiles are doc 11 §2.8's.
    """
    by_pair: dict[str, list[T]] = defaultdict(list)
    for item in paths_or_rows:
        by_pair[_pair(item)].append(item)
    keys = sorted(by_pair)
    if not keys:
        return BootCI(math.nan, math.nan, 0)
    rng = random.Random(seed)
    draws = [
        statistic([x for k in rng.choices(keys, k=len(keys)) for x in by_pair[k]])
        for _ in range(n_boot)
    ]
    kept = [d for d in draws if not math.isnan(d)]
    return (
        BootCI(*percentiles(kept), len(kept)) if kept else BootCI(math.nan, math.nan, 0)
    )


def survival(
    rows: Sequence[Mapping[str, Any]],
    column: str,
    n_boot: int = N_BOOT,
    seed: int = 0,
) -> Survival:
    """`fit_survival` and `half_life` for `column`, with a pair-bootstrap CI on
    the half-life (`lo`/`hi`) and `n` the runs at risk at k = 0.

    Scored attack runs only, so a run whose twin stopped at a typed hand-off
    parse error (outcomes NaN on both sides) is excluded here too.
    """
    counts = survival_by_depth(rows, column)
    s = fit_survival(counts)
    lo, hi, kept = bootstrap_pairs(
        scored_attacks(rows),
        lambda chosen: half_life(fit_survival(survival_by_depth(chosen, column))),
        n_boot,
        seed,
    )
    return Survival(s, half_life(s), lo, hi, counts.get(0, (0, 0))[0], kept)


def group_rows(
    rows: Iterable[Mapping[str, Any]], fields: Sequence[str] = GROUP_FIELDS
) -> dict[tuple[str, ...], list[Mapping[str, Any]]]:
    """Rows by `fields` (values as strings, as a CSV holds them)."""
    out: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        out[tuple(str(r.get(f, "")) for f in fields)].append(r)
    return dict(out)
