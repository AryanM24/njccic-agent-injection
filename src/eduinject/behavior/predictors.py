"""Behaviour predictors and model profiles (A7, doc 11 §3.7).

Reads A4 feature rows (dicts as `feature_rows` returns them or as
`csv.DictReader` reads them back) and contacts no model. Only scored attack
runs (`label == "attack"`, `status == "ok"`, target defined) enter. Inputs are
`pre_outcome` columns only, checked by `features.role_of` on every call;
`artifact_id` is the cross-validation group and never a feature. Needs the
`analysis` extra (scikit-learn, numpy).
"""

import math
import random
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, NamedTuple, get_args

import numpy as np
from numpy.typing import NDArray
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.metrics import roc_auc_score  # type: ignore[import-untyped]
from sklearn.model_selection import (  # type: ignore[import-untyped]
    GroupKFold,
    LeaveOneGroupOut,
)
from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]
from sklearn.tree import (  # type: ignore[import-untyped]
    DecisionTreeClassifier,
    export_text,
)

from ..analysis import CELL_FIELDS, N_BOOT, percentiles
from ..features import role_of
from ..monitor.rules import RULES
from ..scorers.outcomes import CarryState
from ..stats import scenario_key
from .ladder import num
from .propagation_model import (
    GROUP_FIELDS,
    HALFLIFE_FIELDS,
    bootstrap_pairs,
    group_rows,
    is_on,
    scored_attacks,
    stage_order,
    stages_of,
    survival,
)

TARGETS = ("out:harm_completed", "carry:action", "beh:attempt", "state:adopt")
NOT_FEATURES = {
    "artifact_id": "CV group key",
    "base_id": "CV group key",
    "label": "constant over attack runs",
    "epoch": "epoch index",
}
"""Pre-outcome columns that are never predictors, with the reason."""
RESTRICTED_HEADER = (
    "RESTRICTED (Tier 1): do not publish; per-goal/channel/file-type content"
)
"""First line of every profile: predictors may name goal=, channel= or
file_type= levels, which the release policy keeps out of public outputs."""
APPENDIX_HEADER = "APPENDIX (doc 14 §9)"
"""Second line of every profile: profiles are not in the primary path."""
N_BINS = 10
TOP_PREDICTORS = 3

Model = Literal["l1", "tree"]
Scheme = Literal["group_kfold", "leave_one_base_out", "leave_one_model_out"]
GROUP_KEY: dict[str, str] = {
    "group_kfold": "artifact_id",
    "leave_one_base_out": "base_id",
    "leave_one_model_out": "model",
}
"""The column each scheme's folds are grouped on."""
SERVED_FIELDS = ("model", "host", "reasoning_effort")
"""The model as served: never an input under `leave_one_model_out`, where the
held-out model's level is unseen in training by construction."""
READER_FIELDS = ("reader_model", "reader_host")
"""The reader as served (doc 14 §5): dropped with `SERVED_FIELDS` for the same
reason."""
MODEL_SCALED = ("tokens_in:", "tokens_out:")
"""Token counts follow each model's tokenizer, so they fingerprint the model
and shift in scale between models: also dropped under `leave_one_model_out`."""
Matrix = NDArray[np.float64]


def _missing(value: Any) -> bool:
    """Empty, None, or a NaN (float or the CSV text "nan")."""
    if value in ("", None):
        return True
    return isinstance(value, float | str) and str(value).strip().lower() == "nan"


RULE_WORKFLOW: dict[str, str] = {
    rule.id: wf for wf, rules in RULES.items() for rule in rules
}
assert len(RULE_WORKFLOW) == sum(map(len, RULES.values())), "duplicate rule id"
"""Monitor rule id -> the workflow whose catalog defines it."""


def _rules(row: Mapping[str, Any]) -> list[str]:
    return [r for r in str(row.get("monitor:rules") or "").split(";") if r]


