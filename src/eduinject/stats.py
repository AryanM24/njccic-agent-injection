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
  (doc 11 §3.5); `MixedFit.variance`, the latent-scale variance partition
  (model vs other factors vs pair vs run). These need `statsmodels` (the
  optional `analysis` extra).
- `power_mde`: simulated power, the smallest detectable attack-minus-twin
  difference for a planned design.

Everything is deterministic under its seed. Nothing here contacts a model.
"""

import itertools
import math
import random
import warnings
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
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

REFERENCE: dict[str, Any] = {
    "arm": "twin",
    "identity_mode": "off",
    "defense": "none",
    "scope": "read_write",
    "handoff_mode": "free_text",
    "gate": False,
    "relay_stages": 0,
    "isolated": False,
}
"""Each factor's reference level: the undefended or baseline setting, so a term
reads as "this level against the plain pipeline". `model` has none: its
reference is the alphabetically first model level (doc 11 §3.5). A factor
whose reference is absent from the data falls back to its first level in
`factor_levels` order."""

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


class SeparatedLevel(NamedTuple):
    """A factor level with only events or only non-events, left out of a fit.

    `bound` is the exact one-sided 95% bound on its rate over `n_pairs`
    (`zero_upper_bound`): an upper bound when `events` is 0, a lower bound
    (1 − bound) when every run is an event. `other_*` count the rest of the
    factor's runs, so the contrast is still readable.
    """

    term: str
    n_runs: int
    n_pairs: int
    events: int
    bound: float
    other_runs: int
    other_events: int


class GeeFit(NamedTuple):
    """A pair-clustered logistic GEE; `terms` are named `factor=level`.

    `references` names each fitted factor's reference level, which is the
    next level in order when the usual one was separated. `separated` lists
    the levels left out; the terms are estimated on the rows that remain.
    `unfitted` names the factors that still vary but were not fitted because
    fewer than `MIN_GEE_EVENTS` events or non-events remained; `terms` is
    then empty.
    """

    terms: dict[str, GeeTerm]
    n_groups: int
    cov: GeeCov
    references: dict[str, Any]
    separated: tuple[SeparatedLevel, ...] = ()
    unfitted: tuple[str, ...] = ()


LOGISTIC_RESIDUAL = math.pi**2 / 3
"""Latent-scale residual variance of the logit link: run-to-run noise."""


class VariancePartition(NamedTuple):
    """Latent-scale variance of a pair random-intercept logistic fit
    (Nakagawa & Schielzeth 2013), by source.

    `variance` holds one entry per fitted factor (the variance across runs of
    that factor's part of the linear predictor), `overlap` (what the factors
    explain jointly beyond their sum, from imbalance; may be negative),
    `pair` (the random-intercept variance: document to document) and `run`
    (`LOGISTIC_RESIDUAL`: epoch to epoch). `share` is each over the total.
    """

    variance: dict[str, float]
    share: dict[str, float]


class MixedFit(NamedTuple):
    """Posterior (mean, sd) of each fixed effect of a pair random-intercept
    logistic model, named like `GeeFit.terms`, and the variance partition of
    the same fit."""

    terms: dict[str, tuple[float, float]]
    variance: VariancePartition | None = None


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


def factor_levels(factor: str, values: Iterable[Any]) -> list[Any]:
    """Distinct levels, reference first (`REFERENCE`), the rest in order:
    numbers numerically (relay depth 0 < 2 < 10), anything else as text."""

    def order(v: Any) -> tuple[bool, int, float, str]:
        number = isinstance(v, int | float)
        return (
            v != REFERENCE.get(factor, object()),
            not number,
            v if number else 0,
            str(v),
        )

    return sorted(set(values), key=order)


class _Design(NamedTuple):
    y: list[float]
    columns: list[list[float]]
    names: list[str]
    groups: list[str]
    separated: tuple[SeparatedLevel, ...]
    references: dict[str, Any]
    unfitted: tuple[str, ...]


def _separate(
    data: list[Mapping[str, Any]], y: list[float], factors: Sequence[str], group: str
) -> tuple[list[Mapping[str, Any]], list[float], list[SeparatedLevel]]:
    """Drop every factor level with only events or only non-events, repeating
    until none is left (dropping rows can separate another level)."""
    separated: list[SeparatedLevel] = []
    while True:
        found = None
        for factor in factors:
            values = [r.get(factor) for r in data]
            if len(set(values)) < 2:
                continue
            for level in factor_levels(factor, values):
                hits = [v for v, x in zip(y, values, strict=True) if x == level]
                if sum(hits) in (0, len(hits)):
                    found = (factor, level, hits, values)
                    break
            if found:
                break
        if found is None:
            return data, y, separated
        factor, level, hits, values = found
        inside = [x == level for x in values]
        pairs = {r[group] for r, keep in zip(data, inside, strict=True) if keep}
        events = int(sum(hits))
        bound = zero_upper_bound(len(pairs))
        others = [v for v, keep in zip(y, inside, strict=True) if not keep]
        separated.append(
            SeparatedLevel(
                term=f"{factor}={level}",
                n_runs=len(hits),
                n_pairs=len(pairs),
                events=events,
                bound=bound if events == 0 else 1 - bound,
                other_runs=len(others),
                other_events=int(sum(others)),
            )
        )
        data = [r for r, keep in zip(data, inside, strict=True) if not keep]
        y = others


def _design(
    rows: Sequence[Mapping[str, Any]],
    outcome: str,
    factors: Sequence[str],
    group: str,
) -> _Design | None:
    """Treatment-coded main effects (no interactions), after separation.

    A level with only events or only non-events would send its estimate to
    infinity (the first-edition recompute gave p≈0 for a single event), so it
    is dropped and reported in `separated`, and the remaining levels are fitted
    on the remaining rows. Separation runs before the event count, so a sparse
    contrast is still reported as separated. Then, with fewer than
    `MIN_GEE_EVENTS` events or non-events left, nothing is fitted and the
    factors that still vary are `unfitted`. None when there is no event or no
    non-event at all, or no separated level and too few events. A factor left
    with one level carries no term.
    """
    data = list(_scored(rows, outcome))
    y = [float(r[f"score:{outcome}"]) for r in data]
    if sum(y) in (0, len(y)):
        return None
    data, y, separated = _separate(data, y, factors, group)
    enough = sum(y) >= MIN_GEE_EVENTS and len(y) - sum(y) >= MIN_GEE_EVENTS
    if not (enough or separated):
        return None
    columns: list[list[float]] = []
    names: list[str] = []
    references: dict[str, Any] = {}
    unfitted: list[str] = []
    for factor in factors:
        values = [r.get(factor) for r in data]
        levels = factor_levels(factor, values)
        if len(levels) < 2:
            continue
        if not enough:
            unfitted.append(factor)
            continue
        references[factor] = levels[0]
        for level in levels[1:]:
            columns.append([float(v == level) for v in values])
            names.append(f"{factor}={level}")
    return _Design(
        y,
        columns,
        names,
        [str(r[group]) for r in data],
        tuple(separated),
        references,
        tuple(unfitted),
    )


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
    Separated levels are left out and listed (`_design`); if nothing is left
    to fit, `terms` is empty. Returns None without statsmodels (the optional
    `analysis` extra), with too few events, when there is neither a term nor a
    separated level, or if the fit fails or is not finite: never a crash or a
    fake number (doc 11 §3.5).
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
    if design is None or not (design.names or design.separated):
        return None
    n_groups = len(set(design.groups))
    if not design.names:
        return GeeFit({}, n_groups, cov, {}, design.separated, design.unfitted)
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
        n_groups=n_groups,
        cov=cov,
        separated=design.separated,
        references=design.references,
    )


def mixed_fit(
    rows: Sequence[Mapping[str, Any]],
    outcome: str,
    factors: Sequence[str],
    group: str = "artifact_id",
) -> MixedFit | None:
    """Mixed-effects logistic sensitivity fit: a random intercept per pair.

    statsmodels' `BinomialBayesMixedGLM` fitted by variational Bayes
    (`fit_vb`), on the same design as `gee_fit` (separated levels left out).
    Its estimates are conditional on the pair, so they run larger than the
    GEE's population-averaged ones when pairs differ. The same fit gives
    `variance` (`VariancePartition`), which backs or refutes a claim that the
    outcome "depends more on the model than anything else varied" (doc 12
    A-50); like the terms, it describes the rows left after separation. None
    when there is no term to fit or the fit fails.
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
        np.asarray(design.y), exog, exog_vc, np.zeros(len(index), dtype=int)
    )
    try:
        result = model.fit_vb()
    except (ValueError, np.linalg.LinAlgError):
        return None
    means, sds = np.asarray(result.fe_mean), np.asarray(result.fe_sd)
    pair_sd = float(np.exp(np.asarray(result.vcp_mean)[0]))
    if not (np.isfinite(means).all() and np.isfinite(sds).all()):
        return None
    parts = exog[:, 1:] * means[1:]
    variance: dict[str, float] = {}
    for factor in dict.fromkeys(n.split("=", 1)[0] for n in design.names):
        columns = [i for i, n in enumerate(design.names) if n.startswith(f"{factor}=")]
        variance[factor] = float(np.var(parts[:, columns].sum(axis=1)))
    variance["overlap"] = float(np.var(parts.sum(axis=1))) - sum(variance.values())
    variance["pair"] = pair_sd**2
    variance["run"] = LOGISTIC_RESIDUAL
    total = sum(variance.values())
    return MixedFit(
        {
            name: (float(means[i + 1]), float(sds[i + 1]))
            for i, name in enumerate(design.names)
        },
        VariancePartition(variance, {k: v / total for k, v in variance.items()})
        if math.isfinite(total)
        else None,
    )


