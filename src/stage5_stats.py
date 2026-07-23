"""
Stage 5 — statistical inference for a tail-concentrated profit distribution (§VIII.5).

PURE statistics. Every function here takes plain numpy arrays (typically a series of
daily paired differences D_i = Pi^A_i - Pi^B_i, one per traded calendar day) and returns
numbers — no data loading, no backtests, no I/O. That keeps the inference logic unit-testable
against synthetic inputs with known answers (tests/test_stage5.py); the heavy leak-free
backtests that PRODUCE the daily series live in src/stage5_run.py.

Why this protocol and not the textbook one (§VIII.5, and the plan's reasoning):

  * Profit in ERCOT is extremely tail-concentrated — a single scarcity day can be ~45% of a
    month's fleet revenue. Under that concentration, bootstrap coverage for the MEAN degrades
    badly, so the **sign test** (distribution-free) is the HEADLINE and the mean is secondary.
  * Daily differences are serially dependent (weather regimes persist), so an i.i.d. bootstrap
    understates the variance. We use the **stationary block bootstrap** (Politis & Romano 1994)
    and report the CI as a function of block length — an interval that moves with block length
    is itself information.
  * A **power statement** ("this design could detect an edge above X% of the ceiling") is the
    single most credibility-enhancing sentence available and almost nobody writes it.

All randomised routines are SEEDED (default seed=0) so every reported number is reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats as _sps


# --------------------------------------------------------------------------- #
#  (c) Sign test — the distribution-free HEADLINE statistic (§VIII.5c)
# --------------------------------------------------------------------------- #
@dataclass
class SignTestResult:
    n_days: int          # total daily differences supplied
    n_zero: int          # exact ties (dropped from the test, per convention)
    n_eff: int           # non-tied days actually tested
    n_pos: int           # days A beat B
    n_neg: int           # days B beat A
    prop_pos: float      # n_pos / n_eff (the "beats on X% of days" number)
    p_value: float       # two-sided exact binomial p under H0: P(D>0)=1/2


def sign_test(D, tol: float = 0.0) -> SignTestResult:
    """Exact two-sided sign test on daily paired differences D.

    Under H0 (no systematic difference) the count of positive days is Binomial(n_eff, 1/2).
    Reports "A beats B on prop_pos of days, p=...". This SURVIVES a fat tail because it only
    uses the SIGN of each day, not its magnitude — one $50k spike day counts as one win, the
    same as a $5 win. `tol` treats |D_i|<=tol as a tie (use a small tol to ignore sub-dollar
    numerical noise; default 0 = exact)."""
    D = np.asarray(D, float)
    n_days = D.size
    pos = int(np.sum(D > tol))
    neg = int(np.sum(D < -tol))
    n_eff = pos + neg
    n_zero = n_days - n_eff
    prop = pos / n_eff if n_eff else float("nan")
    # exact two-sided binomial p-value (scipy handles the doubling / clipping at 1)
    p = _sps.binomtest(pos, n_eff, 0.5, alternative="two-sided").pvalue if n_eff else 1.0
    return SignTestResult(n_days, n_zero, n_eff, pos, neg, prop, float(p))


# --------------------------------------------------------------------------- #
#  (c′) Paired sign-flip permutation test — the MAGNITUDE-AWARE companion
# --------------------------------------------------------------------------- #
def permutation_test(D, n_perm: int = 50000, seed: int = 0):
    """Exact-in-distribution paired sign-flip permutation test on daily differences D.

    Why this ALONGSIDE the sign test: the sign test throws away magnitude (a $900 win and a $1 win
    both count as one), which makes it the *least* powerful test against this study's actual
    alternative — a policy that wins by a few large-magnitude days. The paired permutation test
    keeps magnitude while making no distributional assumption: under H0 that each $D_i$ is
    symmetric about zero, the sign of every $D_i$ is exchangeable, so we form the null by flipping
    signs at random (Rademacher $\\pm 1$) and comparing the observed $\\sum_i D_i$ to that null.
    It is the right exact test for a magnitude-concentrated alternative, and — unlike the
    normal-approx mean test — it stays valid under the fat tail. Monte-Carlo over `n_perm` flips
    with the add-one correction (a permutation p-value is never exactly 0).

    Returns two-sided (does |edge| exceed chance?) and one-sided (is the edge > 0?) p-values."""
    D = np.asarray(D, float)
    n = D.size
    obs = float(D.sum())
    if n == 0:
        return {"observed": 0.0, "p_two_sided": 1.0, "p_one_sided": 1.0, "n_perm": n_perm}
    rng = np.random.default_rng(seed)
    signs = rng.integers(0, 2, size=(n_perm, n)) * 2 - 1        # ±1, flipping a zero is a no-op
    perm = (signs * D).sum(axis=1)
    p_two = (np.sum(np.abs(perm) >= abs(obs)) + 1) / (n_perm + 1)
    p_one = (np.sum(perm >= obs) + 1) / (n_perm + 1)
    return {"observed": obs, "p_two_sided": float(p_two), "p_one_sided": float(p_one),
            "n_perm": n_perm}


# --------------------------------------------------------------------------- #
#  (b) Stationary block bootstrap (§VIII.5b) — Politis & Romano (1994)
# --------------------------------------------------------------------------- #
def stationary_bootstrap_samples(x, stat_fn=np.sum, n_boot: int = 10000,
                                 block_mean: float = 5.0, seed: int = 0) -> np.ndarray:
    """Draw `n_boot` stationary-bootstrap replicates of stat_fn(resample), VECTORISED.

    The stationary bootstrap resamples wrap-around blocks whose lengths are geometric with mean
    `block_mean` (so at each step P(start a new block) = 1/block_mean, else continue the current
    block by advancing one index mod N). Geometric (random) block lengths — not fixed blocks — are
    what make the resampled series stationary, which is why this is the right bootstrap for a
    serially-dependent daily P&L series (Politis & Romano 1994).

    Implementation note: the index recursion is sequential in the series position t, but that loop
    is only N steps and each step is vectorised across all `n_boot` replicates at once — so the
    whole draw is O(N) NumPy ops, ~30x faster than the naive replicate-by-replicate double loop.
    `stat_fn` is applied row-wise via its `axis=1` argument (np.sum/np.mean/np.median all support
    it). Returns the (n_boot,) array of replicate statistics; the caller percentiles it into a CI."""
    x = np.asarray(x, float)
    N = x.size
    if N == 0:
        return np.array([])
    rng = np.random.default_rng(seed)
    p = 1.0 / float(block_mean)
    idx = np.empty((n_boot, N), dtype=np.int64)
    idx[:, 0] = rng.integers(0, N, size=n_boot)          # each replicate starts a block
    if N > 1:
        new_block = rng.random((n_boot, N - 1)) < p       # start a fresh block at step t?
        restart = rng.integers(0, N, size=(n_boot, N - 1))
        for t in range(1, N):
            cont = (idx[:, t - 1] + 1) % N                # else continue: advance one, wrap
            idx[:, t] = np.where(new_block[:, t - 1], restart[:, t - 1], cont)
    return stat_fn(x[idx], axis=1)


def bootstrap_ci(x, stat_fn=np.sum, n_boot: int = 10000, block_mean: float = 5.0,
                 seed: int = 0, alpha: float = 0.05):
    """Percentile CI at level (1-alpha) for stat_fn under the stationary bootstrap, plus the
    point estimate and the fraction of replicates on each side of zero (a one-line read of how
    much of the resampling mass changes the sign)."""
    x = np.asarray(x, float)
    point = float(stat_fn(x))
    sims = stationary_bootstrap_samples(x, stat_fn, n_boot, block_mean, seed)
    lo, hi = np.percentile(sims, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    frac_le0 = float(np.mean(sims <= 0.0))
    return {"point": point, "lo": float(lo), "hi": float(hi),
            "straddles_zero": bool(lo < 0 < hi), "frac_replicates_le_0": frac_le0,
            "block_mean": block_mean, "n_boot": n_boot}


def block_length_sensitivity(x, blocks=(1, 2, 5, 10, 20, 40), stat_fn=np.sum,
                             n_boot: int = 10000, seed: int = 0, alpha: float = 0.05):
    """(b) CI as a function of expected block length. A CI that widens materially as the block
    length grows is telling you the daily series is serially dependent and the i.i.d. bootstrap
    (block_mean=1) understates the uncertainty. Returns a list of per-block CI dicts."""
    return [bootstrap_ci(x, stat_fn, n_boot=n_boot, block_mean=b, seed=seed, alpha=alpha)
            for b in blocks]


# --------------------------------------------------------------------------- #
#  (d) Concentration reporting (§VIII.5d)
# --------------------------------------------------------------------------- #
def concentration(x, ks=(1, 5)):
    """Fraction of the total contributed by the top-k days.

    Reported two ways because the total can be small or negative (which makes top_k/total
    explode or go negative and mislead):
      * share_of_total  = top_k_sum / sum(x)          -- the plan's headline ratio
      * share_of_gross  = top_k_sum / sum(positive x) -- robust denominator; 'of all the money
                                                          MADE on up-days, how much is top-k'
    A share_of_gross near 1 means the entire positive P&L is a handful of days — the market
    finding, stated rather than asserted."""
    x = np.asarray(x, float)
    total = float(x.sum())
    gross_pos = float(x[x > 0].sum())
    order = np.sort(x)[::-1]
    res = {"total": total, "gross_positive": gross_pos, "n_days": int(x.size)}
    for k in ks:
        topk = float(order[:k].sum())
        res[f"top{k}_sum"] = topk
        res[f"top{k}_share_of_total"] = topk / total if total != 0 else float("nan")
        res[f"top{k}_share_of_gross"] = topk / gross_pos if gross_pos > 0 else float("nan")
    return res


# --------------------------------------------------------------------------- #
#  (e) Leave-one-day-out jackknife (§VIII.5e)
# --------------------------------------------------------------------------- #
def jackknife(x, stat_fn=np.sum):
    """Recompute stat_fn with each single day removed; report the min/max over the n leave-one
    -out values and whether the SIGN is fragile (does dropping any one day flip the sign of the
    statistic?). `which_day` is the index whose removal moves the statistic most."""
    x = np.asarray(x, float)
    n = x.size
    full = float(stat_fn(x))
    vals = np.array([stat_fn(np.delete(x, i)) for i in range(n)])
    sign_flips = bool((vals.min() < 0) != (vals.max() < 0)) or bool(
        (full > 0) and (vals.min() < 0)) or bool((full < 0) and (vals.max() > 0))
    most = int(np.argmax(np.abs(vals - full)))
    return {"full": full, "min": float(vals.min()), "max": float(vals.max()),
            "sign_flips": sign_flips, "most_influential_day": most,
            "delta_from_most_influential": float(full - vals[most])}


# --------------------------------------------------------------------------- #
#  (f) Power statement (§VIII.5f)
# --------------------------------------------------------------------------- #
def power_statement(D, ceiling: float, alpha: float = 0.05, power: float = 0.80):
    """Minimum detectable effect (MDE) for the paired MEAN difference, under a two-sided
    normal-approx test at level `alpha` with the stated `power`.

    Fixing the observed daily standard deviation sd(D) and n days, the smallest true mean daily
    difference a test of this size could reliably detect is
        MDE_mean = (z_{1-alpha/2} + z_{power}) * sd(D) / sqrt(n),
    equivalently a WINDOW-TOTAL edge of MDE_total = n * MDE_mean, which we express as a % of the
    perfect-foresight ceiling. Anything smaller than MDE_total is 'not resolvable with this
    sample'. Normal-approx caveat: under this market's fat tail the true MDE is somewhat larger
    (the mean's sampling distribution is heavier than Gaussian), so this is an OPTIMISTIC bound —
    which only strengthens a 'not separable' conclusion."""
    D = np.asarray(D, float)
    n = D.size
    sd = float(np.std(D, ddof=1)) if n > 1 else float("nan")
    z = _sps.norm.ppf(1 - alpha / 2) + _sps.norm.ppf(power)
    mde_mean = z * sd / np.sqrt(n) if n > 0 else float("nan")
    mde_total = n * mde_mean
    return {"n_days": n, "sd_daily": sd, "z_sum": float(z),
            "mde_mean_daily": float(mde_mean), "mde_total": float(mde_total),
            "mde_pct_of_ceiling": float(mde_total / ceiling) if ceiling else float("nan"),
            "alpha": alpha, "power": power}


# --------------------------------------------------------------------------- #
#  Convenience: the full paired-difference report in one call
# --------------------------------------------------------------------------- #
def paired_report(D, ceiling: float, seed: int = 0, sign_tol: float = 1e-6):
    """Bundle every §VIII.5 statistic for a daily paired-difference series D against a ceiling.
    Returns a dict of the sub-results; src.stage5_run formats it into reports/stage5_notes.md."""
    D = np.asarray(D, float)
    return {
        "n_days": int(D.size),
        "mean_daily": float(np.mean(D)) if D.size else float("nan"),
        "total": float(np.sum(D)),
        "sign_test": sign_test(D, tol=sign_tol),
        "permutation": permutation_test(D, seed=seed),
        "bootstrap_ci_sum": bootstrap_ci(D, np.sum, seed=seed),
        "bootstrap_ci_mean": bootstrap_ci(D, np.mean, seed=seed),
        "block_sensitivity_sum": block_length_sensitivity(D, stat_fn=np.sum, seed=seed),
        "concentration": concentration(D),
        "jackknife_sum": jackknife(D, np.sum),
        "power": power_statement(D, ceiling),
    }