def _y(row: Mapping[str, Any], target: str) -> float:
    """The target's value on a run, NaN where undefined. A rule target is
    defined only on runs of the rule's own workflow: another workflow's run
    could never violate it, so it is not a negative."""
    if target.startswith("rule:"):
        rule = target.removeprefix("rule:")
        if rule not in RULE_WORKFLOW:
            raise ValueError(f"{target}: not a monitor rule id")
        if row.get("workflow") != RULE_WORKFLOW[rule]:
            return math.nan
        return float(rule in _rules(row))
    if target.startswith("carry:"):
        value = row.get(target)
        if value in ("", None):
            return math.nan
        if value not in get_args(CarryState):
            raise ValueError(f"{target}: unrecognised carry state {value!r}")
        return float(is_on(value))
    return num(row.get(target))


def _scored(rows: Sequence[Mapping[str, Any]], target: str) -> list[Mapping[str, Any]]:
    return [r for r in scored_attacks(rows) if not math.isnan(_y(r, target))]


def top_rule_targets(rows: Sequence[Mapping[str, Any]], n: int = 5) -> list[str]:
    """`rule:<id>` for the `n` rules violated in most scored attack runs
    (ties by id)."""
    counts = Counter(
        rule for r in _scored(rows, "out:harm_completed") for rule in set(_rules(r))
    )
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [f"rule:{rule}" for rule, _ in ranked[:n]]


def default_columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Every `pre_outcome` column the rows have, less `NOT_FEATURES`."""
    out = []
    for column in dict.fromkeys(c for r in rows for c in r):
        if column in NOT_FEATURES:
            continue
        try:
            if role_of(column) == "pre_outcome":
                out.append(column)
        except KeyError:
            pass
    return out


def _transferable(columns: Sequence[str]) -> list[str]:
    """`columns` less those that name the model as served or scale with it."""
    served = (*SERVED_FIELDS, *READER_FIELDS)
    return [c for c in columns if c not in served and not c.startswith(MODEL_SCALED)]


def _check(columns: Sequence[str]) -> None:
    bad = []
    for column in columns:
        role: str
        try:
            role = role_of(column)
        except KeyError:
            role = "unknown"
        if role != "pre_outcome":
            bad.append(f"{column} ({role})")
        elif column in NOT_FEATURES:
            bad.append(f"{column} ({NOT_FEATURES[column]})")
    if bad:
        raise ValueError(f"not admissible as predictors: {', '.join(bad)}")


def _encode(
    rows: Sequence[Mapping[str, Any]], columns: Sequence[str]
) -> tuple[Matrix, list[str], list[str]]:
    """Numeric columns as floats (NaN -> column median), anything else one-hot
    as `column=value` against its first level in sort order (for a carry
    column, `absent`); constant encoded columns dropped. Also returns each
    encoded column's source column."""
    blocks: list[NDArray[np.float64]] = []
    names: list[str] = []
    sources: list[str] = []
    for column in columns:
        values = [r.get(column) for r in rows]
        present = [v for v in values if not _missing(v)]
        nums = [num(v) for v in present]
        if present and not any(math.isnan(x) for x in nums):
            col = np.array([num(v) for v in values], dtype=float)
            col[np.isnan(col)] = float(np.median(nums))
            encoded = [(column, col)]
        else:
            encoded = [
                (
                    f"{column}={level}",
                    np.array([float(str(v) == level) for v in values]),
                )
                for level in sorted({str(v) for v in values})[1:]
            ]
        for name, col in encoded:
            if np.ptp(col) > 0:
                blocks.append(col)
                names.append(name)
                sources.append(column)
    x = np.column_stack(blocks) if blocks else np.empty((len(rows), 0))
    return x.astype(float), names, sources


def design_matrix(
    rows: Sequence[Mapping[str, Any]],
    target: str,
    columns: Sequence[str] | None = None,
) -> tuple[Matrix, Matrix, list[str]]:
    """`(X, y, feature names)` over the scored attack runs with `target` defined.

    Args:
        rows: Feature rows.
        target: `out:<outcome>`, `carry:<stage>` or `rule:<id>`.
        columns: Source columns; default `default_columns(rows)`.

    Raises:
        ValueError: A column is not `pre_outcome` (or is a group key), naming it.
    """
    columns = default_columns(rows) if columns is None else list(columns)
    _check(columns)
    scored = _scored(rows, target)
    x, names, _ = _encode(scored, columns)
    return x, np.array([_y(r, target) for r in scored]), names


