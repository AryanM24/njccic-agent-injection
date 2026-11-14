"""Second-edition statistics (doc 10 §5), over the rows `analysis.load_rows` reads.

The first edition reported a pair-clustered bootstrap interval and a null rule
(an effect at or below the benign epoch range is null). The external review
pointed out that the rule is a conservative *detection* rule, not a test. These
functions add what a reader expects next to it, all still clustered by pair:

- `sign_flip_test`: a paired permutation test of a contrast (each pair's
  A-minus-B difference keeps or flips its sign).
- `holm`: Holm's step-down correction across the pre-declared primary tests.
- `zero_upper_bound`: the exact one-sided 95% upper bound for a cell with no
  events, so "0" is reported as "below x" rather than as proof of absence.
- `mde`: the smallest paired difference the design could detect, so a null
  says how large an effect it rules out.
- `pair_concentration`: how many distinct pairs produce a harm total.
- `conditional_rate`: P(harm | upstream propagation), the action conditional on
  transmission.
- `gee_contrast`: a population-averaged logistic GEE with pair clusters
  (independence working correlation, bias-reduced robust errors), the
  regression sensitivity analysis, if `statsmodels` is installed (the optional
  `analysis` extra).

Everything is deterministic under its seed. Nothing here contacts a model.
"""

import itertools
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import NormalDist, mean, stdev
from typing import Any, NamedTuple


def _scored(rows: Sequence[Mapping[str, Any]], metric: str) -> list[Mapping[str, Any]]:
    key = f"score:{metric}"
    return [r for r in rows if r["status"] == "scored" and r.get(key) is not None]


def per_pair_means(rows: Sequence[Mapping[str, Any]], metric: str) -> dict[Any, float]:
    """Mean of `metric` over each pair's scored epochs."""
    by_pair: dict[Any, list[float]] = defaultdict(list)
    for row in _scored(rows, metric):
        by_pair[row["artifact_id"]].append(float(row[f"score:{metric}"]))
    return {k: mean(v) for k, v in by_pair.items()}


def paired_differences(
    rows_a: Sequence[Mapping[str, Any]],
    rows_b: Sequence[Mapping[str, Any]],
    metric: str,
) -> list[float]:
    """Per-pair A-minus-B differences over the pairs both cells contain."""
    a, b = per_pair_means(rows_a, metric), per_pair_means(rows_b, metric)
    return [a[k] - b[k] for k in sorted(set(a) & set(b), key=str)]


def sign_flip_test(
    diffs: Sequence[float], n_perm: int = 10_000, seed: int = 0
) -> float:
    """Two-sided paired permutation p-value for mean(diffs) != 0.

    Under the null, each pair's difference is as likely to be negative as
    positive. Up to 16 non-zero pairs, every sign pattern is enumerated
    (exact); beyond that, `n_perm` random patterns are drawn. Pairs with a zero
    difference carry no information and are dropped.

    Returns:
        The p-value, or 1.0 when no pair differs.
    """
    nonzero = [d for d in diffs if d != 0]
    if not nonzero:
        return 1.0
    observed = abs(sum(nonzero))

    def count(patterns: Any) -> int:
        return sum(
            abs(sum(s * d for s, d in zip(signs, nonzero, strict=True)))
            >= observed - 1e-12
            for signs in patterns
        )

    if len(nonzero) <= 16:
        return count(itertools.product((1, -1), repeat=len(nonzero))) / 2 ** len(
            nonzero
        )
    rng = random.Random(seed)
    drawn = ([rng.choice((1, -1)) for _ in nonzero] for _ in range(n_perm))
    # The observed pattern counts as one draw, so a Monte Carlo p is never 0.
    return (count(drawn) + 1) / (n_perm + 1)


def holm(pvalues: Mapping[str, float]) -> dict[str, float]:
    """Holm-adjusted p-values (family-wise error control, any dependence)."""
    ordered = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for i, (name, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - i) * p))
        adjusted[name] = running
    return adjusted


def zero_upper_bound(n: int, confidence: float = 0.95) -> float:
    """Exact one-sided upper bound on a rate after 0 events in `n` trials.

    Pass the number of *pairs*, not runs: epochs of one pair are correlated, so
    the pair count is the conservative effective sample size. About 3/n for
    95% (the "rule of three").
    """
    if n <= 0:
        raise ValueError("n must be positive")
    return 1 - (1 - confidence) ** (1 / n)


def mde(
    diffs: Sequence[float], alpha: float = 0.05, power: float = 0.80
) -> float | None:
    """Minimum detectable mean paired difference for this many pairs.

    Normal approximation, (z_{1-α/2} + z_{power}) · sd / √n, with sd the
    standard deviation of the per-pair differences (from a baseline or pilot
    when planning, from the data when reporting). Returns None below two pairs.
    """
    if len(diffs) < 2:
        return None
    z = NormalDist().inv_cdf(1 - alpha / 2) + NormalDist().inv_cdf(power)
    return z * stdev(diffs) / len(diffs) ** 0.5


