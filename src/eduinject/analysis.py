"""Turn finished eval logs into the tables doc 04 §13 requires.

Everything here runs after the fact, over logs, and contacts no model. The
procedure it implements is proposed in `docs/design/09_analysis_plan.md`; that
plan is a draft until signed, and where it leaves a choice open (the null rule's
noise-floor statistic) the code reports both candidates rather than picking.

The unit is the *pair* (`artifact_id`), never the run: the ten epochs of one
pair are not independent evidence, so every interval resamples whole pairs.
"""

import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from statistics import mean, pstdev
from typing import Any, NamedTuple

from eduinject.scorers import RUNS_KEY

CELL_FIELDS: tuple[str, ...] = (
    "model",
    "host",
    "reasoning_effort",
    "workflow",
    "corpus",
    "benign_only",
    "controls",
    "scope",
    "isolated",
)
"""Fields that identify one experimental condition. Rows that differ in any of
these are never pooled."""

REPORTABILITY: dict[str, str] = {
    "propagation": "M1 (verbatim) only; depth provisional (D1, D2)",
    "exfiltration": "reportable as a lower bound (07, 08)",
    "authorization": "reportable as a lower bound (08)",
    "scope_violation": "reportable",
    "action_divergence": "proxy for A3, not the specified magnitude (D5)",
    "suppression": "recorded, NOT reportable (D6)",
    "control_check": "reportable (08 §6)",
}
"""What each scorer's numbers may be used for, keyed by scorer name."""


class RateCI(NamedTuple):
    """A rate over runs with a pair-clustered bootstrap interval."""

    n_pairs: int
    n_runs: int
    rate: float
    lo: float
    hi: float


class EpochSpread(NamedTuple):
    """How much a cell's rate moves between epochs: the noise-floor candidates."""

    epoch_rates: tuple[float, ...]
    sd: float
    range: float


class Difference(NamedTuple):
    """Paired difference between two cells, over the pairs both contain."""

    n_pairs: int
    diff: float
    lo: float
    hi: float


def provider_host(model_args: dict[str, Any] | None) -> str:
    """The pinned upstream host recorded in a task's model_args, or ''."""
    provider = (model_args or {}).get("provider") or {}
    hosts = provider.get("order") or provider.get("only") or []
    return ",".join(str(h) for h in hosts)


def flatten_scores(scores: dict[str, Any]) -> dict[str, float]:
    """Flatten score values to `scorer` / `scorer.key` -> float.

    Non-numeric or missing values are dropped rather than coerced, so an
    inapplicable score never counts as a zero.
    """
    flat: dict[str, float] = {}
    for name, value in scores.items():
        if isinstance(value, dict):
            for key, inner in value.items():
                if isinstance(inner, int | float) and not isinstance(inner, bool):
                    flat[f"{name}.{key}"] = float(inner)
        elif isinstance(value, int | float) and not isinstance(value, bool):
            flat[name] = float(value)
    return flat


def rows_from_log(log: Any) -> list[dict[str, Any]]:
    """One row per (sample, epoch) of an Inspect `EvalLog`.

    A row records its cell (`CELL_FIELDS`), its pair and corpus coordinates,
    its status (`scored`, `error` or `limit`), and every numeric score under
    `score:<name>`. Errored and limit-hit runs keep their row so they can be
    counted (doc 04 §13.5); they simply carry no scores.
    """
    meta = log.eval.metadata or {}
    cell = {
        "model": meta.get("model") or str(log.eval.model),
        "host": provider_host(meta.get("model_args")),
        "reasoning_effort": meta.get("reasoning_effort"),
        "workflow": meta.get("workflow"),
        "corpus": meta.get("corpus"),
        "benign_only": bool(meta.get("benign_only")),
        "controls": bool(meta.get("controls")),
        "scope": meta.get("scope"),
        "isolated": bool(meta.get("isolated")),
    }
    rows: list[dict[str, Any]] = []
    for sample in log.samples or []:
        smeta = sample.metadata or {}
        if sample.error is not None:
            status, detail = "error", str(sample.error.message).splitlines()[0]
        elif sample.limit is not None:
            status, detail = "limit", str(sample.limit.type)
        else:
            status, detail = "scored", ""
        row: dict[str, Any] = {
            **cell,
            "config_hash": meta.get("config_hash"),
            "log": log.location,
            "created": log.eval.created,
            "sample_id": sample.id,
            "artifact_id": smeta.get("artifact_id", sample.id),
            "base_id": smeta.get("base_id"),
            "goal": smeta.get("goal"),
            "file_type": smeta.get("file_type"),
            "channel": smeta.get("concealment"),
            "epoch": sample.epoch,
            "status": status,
            "status_detail": detail,
        }
        # How many tool calls each recorded run made (lookups included), so a
        # pipeline whose action stage never calls a tool can be told from one
        # that was safe (`tool_use_check`).
        runs = smeta.get(RUNS_KEY) or {}
        for label in ("attack", "twin"):
            ledger = (runs.get(label) or {}).get("ledger") or {}
            if "calls" in ledger:
                row[f"tool_calls:{label}"] = len(ledger["calls"])
        if status == "scored":
            values = {k: v.value for k, v in (sample.scores or {}).items()}
            for name, value in flatten_scores(values).items():
                row[f"score:{name}"] = value
        rows.append(row)
    return rows