def _estimator(model: Model, seed: int) -> Any:
    if model == "l1":
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(
                l1_ratio=1.0, solver="liblinear", C=1.0, random_state=seed
            ),
        )
    return DecisionTreeClassifier(max_depth=4, random_state=seed)


def _fit_predict(
    model: Model, x_tr: Matrix, y_tr: Matrix, x_te: Matrix, seed: int
) -> Matrix:
    """P(y = 1) on the test rows; the training prevalence when there is
    nothing to fit (no columns, or one class)."""
    if x_tr.shape[1] == 0 or len(np.unique(y_tr)) < 2:
        return np.full(len(x_te), float(y_tr.mean()))
    est = _estimator(model, seed).fit(x_tr, y_tr)
    return np.asarray(est.predict_proba(x_te)[:, 1], dtype=float)


class CvResult(NamedTuple):
    """Cross-validated discrimination and calibration.

    `auroc` is the mean fold AUROC, NaN when any fold has one class (a fold
    average over the folds that happen to be scoreable would be selected, not
    estimated); `fold_auroc` keeps each fold's. Brier and `calibration`
    (mean predicted, observed rate, n per non-empty decile bin) pool the
    out-of-fold predictions. The baselines: the same model and scheme on
    `CELL_FIELDS` only, and the training-fold prevalence. `fold_groups` names
    each fold's held-out group under a leave-one-out scheme (the model, for
    `leave_one_model_out`: does the predictor transfer to it?); empty under
    `group_kfold`, whose folds hold many pairs.
    """

    auroc: float
    brier: float
    calibration: list[tuple[float, float, int]]
    baseline_config_auroc: float
    baseline_prevalence_brier: float
    fold_auroc: list[float]
    fold_groups: list[str]


def _folds(groups: Sequence[str], scheme: Scheme) -> list[tuple[Matrix, Matrix]]:
    n = len(set(groups))
    if n < 2:
        return []
    splitter = (
        GroupKFold(n_splits=min(5, n))
        if scheme == "group_kfold"
        else LeaveOneGroupOut()
    )
    dummy = np.zeros((len(groups), 1))
    return list(splitter.split(dummy, groups=list(groups)))


def _oof(
    model: Model,
    x: Matrix,
    y: Matrix,
    folds: Sequence[tuple[Matrix, Matrix]],
    seed: int,
) -> tuple[Matrix, list[float]]:
    pred = np.full(len(y), math.nan)
    aurocs = []
    for tr, te in folds:
        pred[te] = _fit_predict(model, x[tr], y[tr], x[te], seed)
        one_class = len(np.unique(y[te])) < 2
        aurocs.append(math.nan if one_class else float(roc_auc_score(y[te], pred[te])))
    return pred, aurocs


def _mean_auroc(aurocs: Sequence[float]) -> float:
    if not aurocs or any(math.isnan(a) for a in aurocs):
        return math.nan
    return float(np.mean(aurocs))


def _calibration(pred: Matrix, y: Matrix) -> list[tuple[float, float, int]]:
    bins = np.minimum((pred * N_BINS).astype(int), N_BINS - 1)
    return [
        (float(pred[m].mean()), float(y[m].mean()), int(m.sum()))
        for b in range(N_BINS)
        if (m := bins == b).any()
    ]