def gee_contrast(
    rows_a: Sequence[Mapping[str, Any]],
    rows_b: Sequence[Mapping[str, Any]],
    metric: str,
) -> GeeResult | None:
    """Logistic GEE of `metric` on A-vs-B, clustered by pair.

    `gee_fit` with `factors=["arm"]`, A as "attack" and B as the "twin"
    reference, at the primary (exchangeable) covariance. None when there is
    no `arm` term, including when either side is separated.
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


POWER_ICC = 0.2
"""Planning default: share of latent (logit-scale) variance in harm between
pairs. Some documents are far easier to act on than others; replace it with a
pilot estimate when one exists."""

POWER_EFFECT_CONCENTRATION = 0.5
"""Planning default: share of pairs the attack moves at all. The first edition
saw harm concentrated in a few artifacts (`pair_concentration`)."""


class _PowerDraws(NamedTuple):
    base: Any
    """Per-pair twin probability, (n_sim, n_pairs)."""
    affected: Any
    """Whether the attack moves the pair, (n_sim, n_pairs)."""
    twin: Any
    """Per-pair twin rate over its epochs, (n_sim, n_pairs)."""
    u_attack: Any
    """Uniforms for the attack runs, (n_sim, n_pairs, epochs)."""
    flips: Any
    """Fixed sign-flip patterns, (n_perm, n_pairs)."""


def _power_draws(
    base_rate: float,
    n_pairs: int,
    epochs: int,
    icc: float,
    effect_concentration: float,
    n_sim: int,
    n_perm: int,
    seed: int,
) -> _PowerDraws:
    import numpy as np

    if not (0 < base_rate < 1 and n_pairs >= 2 and epochs >= 1):
        raise ValueError("need 0 < base_rate < 1, n_pairs >= 2, epochs >= 1")
    if not (0 <= icc < 1 and 0 < effect_concentration <= 1):
        raise ValueError("need 0 <= icc < 1 and 0 < effect_concentration <= 1")
    rng = np.random.default_rng(seed)
    sigma = math.sqrt(icc / (1 - icc) * math.pi**2 / 3)
    logit = math.log(base_rate / (1 - base_rate)) + sigma * rng.standard_normal(
        (n_sim, n_pairs)
    )
    base = 1 / (1 + np.exp(-logit))
    affected = rng.random((n_sim, n_pairs)) < effect_concentration
    twin = (rng.random((n_sim, n_pairs, epochs)) < base[..., None]).mean(axis=2)
    u_attack = rng.random((n_sim, n_pairs, epochs))
    flips = rng.choice(np.array([-1.0, 1.0]), size=(n_perm, n_pairs))
    return _PowerDraws(base, affected, twin, u_attack, flips)


def _power(
    draws: _PowerDraws, delta: float, effect_concentration: float, alpha: float
) -> float:
    import numpy as np

    shift = np.where(draws.affected, delta / effect_concentration, 0.0)
    attack_p = np.minimum(1.0, draws.base + shift)
    d = (draws.u_attack < attack_p[..., None]).mean(axis=2) - draws.twin
    observed = np.abs(d.sum(axis=1))
    permuted = np.abs(d @ draws.flips.T)
    p = ((permuted >= observed[:, None] - 1e-12).sum(axis=1) + 1) / (
        draws.flips.shape[0] + 1
    )
    return float((p <= alpha).mean())


def power_at(
    delta: float,
    base_rate: float,
    n_pairs: int,
    epochs: int,
    *,
    icc: float = POWER_ICC,
    effect_concentration: float = POWER_EFFECT_CONCENTRATION,
    alpha: float = 0.05,
    n_sim: int = 500,
    n_perm: int = 999,
    seed: int = 0,
) -> float:
    """Simulated power of the study's paired test at a mean attack-minus-twin
    difference `delta`.

    Each simulated pair has its own twin probability: `base_rate` on the logit
    scale plus a normal pair intercept with intra-class correlation `icc`. A
    random `effect_concentration` share of pairs carries the effect, raised
    by `delta / effect_concentration` (capped at 1, so the realised mean can
    fall short of `delta` near the ceiling), so the mean shift over pairs is
    `delta`. Each pair runs `epochs` attack and `epochs` twin runs. The test
    is `sign_flip_test` on per-pair differences, vectorised with `n_perm`
    fixed Monte Carlo sign patterns (exact enumeration is not used here).
    """
    draws = _power_draws(
        base_rate, n_pairs, epochs, icc, effect_concentration, n_sim, n_perm, seed
    )
    return _power(draws, delta, effect_concentration, alpha)


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
    icc: float = POWER_ICC,
    effect_concentration: float = POWER_EFFECT_CONCENTRATION,
    n_perm: int = 999,
) -> float | None:
    """Simulated minimum detectable mean attack-minus-twin difference.

    The smallest `delta` on a `step` grid whose `power_at` simulation rejects
    at `alpha` in at least `power` of `n_sim` draws, or None if no `delta` up
    to 1 − `base_rate` does. All grid points share one set of draws (common
    random numbers), so power rises with `delta` up to Monte Carlo noise and
    the grid is searched by bisection; the answer is deterministic under
    `seed`. `mde` stays as the analytic approximation; this is the reported
    power (doc 11 §3.5).
    """
    if step <= 0:
        raise ValueError("step must be positive")
    draws = _power_draws(
        base_rate, n_pairs, epochs, icc, effect_concentration, n_sim, n_perm, seed
    )
    top = int((1 - base_rate) / step + 1e-9)

    def enough(k: int) -> bool:
        return _power(draws, k * step, effect_concentration, alpha) >= power

    if top < 1 or not enough(top):
        return None
    lo, hi = 0, top  # enough(hi) holds; lo is below the grid
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (lo, mid) if enough(mid) else (mid, hi)
    return round(hi * step, 10)