def load_rows(log_dirs: Sequence[str]) -> tuple[list[dict[str, Any]], int]:
    """Read every eduinject log under `log_dirs` (local, file:// or s3://).

    A retried eval set can leave the same (config, sample, epoch) in more than
    one log. The row from the most recently created log wins.

    Returns:
        The rows, and how many duplicate rows were dropped.
    """
    from inspect_ai.log import list_eval_logs, read_eval_log

    rows: list[dict[str, Any]] = []
    for log_dir in log_dirs:
        for info in list_eval_logs(log_dir, recursive=True):
            log = read_eval_log(info)
            if str(log.eval.task).split("/")[-1].startswith("eduinject"):
                rows.extend(rows_from_log(log))
    return dedupe(rows)


def dedupe(rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Keep one row per (config_hash, sample_id, epoch): the newest log's."""
    best: dict[tuple[Any, ...], dict[str, Any]] = {}
    total = 0
    for row in rows:
        total += 1
        key = (row["config_hash"], row["sample_id"], row["epoch"])
        if key not in best or str(row["created"]) > str(best[key]["created"]):
            best[key] = row
    return list(best.values()), total - len(best)


def cell_of(row: dict[str, Any], extra: Sequence[str] = ()) -> tuple[Any, ...]:
    """The grouping key of a row: its cell, plus any `extra` fields."""
    return tuple(row.get(f) for f in (*CELL_FIELDS, *extra))


def group(
    rows: Iterable[dict[str, Any]], extra: Sequence[str] = ()
) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    """Group rows by cell (plus `extra` fields, e.g. `base_id`)."""
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[cell_of(row, extra)].append(row)
    return dict(groups)


def denominators(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    """Count runs by status, for the exclusion line of every table (§13.5)."""
    counts = {"total": len(rows), "scored": 0, "error": 0, "limit": 0}
    for row in rows:
        counts[row["status"]] += 1
    return counts


def tool_use_check(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    """Count scored runs that made no tool call at all.

    A pipeline whose action stage never calls a tool has not been tested, and it
    looks perfectly safe: no leak, no overstep, no action. Zero calls across a
    whole run (lookups included) means the model is not issuing tool calls on this
    route, which is a setup fault and not a result (RUNNING.md step 4, check 2).
    Rows from logs that predate the ledger field are not counted either way.
    """
    with_ledger = 0
    silent = 0
    for row in rows:
        if row["status"] != "scored":
            continue
        counts = [v for k, v in row.items() if k.startswith("tool_calls:")]
        if counts:
            with_ledger += 1
            silent += all(v == 0 for v in counts)
    return {"scored_with_ledger": with_ledger, "no_tool_calls": silent}


def metrics_in(rows: Iterable[dict[str, Any]]) -> list[str]:
    """Every score name present in `rows`, sorted."""
    names = {k[len("score:") :] for row in rows for k in row if k.startswith("score:")}
    return sorted(names)


def _by_pair(rows: Iterable[dict[str, Any]], metric: str) -> dict[Any, list[float]]:
    pairs: dict[Any, list[float]] = defaultdict(list)
    for row in rows:
        value = row.get(f"score:{metric}")
        if row["status"] == "scored" and value is not None:
            pairs[row["artifact_id"]].append(float(value))
    return dict(pairs)


def _percentiles(
    values: list[float], lo: float = 2.5, hi: float = 97.5
) -> tuple[float, float]:
    ordered = sorted(values)
    last = len(ordered) - 1

    def at(q: float) -> float:
        return ordered[round(q / 100 * last)]

    return at(lo), at(hi)


def _bootstrap(
    keys: list[Any], statistic: Callable[[list[Any]], float], n_boot: int, seed: int
) -> tuple[float, float]:
    rng = random.Random(seed)
    draws = [statistic(rng.choices(keys, k=len(keys))) for _ in range(n_boot)]
    return _percentiles(draws)


def rate_with_ci(
    rows: Sequence[dict[str, Any]], metric: str, n_boot: int = 2000, seed: int = 0
) -> RateCI | None:
    """Mean of `metric` over scored runs, with a 95% pair-clustered interval.

    Resamples whole pairs with replacement, so a pair's ten correlated epochs
    move together. Returns None when no scored run carries the metric.
    """
    pairs = _by_pair(rows, metric)
    if not pairs:
        return None
    keys = list(pairs)
    sums = {k: sum(v) for k, v in pairs.items()}
    counts = {k: len(v) for k, v in pairs.items()}

    def pooled(chosen: list[Any]) -> float:
        return sum(sums[k] for k in chosen) / sum(counts[k] for k in chosen)

    lo, hi = _bootstrap(keys, pooled, n_boot, seed)
    n_runs = sum(counts.values())
    return RateCI(len(keys), n_runs, pooled(keys), lo, hi)


def epoch_spread(rows: Sequence[dict[str, Any]], metric: str) -> EpochSpread | None:
    """Rate of `metric` per epoch, and its SD and range across epochs.

    On a benign-only cell this is the run-to-run variation doc 04 §13.4 sets as
    the floor below which an effect is reported as null. Needs two epochs.
    """
    by_epoch: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        value = row.get(f"score:{metric}")
        if row["status"] == "scored" and value is not None:
            by_epoch[int(row["epoch"])].append(float(value))
    if len(by_epoch) < 2:
        return None
    rates = tuple(mean(by_epoch[e]) for e in sorted(by_epoch))
    return EpochSpread(rates, pstdev(rates), max(rates) - min(rates))


def paired_difference(
    rows_a: Sequence[dict[str, Any]],
    rows_b: Sequence[dict[str, Any]],
    metric: str,
    n_boot: int = 2000,
    seed: int = 0,
) -> Difference | None:
    """Rate of `metric` in A minus B, over pairs present in both, with a CI.

    Each pair contributes its own A-minus-B difference, and the bootstrap
    resamples pairs, so the comparison is within-document (e.g. the same
    resume isolated vs not). Returns None when no pair is shared.
    """
    a, b = _by_pair(rows_a, metric), _by_pair(rows_b, metric)
    shared = sorted(set(a) & set(b), key=str)
    if not shared:
        return None
    per_pair = {k: mean(a[k]) - mean(b[k]) for k in shared}

    def avg(chosen: list[Any]) -> float:
        return sum(per_pair[k] for k in chosen) / len(chosen)

    lo, hi = _bootstrap(shared, avg, n_boot, seed)
    return Difference(len(shared), avg(shared), lo, hi)


def saturated(ci: RateCI) -> bool:
    """A rate at exactly 0 or 1 says nothing about ordering (doc 04 §14)."""
    return ci.rate in (0.0, 1.0)


def is_null(diff: Difference, floor: float | None) -> bool | None:
    """Doc 04 §13.4: an effect no larger than the benign floor is null.

    Returns None when there is no floor to compare against (no benign-only
    cell for the same model, workflow, scope and isolation).
    """
    if floor is None:
        return None
    return abs(diff.diff) <= floor


def stratified_sample(
    rows: Sequence[dict[str, Any]], fraction: float = 0.10, seed: int = 0
) -> list[dict[str, Any]]:
    """Draw `fraction` of scored runs from every cell, at least one per cell.

    Doc 04 §13.2: sampled deliberately across all conditions, not at random
    overall, so every condition is checked.
    """
    if not 0 < fraction <= 1:
        raise ValueError(f"fraction must be in (0, 1], got {fraction}")
    rng = random.Random(seed)
    chosen: list[dict[str, Any]] = []
    groups = group(rows)
    for key in sorted(groups, key=str):
        scored = [r for r in groups[key] if r["status"] == "scored"]
        if scored:
            k = max(1, round(len(scored) * fraction))
            chosen.extend(rng.sample(scored, k))
    return chosen


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    """Agreement between two coders beyond chance (doc 04 §13.2).

    Raises:
        ValueError: If the codings differ in length or are empty.
    """
    if len(a) != len(b) or not a:
        raise ValueError("codings must be non-empty and of equal length")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    labels = set(a) | set(b)
    expected = sum((a.count(lab) / n) * (b.count(lab) / n) for lab in labels)
    if expected == 1:
        return 1.0
    return (observed - expected) / (1 - expected)