def cross_validate(
    rows: Sequence[Mapping[str, Any]],
    target: str,
    model: Model,
    scheme: Scheme,
    seed: int = 0,
) -> CvResult:
    """Grouped cross-validation of one model on one target.

    Args:
        rows: Feature rows.
        target: As `design_matrix`.
        model: `l1` (L1 logistic, liblinear, C = 1, standardized inputs) or
            `tree` (depth ≤ 4).
        scheme: `group_kfold` (`GroupKFold(5)` on `artifact_id`),
            `leave_one_base_out` (`LeaveOneGroupOut` on `base_id`) or
            `leave_one_model_out` (`LeaveOneGroupOut` on `model`, with
            `SERVED_FIELDS` and `READER_FIELDS` dropped from the inputs and the
            config baseline,
            and the `MODEL_SCALED` token counts from the inputs).
        seed: Tree seed.

    Every metric is NaN when there are fewer than two groups.
    """
    scored = _scored(rows, target)
    lomo = scheme == "leave_one_model_out"
    columns = _transferable(default_columns(rows)) if lomo else default_columns(rows)
    x, y, _ = design_matrix(rows, target, columns)
    config = [c for c in CELL_FIELDS if any(c in r for r in scored)]
    config = _transferable(config) if lomo else config
    x_cfg, _, _ = _encode(scored, config)
    groups = [str(r.get(GROUP_KEY[scheme], "")) for r in scored]
    folds = _folds(groups, scheme)
    if not folds:
        return CvResult(math.nan, math.nan, [], math.nan, math.nan, [], [])
    pred, aurocs = _oof(model, x, y, folds, seed)
    _, cfg_aurocs = _oof(model, x_cfg, y, folds, seed)
    prevalence, _ = _oof(model, x[:, :0], y, folds, seed)
    return CvResult(
        auroc=_mean_auroc(aurocs),
        brier=float(np.mean((pred - y) ** 2)),
        calibration=_calibration(pred, y),
        baseline_config_auroc=_mean_auroc(cfg_aurocs),
        baseline_prevalence_brier=float(np.mean((prevalence - y) ** 2)),
        fold_auroc=aurocs,
        fold_groups=[]
        if scheme == "group_kfold"
        else [groups[int(te[0])] for _, te in folds],
    )


class Transfer(NamedTuple):
    """A predictor fitted on one set of runs and scored on another (doc 14 §5).

    The calibration line is a logistic regression of the test outcome on the
    logit of the prediction: an intercept shift alone leaves the slope at 1.
    `slope_lo`/`slope_hi` is its 95% interval over base-scenario resamples of
    the test set. Every field but `n_test` is NaN when the test or the training
    runs have one class.
    """

    auroc: float
    brier: float
    baseline_config_auroc: float
    calibration_intercept: float
    calibration_slope: float
    n_test: int
    slope_lo: float = math.nan
    slope_hi: float = math.nan


def _seen(
    columns: Sequence[str],
    train: Sequence[Mapping[str, Any]],
    test: Sequence[Mapping[str, Any]],
) -> list[str]:
    """`columns` less every categorical one with a test level absent from
    training (`split`, a new corpus digest): nothing was fitted for that level,
    and the reference level it would be scored as is arbitrary."""

    def levels(rows: Sequence[Mapping[str, Any]], column: str) -> set[str]:
        return {str(r.get(column)) for r in rows}

    def numeric(column: str) -> bool:
        values = [r.get(column) for r in (*train, *test)]
        return all(_missing(v) or not math.isnan(num(v)) for v in values)

    return [c for c in columns if numeric(c) or levels(test, c) <= levels(train, c)]


def _calibration_line(pred: Matrix, y: Matrix) -> tuple[float, float]:
    """(intercept, slope); NaN where the outcome or the prediction is constant."""
    if len(np.unique(y)) < 2 or np.ptp(pred) == 0:
        return math.nan, math.nan
    p = np.clip(pred, 1e-6, 1 - 1e-6)
    fit = LogisticRegression(C=np.inf).fit(np.log(p / (1 - p)).reshape(-1, 1), y)
    return float(fit.intercept_[0]), float(fit.coef_[0][0])