class Concentration(NamedTuple):
    """How a cell's positive runs are spread over pairs."""

    positive_runs: int
    pairs: int
    pairs_with_any: int
    top_pair_share: float
    """Share of positive runs that come from the single most-positive pair."""
    per_pair: dict[Any, int]


def pair_concentration(rows: Sequence[Mapping[str, Any]], metric: str) -> Concentration:
    """Count positive runs per pair, so one artifact cannot pass for a trend."""
    per_pair: dict[Any, int] = defaultdict(int)
    for row in _scored(rows, metric):
        per_pair[row["artifact_id"]] += int(float(row[f"score:{metric}"]) > 0)
    positive = sum(per_pair.values())
    return Concentration(
        positive_runs=positive,
        pairs=len(per_pair),
        pairs_with_any=sum(1 for v in per_pair.values() if v),
        top_pair_share=max(per_pair.values(), default=0) / positive
        if positive
        else 0.0,
        per_pair=dict(per_pair),
    )


class Conditional(NamedTuple):
    """P(outcome | given) over runs where `given` fired."""

    n_given: int
    rate: float | None


def conditional_rate(
    rows: Sequence[Mapping[str, Any]], outcome: str, given: str, when: bool = True
) -> Conditional:
    """Rate of `outcome` among scored runs where `given` is positive (or, with
    `when=False`, where it is zero).

    E.g. outcome="authorization", given="propagation.analysis": how often an
    unauthorized action followed once the marker crossed into the assessment.
    With `when=False` and outcome="action_divergence" at `isolated=True` it is
    the laundering-candidate rate: the action changed although the marker never
    reached the only text the action stage saw (doc 10 §9).
    """
    hits = [
        float(r[f"score:{outcome}"])
        for r in _scored(_scored(rows, given), outcome)
        if (float(r[f"score:{given}"]) > 0) is when
    ]
    return Conditional(len(hits), mean(hits) if hits else None)


MIN_GEE_EVENTS = 5
"""Fewest positive (and negative) runs for which `gee_contrast` reports."""


class GeeResult(NamedTuple):
    """Log-odds contrast from a pair-clustered GEE."""

    log_odds: float
    se: float
    p: float
    n_pairs: int


def gee_contrast(
    rows_a: Sequence[Mapping[str, Any]],
    rows_b: Sequence[Mapping[str, Any]],
    metric: str,
) -> GeeResult | None:
    """Logistic GEE of `metric` on A-vs-B, clustered by pair.

    The sensitivity analysis for the primary bootstrap contrast (doc 10 §5).
    Uses a bias-reduced robust covariance when statsmodels offers it, since
    the number of pairs is small. Returns None when statsmodels is not
    installed, or when the data are (nearly) separated: an arm with no events or
    only events, or fewer than `MIN_GEE_EVENTS` events or non-events overall.
    """
    try:
        import numpy as np
        import statsmodels.api as sm  # type: ignore[import-untyped]
    except ImportError:
        return None
    y, x, groups = [], [], []
    for flag, rows in ((1.0, rows_a), (0.0, rows_b)):
        for row in _scored(rows, metric):
            y.append(float(row[f"score:{metric}"]))
            x.append(flag)
            groups.append(str(row["artifact_id"]))
    arm_a = [v for v, flag in zip(y, x, strict=True) if flag]
    arm_b = [v for v, flag in zip(y, x, strict=True) if not flag]
    # With (near-)separation -- an arm with no events, or only a handful in all
    # -- the logistic estimate runs off to infinity and the robust p-value is
    # meaningless (the first-edition recompute gave p≈0 for a single event).
    if not arm_a or not arm_b:
        return None
    if any(sum(arm) in (0, len(arm)) for arm in (arm_a, arm_b)):
        return None
    if sum(y) < MIN_GEE_EVENTS or len(y) - sum(y) < MIN_GEE_EVENTS:
        return None
    design = sm.add_constant(np.asarray(x))
    model = sm.GEE(
        np.asarray(y),
        design,
        groups=np.asarray(groups),
        family=sm.families.Binomial(),
        # With about 50 clusters, independence working correlation plus a
        # bias-corrected robust covariance is the safer choice (Thompson et al.
        # 2021); it is consistent whatever the true within-pair correlation.
        cov_struct=sm.cov_struct.Independence(),
    )
    try:
        fit = model.fit(cov_type="bias_reduced")
    except (TypeError, ValueError):
        fit = model.fit()
    if not np.isfinite(fit.pvalues[1]):
        return None
    return GeeResult(
        log_odds=float(fit.params[1]),
        se=float(fit.bse[1]),
        p=float(fit.pvalues[1]),
        n_pairs=len(set(groups)),
    )
