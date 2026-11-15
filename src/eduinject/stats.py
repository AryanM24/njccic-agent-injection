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
- `gee_fit` / `gee_contrast`: population-averaged logistic GEE with pair
  clusters (exchangeable + robust errors primary, independence + bias-reduced
  beside it; pending PI sign-off), over `long_rows`; `mixed_fit`, a pair
  random-intercept sensitivity model; `CONTRAST_FAMILY`, the Holm family
  (doc 11 §3.5). These need `statsmodels` (the optional `analysis` extra).
- `power_mde`: simulated power, the smallest detectable attack-minus-twin
  difference for a planned design.

Everything is deterministic under its seed. Nothing here contacts a model.
"""

import itertools
import random
import warnings
from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import NormalDist, mean, stdev
from typing import Any, Literal, NamedTuple


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
"""Fewest positive (and negative) runs for which a GEE or mixed fit reports."""

CONTRAST_FAMILY = (
    "arm",
    "isolated",
    "scope",
    "identity_mode",
    "defense",
    "handoff_mode",
    "gate",
    "model",
    "relay_stages",
)
"""The Holm family (doc 11 §3.5, pending PI sign-off): doc 10's primary
contrasts (isolation, scope, identity, defense) and the new arm contrasts
(attack vs twin, handoff mode, gate, model, relay depth), as the factor names
the fits take. Every other test is exploratory."""

REFERENCE = {"arm": "twin"}
"""Reference level per factor; any other factor's reference is its first
level in sorted order (False, `free_text`, 0)."""

GeeCov = Literal["exchangeable", "independence_bias_reduced"]
"""Exchangeable working correlation with robust errors is the primary fit;
independence with bias-reduced errors (doc 10 §5) is the sensitivity column.
Which is primary is pending PI sign-off (doc 11 §8 ruling 3)."""


class GeeTerm(NamedTuple):
    """One coefficient of a logistic fit: a level against its reference."""

    log_odds: float
    se: float
    p: float
    lo: float
    hi: float


class GeeFit(NamedTuple):
    """A pair-clustered logistic GEE; `terms` are named `factor=level`."""

    terms: dict[str, GeeTerm]
    n_groups: int
    cov: GeeCov


class MixedFit(NamedTuple):
    """Posterior (mean, sd) of each fixed effect of a pair random-intercept
    logistic model, named like `GeeFit.terms`."""

    terms: dict[str, tuple[float, float]]


class GeeResult(NamedTuple):
    """Log-odds contrast from a pair-clustered GEE."""

    log_odds: float
    se: float
    p: float
    n_pairs: int


def long_rows(
    rows: Sequence[Mapping[str, Any]], outcome_pair: tuple[str, str]
) -> list[dict[str, Any]]:
    """One row per run from rows that score both runs of a pair on one sample.

    `outcome_pair` is (attack metric, twin metric), e.g.
    ("paired_utility.harm_attack", "paired_utility.harm_twin"). Each scored row
    carrying both becomes two rows, `arm` "attack" and "twin", with the value
    under `score:<attack metric without "_attack">` (here
    `score:paired_utility.harm`) and every other field copied.
    """
    attack, twin = outcome_pair
    name = attack.removesuffix("_attack")
    out: list[dict[str, Any]] = []
    for row in _scored(_scored(rows, attack), twin):
        for arm, metric in (("attack", attack), ("twin", twin)):
            out.append({**row, "arm": arm, f"score:{name}": row[f"score:{metric}"]})
    return out


class _Design(NamedTuple):
    y: list[float]
    columns: list[list[float]]
    names: list[str]
    groups: list[str]


def _design(
    rows: Sequence[Mapping[str, Any]],
    outcome: str,
    factors: Sequence[str],
    group: str,
) -> _Design | None:
    """Treatment-coded main effects, or None when a fit would be meaningless.

    None with fewer than `MIN_GEE_EVENTS` events or non-events, or when any
    level of any factor has only events or only non-events: under that
    (quasi-)separation the estimate runs off to infinity and a robust p-value
    is meaningless (the first-edition recompute gave p≈0 for a single event).
    A factor with one level carries no contrast and is left out.
    """
    data = _scored(rows, outcome)
    y = [float(r[f"score:{outcome}"]) for r in data]
    if sum(y) < MIN_GEE_EVENTS or len(y) - sum(y) < MIN_GEE_EVENTS:
        return None
    columns: list[list[float]] = []
    names: list[str] = []
    for factor in factors:
        values = [r.get(factor) for r in data]
        ref = REFERENCE.get(factor)
        levels = sorted(set(values), key=lambda v: (v != ref, str(v)))
        for level in levels:
            hits = [v for v, x in zip(y, values, strict=True) if x == level]
            if sum(hits) in (0, len(hits)):
                return None
        for level in levels[1:]:
            columns.append([float(v == level) for v in values])
            names.append(f"{factor}={level}")
    return _Design(y, columns, names, [str(r[group]) for r in data])


def gee_fit(
    rows: Sequence[Mapping[str, Any]],
    outcome: str,
    factors: Sequence[str],
    group: str = "artifact_id",
    cov: GeeCov = "exchangeable",
) -> GeeFit | None:
    """Logistic GEE of `outcome` on main effects of `factors`, clustered by pair.

    `cov` "exchangeable" uses exchangeable working correlation and robust
    (sandwich) errors; "independence_bias_reduced" uses independence and the
    bias-reduced robust covariance, which suits few clusters (doc 10 §5).
    Returns None without statsmodels (the optional `analysis` extra), under
    separation or too few events (`_design`), or if the fit fails or is not
    finite: never a crash or a fake number (doc 11 §3.5).
    """
    if cov not in ("exchangeable", "independence_bias_reduced"):
        raise ValueError(
            f"cov must be exchangeable or independence_bias_reduced: {cov!r}"
        )
    try:
        import numpy as np
        import statsmodels.api as sm  # type: ignore[import-untyped]
        from statsmodels.tools.sm_exceptions import (  # type: ignore[import-untyped]
            PerfectSeparationError,
            PerfectSeparationWarning,
        )
    except ImportError:
        return None
    design = _design(rows, outcome, factors, group)
    if design is None or not design.names:
        return None
    exog = np.column_stack([np.ones(len(design.y)), *map(np.asarray, design.columns)])
    exchangeable = cov == "exchangeable"
    model = sm.GEE(
        np.asarray(design.y),
        exog,
        groups=np.asarray(design.groups),
        family=sm.families.Binomial(),
        cov_struct=sm.cov_struct.Exchangeable()
        if exchangeable
        else sm.cov_struct.Independence(),
    )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PerfectSeparationWarning)
            fit = model.fit(cov_type="robust" if exchangeable else "bias_reduced")
    except (
        PerfectSeparationError,
        PerfectSeparationWarning,
        ValueError,
        np.linalg.LinAlgError,
    ):
        return None
    ci = np.asarray(fit.conf_int())
    values = np.column_stack([fit.params, fit.bse, fit.pvalues, ci])
    if not np.isfinite(values).all():
        return None
    return GeeFit(
        terms={
            name: GeeTerm(*(float(v) for v in values[i + 1]))
            for i, name in enumerate(design.names)
        },
        n_groups=len(set(design.groups)),
        cov=cov,
    )


def mixed_fit(
    rows: Sequence[Mapping[str, Any]],
    outcome: str,
    factors: Sequence[str],
    group: str = "artifact_id",
) -> MixedFit | None:
    """Mixed-effects logistic sensitivity fit: a random intercept per pair.

    statsmodels' `BinomialBayesMixedGLM` fitted by variational Bayes
    (`fit_vb`). Its estimates are conditional on the pair, so they run larger
    than the GEE's population-averaged ones when pairs differ. None on the
    same conditions as `gee_fit`.
    """
    try:
        import numpy as np
        from scipy import sparse  # type: ignore[import-untyped]
        from statsmodels.genmod.bayes_mixed_glm import (  # type: ignore[import-untyped]
            BinomialBayesMixedGLM,
        )
    except ImportError:
        return None
    design = _design(rows, outcome, factors, group)
    if design is None or not design.names:
        return None
    n = len(design.y)
    exog = np.column_stack([np.ones(n), *map(np.asarray, design.columns)])
    index = {g: i for i, g in enumerate(sorted(set(design.groups)))}
    exog_vc = sparse.csr_matrix(
        (np.ones(n), (np.arange(n), [index[g] for g in design.groups])),
        shape=(n, len(index)),
    )
    model = BinomialBayesMixedGLM(
        np.asarray(design.y),
        exog,
        exog_vc,
        np.zeros(len(index), dtype=int),
    )
    try:
        result = model.fit_vb()
    except (ValueError, np.linalg.LinAlgError):
        return None
    means, sds = np.asarray(result.fe_mean), np.asarray(result.fe_sd)
    if not (np.isfinite(means).all() and np.isfinite(sds).all()):
        return None
    return MixedFit(
        {
            name: (float(means[i + 1]), float(sds[i + 1]))
            for i, name in enumerate(design.names)
        }
    )


def gee_contrast(
    rows_a: Sequence[Mapping[str, Any]],
    rows_b: Sequence[Mapping[str, Any]],
    metric: str,
) -> GeeResult | None:
    """Logistic GEE of `metric` on A-vs-B, clustered by pair.

    `gee_fit` with `factors=["arm"]`, A as "attack" and B as the "twin"
    reference, at the primary covariance. None when `gee_fit` gives none.
    """
    rows = [
        {**row, "arm": arm}
        for arm, side in (("attack", rows_a), ("twin", rows_b))
        for row in side
    ]
    fit = gee_fit(rows, metric, ["arm"])
    term = fit.terms.get("arm=attack") if fit else None
    if fit is None or term is None:
        return None
    return GeeResult(term.log_odds, term.se, term.p, fit.n_groups)


def power_mde(
    base_rate: float,
    n_pairs: int,
    epochs: int,
    *,
    alpha: float = 0.05,
    power: float = 0.8,
    n_sim: int = 500,
    seed: int = 0,
    step: float = 0.01,
) -> float | None:
    """Simulated minimum detectable attack-minus-twin difference.

    Each simulated pair runs `epochs` twin runs at `base_rate` and `epochs`
    attack runs at `base_rate + Δ`; the paired test is a two-sided z-test on
    the per-pair mean differences. Returns the smallest Δ on a `step` grid
    whose test rejects at `alpha` in at least `power` of `n_sim` draws, or None
    if no Δ up to 1 − `base_rate` does. The same uniforms are reused for every
    Δ, so the answer is deterministic under `seed` and power rises with Δ.
    `mde` stays as the analytic approximation; this is the reported power.
    """
    # shortcut: runs are independent within a pair (no pair random effect) and the
    # test is a z-test, not the sign-flip test; add an ICC if pilot data show one.
    import numpy as np

    if not 0 <= base_rate < 1 or n_pairs < 2 or epochs < 1 or step <= 0:
        raise ValueError("need 0 <= base_rate < 1, n_pairs >= 2, epochs >= 1, step > 0")
    rng = np.random.default_rng(seed)
    twin = (rng.random((n_sim, n_pairs, epochs)) < base_rate).mean(axis=2)
    u_attack = rng.random((n_sim, n_pairs, epochs))
    z = NormalDist().inv_cdf(1 - alpha / 2)
    k = 1
    while (delta := round(k * step, 10)) <= 1 - base_rate + 1e-12:
        d = (u_attack < base_rate + delta).mean(axis=2) - twin
        m, s = d.mean(axis=1), d.std(axis=1, ddof=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            reject = np.where(s > 0, np.abs(m) * n_pairs**0.5 / s > z, m != 0)
        if reject.mean() >= power:
            return delta
        k += 1
    return None