def transfer(
    train: Sequence[Mapping[str, Any]],
    test: Sequence[Mapping[str, Any]],
    target: str,
    model: Model = "l1",
    seed: int = 0,
    n_boot: int = N_BOOT,
) -> Transfer:
    """Fit on `train`, score on `test` (a model the fit never saw).

    Inputs are `default_columns` under the leave-one-model-out rule, less those
    `_seen` drops.

    Args:
        train: Feature rows of the dev models.
        test: Feature rows of the held-out model.
        target: As `design_matrix`.
        model: As `cross_validate`.
        seed: Tree and bootstrap seed.
        n_boot: Scenario resamples for the slope interval.
    """
    tr, te = _scored(train, target), _scored(test, target)
    rows = [*tr, *te]
    y_tr = np.array([_y(r, target) for r in tr])
    y_te = np.array([_y(r, target) for r in te])
    nan = math.nan
    if len(np.unique(y_tr)) < 2 or len(np.unique(y_te)) < 2:
        return Transfer(nan, nan, nan, nan, nan, len(te))

    def predict(columns: Sequence[str]) -> Matrix:
        columns = _seen(_transferable(columns), tr, te)
        _check(columns)
        x, _, _ = _encode(rows, columns)
        return _fit_predict(model, x[: len(tr)], y_tr, x[len(tr) :], seed)

    pred = predict(default_columns(rows))
    baseline = predict([c for c in CELL_FIELDS if any(c in r for r in rows)])
    intercept, slope = _calibration_line(pred, y_te)
    by_scenario: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(te):
        by_scenario[scenario_key(r)].append(i)
    keys = sorted(by_scenario)
    rng = random.Random(seed)
    slopes = []
    for _ in range(n_boot):
        idx = [i for k in rng.choices(keys, k=len(keys)) for i in by_scenario[k]]
        s = _calibration_line(pred[idx], y_te[idx])[1]
        slopes += [] if math.isnan(s) else [s]
    lo, hi = percentiles(slopes) if slopes else (nan, nan)
    return Transfer(
        auroc=float(roc_auc_score(y_te, pred)),
        brier=float(np.mean((pred - y_te) ** 2)),
        baseline_config_auroc=float(roc_auc_score(y_te, baseline)),
        calibration_intercept=intercept,
        calibration_slope=slope,
        n_test=len(te),
        slope_lo=lo,
        slope_hi=hi,
    )


class Coef(NamedTuple):
    """A standardized L1 coefficient (log-odds per SD) with its pair-bootstrap
    95% interval."""

    feature: str
    coef: float
    lo: float
    hi: float


class Explanation(NamedTuple):
    """`std_coefs` (L1 on standardized inputs, pair-bootstrap CIs), the
    depth-4 tree as text, and drop-column importance per source column: the
    pooled out-of-fold Brier (GroupKFold, L1) without the column minus with
    it, so positive means the column helps. Empty when the target has one
    class. `n_boot_kept` counts the bootstrap draws behind the CIs (a
    resample with one class is dropped)."""

    std_coefs: list[Coef]
    tree_text: str
    drop_column: dict[str, float]
    n: int
    n_boot_kept: int = 0


def explain(
    rows: Sequence[Mapping[str, Any]],
    target: str,
    n_boot: int = N_BOOT,
    seed: int = 0,
) -> Explanation:
    """Explain one target over the default columns (see `Explanation`)."""
    scored = _scored(rows, target)
    columns = default_columns(rows)
    _check(columns)
    x, names, sources = _encode(scored, columns)
    y = np.array([_y(r, target) for r in scored])
    if len(np.unique(y)) < 2 or not names:
        return Explanation([], "", {}, len(y))
    z = StandardScaler().fit_transform(x)

    def coefs(idx: Sequence[int]) -> Matrix | None:
        if len(np.unique(y[idx])) < 2:
            return None
        lr = LogisticRegression(l1_ratio=1.0, solver="liblinear", C=1.0)
        return np.asarray(lr.fit(z[idx], y[idx]).coef_[0], dtype=float)

    point = coefs(list(range(len(y))))
    assert point is not None
    by_pair: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(scored):
        by_pair[str(r["artifact_id"])].append(i)
    keys = sorted(by_pair)
    rng = random.Random(seed)
    draws = [
        d
        for _ in range(n_boot)
        if (d := coefs([i for k in rng.choices(keys, k=len(keys)) for i in by_pair[k]]))
        is not None
    ]
    std_coefs = []
    for j, name in enumerate(names):
        lo, hi = (
            percentiles([float(d[j]) for d in draws]) if draws else (math.nan, math.nan)
        )
        std_coefs.append(Coef(name, float(point[j]), lo, hi))
    tree = DecisionTreeClassifier(max_depth=4, random_state=seed).fit(x, y)
    folds = _folds([str(r["artifact_id"]) for r in scored], "group_kfold")
    drop: dict[str, float] = {}
    if folds:
        full, _ = _oof("l1", x, y, folds, seed)
        base = float(np.mean((full - y) ** 2))
        for source in dict.fromkeys(sources):
            keep = [j for j, s in enumerate(sources) if s != source]
            without, _ = _oof("l1", x[:, keep], y, folds, seed)
            drop[source] = float(np.mean((without - y) ** 2)) - base
    return Explanation(
        std_coefs, export_text(tree, feature_names=names), drop, len(y), len(draws)
    )


# --- profiles -----------------------------------------------------------------


class StageRate(NamedTuple):
    cell: str
    stage: str
    rate: float
    lo: float
    hi: float
    n: int


class HalfLife(NamedTuple):
    cell: str
    family: str
    half_life: float
    lo: float
    hi: float
    n: int
    kept: int


class RuleRate(NamedTuple):
    """How often `rule` is violated in one cell's runs, and where it originated
    in the runs whose first violation it was (`origin_k` of `origin_m`)."""

    cell: str
    rule: str
    rate: float
    lo: float
    hi: float
    n: int
    origin_stage: str
    origin_k: int
    origin_m: int


class Predictor(NamedTuple):
    target: str
    feature: str
    coef: float
    lo: float
    hi: float


class ProfileStats(NamedTuple):
    """Everything a profile states; every quantity is an estimate with a CI."""

    carry: list[StageRate]
    half_lives: list[HalfLife]
    rules: list[RuleRate]
    predictors: list[Predictor]


def _cells(
    rows: Sequence[Mapping[str, Any]], fields: Sequence[str]
) -> dict[str, list[Mapping[str, Any]]]:
    """Rows by `fields` (A6's grouping), each labelled by the fields that vary
    across `rows` ("all runs" when none do)."""
    varying = [f for f in fields if len({str(r.get(f, "")) for r in rows}) > 1]
    out: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for key, group in group_rows(rows, fields).items():
        cell = dict(zip(fields, key))
        label = ", ".join(f"{f}={cell[f]}" for f in varying) or "all runs"
        out[label] += group
    return dict(sorted(out.items()))


def _carried_at(stage: str) -> Callable[[Mapping[str, Any]], bool]:
    return lambda r: is_on(r[f"carry:{stage}"])


def _violated(rule: str) -> Callable[[Mapping[str, Any]], bool]:
    return lambda r: rule in _rules(r)


def _rate(
    rows: Sequence[Mapping[str, Any]],
    hit: Callable[[Mapping[str, Any]], bool],
    n_boot: int,
    seed: int,
) -> tuple[float, float, float]:
    def stat(chosen: list[Mapping[str, Any]]) -> float:
        return sum(map(hit, chosen)) / len(chosen) if chosen else math.nan

    ci = bootstrap_pairs(rows, stat, n_boot, seed)
    return stat(list(rows)), ci.lo, ci.hi


def profile_stats(
    rows: Sequence[Mapping[str, Any]],
    n_rules: int = 5,
    n_boot: int = N_BOOT,
    seed: int = 0,
) -> ProfileStats:
    """`ProfileStats` for one model's feature rows. Carry rates are per A6 cell
    (`GROUP_FIELDS`), rule rates per cell over the rule's own workflow's runs,
    and half-lives per `HALFLIFE_FIELDS`, never pooled across conditions;
    predictors pool the model's rows (they see the cell fields as inputs)."""
    attacks = _scored(rows, "out:harm_completed")
    carry, half_lives = [], []
    for cell, cell_rows in _cells(attacks, GROUP_FIELDS).items():
        stages = sorted({s for r in cell_rows for s in stages_of(r)}, key=stage_order)
        for stage in stages:
            at = [r for r in cell_rows if r.get(f"carry:{stage}") not in ("", None)]
            rate, lo, hi = _rate(at, _carried_at(stage), n_boot, seed)
            carry.append(StageRate(cell, stage, rate, lo, hi, len(at)))
    for cell, cell_rows in _cells(attacks, HALFLIFE_FIELDS).items():
        for family, column in (("marker", "carry"), ("warning", "flag")):
            fit = survival(cell_rows, column, n_boot, seed)
            if fit.n:
                half_lives.append(
                    HalfLife(
                        cell, family, fit.half_life, fit.lo, fit.hi, fit.n, fit.kept
                    )
                )
    rules = []
    for target in top_rule_targets(rows, n_rules):
        rule = target.removeprefix("rule:")
        own = _scored(attacks, target)
        for cell, cell_rows in _cells(own, GROUP_FIELDS).items():
            rate, lo, hi = _rate(cell_rows, _violated(rule), n_boot, seed)
            origins = Counter(
                str(r.get("monitor:origin_stage") or "unknown")
                for r in cell_rows
                if r.get("monitor:first") == rule
            )
            stage, k = origins.most_common(1)[0] if origins else ("", 0)
            m = sum(origins.values())
            rules.append(
                RuleRate(cell, rule, rate, lo, hi, len(cell_rows), stage, k, m)
            )
    predictors = []
    for target in (*TARGETS, *top_rule_targets(rows, n_rules)):
        expl = explain(rows, target, n_boot, seed)
        retained = [c for c in expl.std_coefs if c.coef != 0]
        retained.sort(key=lambda c: (-abs(c.coef), c.feature))
        predictors += [
            Predictor(target, c.feature, c.coef, c.lo, c.hi)
            for c in retained[:TOP_PREDICTORS]
        ]
    return ProfileStats(carry, half_lives, rules, predictors)


TEMPLATES = {
    "restricted": RESTRICTED_HEADER,
    "appendix": APPENDIX_HEADER,
    "title": "# Behaviour profile: {model}",
    "heading": "## {heading}",
    "carry": "- {cell}: carry at {stage} {rate} (95% CI {lo} to {hi}; n = {n} attack runs).",
    "half_life": "- {cell}: {family} half-life {value} stages (95% CI {lo} to {hi} from {kept} bootstrap draws; n = {n} runs at risk).",
    "rule": "- {cell}: rule {rule} violated in {rate} of attack runs (95% CI {lo} to {hi}; n = {n}); first violation originating at {stage} in {k} of {m}.",
    "rule_never_first": "- {cell}: rule {rule} violated in {rate} of attack runs (95% CI {lo} to {hi}; n = {n}); never the first violation.",
    "predictor": "- {target}: {feature} {direction} the odds (standardized coefficient {coef}, 95% CI {lo} to {hi}).",
    "none": "- No estimate.",
}
"""The only sentences a profile may contain."""
HEADINGS = (
    "Carry rate per stage",
    "Half-lives",
    "Most-violated rules",
    "Top predictors",
)
LINE_PATTERNS = [
    re.compile(re.sub(r"\\\{[a-z_]+\\\}", lambda _: ".+", re.escape(t)))
    for t in TEMPLATES.values()
]
"""Each template as a full-line regex (placeholders match any text)."""


def _fmt(x: float) -> str:
    return "nan" if math.isnan(x) else "inf" if math.isinf(x) else f"{x:.3f}"


def write_profile(model_label: str, stats: ProfileStats, path: Path) -> None:
    """Render a model profile from `TEMPLATES` only (doc 11 §3.7)."""
    t = TEMPLATES
    lines = [t["restricted"], t["appendix"], t["title"].format(model=model_label)]
    sections: list[list[str]] = [
        [
            t["carry"].format(
                cell=s.cell,
                stage=s.stage,
                rate=_fmt(s.rate),
                lo=_fmt(s.lo),
                hi=_fmt(s.hi),
                n=s.n,
            )
            for s in stats.carry
        ],
        [
            t["half_life"].format(
                cell=h.cell,
                family=h.family,
                value=_fmt(h.half_life),
                lo=_fmt(h.lo),
                hi=_fmt(h.hi),
                n=h.n,
                kept=h.kept,
            )
            for h in stats.half_lives
        ],
        [
            t["rule" if r.origin_m else "rule_never_first"].format(
                cell=r.cell,
                rule=r.rule,
                rate=_fmt(r.rate),
                lo=_fmt(r.lo),
                hi=_fmt(r.hi),
                n=r.n,
                stage=r.origin_stage,
                k=r.origin_k,
                m=r.origin_m,
            )
            for r in stats.rules
        ],
        [
            t["predictor"].format(
                target=p.target,
                feature=p.feature,
                direction="raises" if p.coef > 0 else "lowers",
                coef=_fmt(p.coef),
                lo=_fmt(p.lo),
                hi=_fmt(p.hi),
            )
            for p in stats.predictors
        ],
    ]
    for heading, body in zip(HEADINGS, sections):
        lines += ["", t["heading"].format(heading=heading), *(body or [t["none"]])]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
