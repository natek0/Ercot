"""
Stage 5 — tests for the statistical inference suite (src.stage5_stats).

The stats functions are PURE (numpy in, numbers out), so we test them against synthetic inputs
with KNOWN answers rather than against a backtest. The heavy leak-free backtests that produce
the real daily series (src.stage5_run) are exercised by the existing Stage-4 causality tests;
here we pin the inference logic itself: sign test, bootstrap CI, concentration, jackknife, and
the power statement, plus determinism (seeded => identical numbers every run).
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats as sps

from src import stage5_stats as st


# --------------------------------------------------------------------------- #
#  Sign test
# --------------------------------------------------------------------------- #
def test_sign_test_counts_and_ties():
    D = np.array([1.0, 2.0, -1.0, 0.0, 3.0])          # 3 pos, 1 neg, 1 tie
    r = st.sign_test(D)
    assert (r.n_pos, r.n_neg, r.n_zero, r.n_eff) == (3, 1, 1, 4)
    assert r.prop_pos == 0.75
    # matches scipy's exact two-sided binomial on the non-tied days
    assert r.p_value == pytest.approx(sps.binomtest(3, 4, 0.5).pvalue)


def test_sign_test_all_positive_is_significant():
    r = st.sign_test(np.arange(1, 21, dtype=float))    # 20/20 wins
    assert r.prop_pos == 1.0
    assert r.p_value < 1e-4                              # 2 * 0.5**20


def test_sign_test_symmetric_is_insignificant():
    D = np.array([1, -1, 1, -1, 1, -1, 2, -2], float)  # 4 vs 4
    r = st.sign_test(D)
    assert r.prop_pos == 0.5
    assert r.p_value == pytest.approx(1.0)


def test_sign_test_tol_treats_small_as_tie():
    D = np.array([0.5, -0.5, 10.0], float)
    r = st.sign_test(D, tol=1.0)                         # |0.5| <= 1 -> ties
    assert r.n_eff == 1 and r.n_pos == 1


# --------------------------------------------------------------------------- #
#  Stationary bootstrap
# --------------------------------------------------------------------------- #
def test_bootstrap_is_seeded_deterministic():
    x = np.random.default_rng(1).normal(size=60)
    a = st.bootstrap_ci(x, np.sum, n_boot=500, seed=7)
    b = st.bootstrap_ci(x, np.sum, n_boot=500, seed=7)
    assert a == b                                        # identical dicts, byte-for-byte


def test_bootstrap_ci_brackets_point_estimate():
    x = np.random.default_rng(2).normal(loc=5.0, size=200)
    c = st.bootstrap_ci(x, np.sum, n_boot=1000, seed=0)
    assert c["lo"] < c["point"] < c["hi"]


def test_bootstrap_ci_covers_mean_of_known_normal():
    # a strongly-positive-mean series: the 95% CI on the SUM should sit well above 0
    x = np.random.default_rng(3).normal(loc=10.0, scale=1.0, size=100)
    c = st.bootstrap_ci(x, np.sum, n_boot=2000, seed=0)
    assert c["lo"] > 0 and not c["straddles_zero"]


def test_bootstrap_ci_straddles_zero_for_zero_mean():
    x = np.random.default_rng(4).normal(loc=0.0, scale=3.0, size=80)
    c = st.bootstrap_ci(x, np.sum, n_boot=2000, seed=0)
    assert c["straddles_zero"]


def test_block_length_sensitivity_shape():
    x = np.random.default_rng(5).normal(size=100)
    rows = st.block_length_sensitivity(x, blocks=(1, 5, 20), n_boot=300)
    assert [r["block_mean"] for r in rows] == [1, 5, 20]


def test_bootstrap_ci_covers_mean_at_nominal_rate():
    """CALIBRATION (the load-bearing property, not just lo<point<hi): a 90% CI on the SUM should
    contain the TRUE sum ~90% of the time across independent samples. This is what makes the CI a
    CI. Uses i.i.d. draws (block_mean=1) so the nominal rate is well-defined; tolerance is wide
    because it's Monte-Carlo over a modest number of trials to stay CI-fast."""
    true_mean, N, trials, hits = 2.0, 80, 200, 0
    for t in range(trials):
        x = np.random.default_rng(1000 + t).normal(true_mean, 3.0, N)
        c = st.bootstrap_ci(x, np.sum, n_boot=400, block_mean=1.0, seed=t, alpha=0.10)
        if c["lo"] <= true_mean * N <= c["hi"]:
            hits += 1
    assert 0.80 <= hits / trials <= 0.98      # nominal 0.90, generous MC band


# --------------------------------------------------------------------------- #
#  Permutation test (magnitude-aware companion)
# --------------------------------------------------------------------------- #
def test_permutation_all_positive_significant():
    r = st.permutation_test(np.arange(1, 21, dtype=float), n_perm=5000)
    assert r["p_one_sided"] < 0.01          # every day positive -> the edge can't arise by chance
    assert r["p_two_sided"] < 0.02


def test_permutation_symmetric_insignificant():
    D = np.array([5, -5, 3, -3, 8, -8, 1, -1], float)   # perfectly symmetric -> no edge
    r = st.permutation_test(D, n_perm=5000)
    assert r["p_two_sided"] > 0.5


def test_permutation_is_seeded_deterministic():
    D = np.random.default_rng(11).normal(1.0, 5.0, 40)
    assert st.permutation_test(D, n_perm=2000, seed=3) == st.permutation_test(D, n_perm=2000, seed=3)


def test_permutation_magnitude_beats_sign_test():
    """The whole point of adding it: with a few big wins and many tiny losses, the sign test is a
    near coin-flip but the magnitude-aware permutation test is far more significant."""
    D = np.array([100.0, 90.0, 80.0] + [-1.0] * 9)      # 3 big wins, 9 tiny losses (sign 3/12=25%)
    sign_p = st.sign_test(D).p_value
    perm_p = st.permutation_test(D, n_perm=5000)["p_one_sided"]
    assert perm_p < sign_p                               # magnitude rescues what the sign loses


# --------------------------------------------------------------------------- #
#  Leak-free matched-window plumbing (stage5_run._traded_mask / _daily_pnl)
# --------------------------------------------------------------------------- #
def test_traded_mask_excludes_warmup_months():
    import pandas as pd
    from src import stage5_run as S
    panel = pd.DataFrame({"ts": pd.date_range("2025-12-05", periods=120, freq="D")})
    mask = S._traded_mask(panel, min_train_months=2)
    ym = panel["ts"].dt.to_period("M")
    warmup_months = list(ym.drop_duplicates())[:2]       # Dec, Jan held out
    assert not mask[ym.isin(warmup_months).to_numpy()].any()   # warm-up all False
    assert mask[~ym.isin(warmup_months).to_numpy()].all()      # everything after all True


def test_daily_pnl_aligns_and_sums_only_traded_days():
    import pandas as pd
    from src import stage5_run as S
    ts = pd.date_range("2025-12-05", periods=120, freq="D")
    panel = pd.DataFrame({"ts": ts})
    log = pd.DataFrame({"ts": ts, "step_profit": np.ones(120)})
    mask = S._traded_mask(panel, min_train_months=2)
    daily = S._daily_pnl(log, mask)
    assert len(daily) == int(mask.sum())                 # one row per traded day, no warm-up days
    assert (daily == 1.0).all()                          # one interval/day, profit 1 each
    warmup_dates = set(ts[~mask].date)
    assert not (set(daily.index) & warmup_dates)         # no warm-up date leaks into the series


# --------------------------------------------------------------------------- #
#  Concentration
# --------------------------------------------------------------------------- #
def test_concentration_all_in_one_day():
    x = np.array([0.0, 0.0, 100.0, 0.0])
    c = st.concentration(x)
    assert c["top1_share_of_total"] == pytest.approx(1.0)
    assert c["top1_share_of_gross"] == pytest.approx(1.0)


def test_concentration_half_share():
    x = np.array([50.0, 50.0])
    c = st.concentration(x, ks=(1,))
    assert c["top1_share_of_total"] == pytest.approx(0.5)


def test_concentration_gross_denominator_ignores_losses():
    x = np.array([100.0, -40.0, 0.0])                    # gross positive = 100, net = 60
    c = st.concentration(x, ks=(1,))
    assert c["top1_share_of_gross"] == pytest.approx(1.0)
    assert c["top1_share_of_total"] == pytest.approx(100.0 / 60.0)


# --------------------------------------------------------------------------- #
#  Jackknife
# --------------------------------------------------------------------------- #
def test_jackknife_sum_range():
    x = np.array([1.0, 2.0, 3.0, 100.0])                 # total 106
    jk = st.jackknife(x, np.sum)
    assert jk["full"] == pytest.approx(106.0)
    assert jk["min"] == pytest.approx(6.0)               # drop the 100 day
    assert jk["max"] == pytest.approx(105.0)             # drop the 1 day
    assert jk["most_influential_day"] == 3               # the 100 day moves it most


def test_jackknife_sign_fragility():
    # total is +4 but dropping the single +10 day flips it to -6 -> fragile
    x = np.array([10.0, -2.0, -2.0, -2.0])
    jk = st.jackknife(x, np.sum)
    assert jk["full"] > 0 and jk["min"] < 0 and jk["sign_flips"]


# --------------------------------------------------------------------------- #
#  Power statement
# --------------------------------------------------------------------------- #
def test_power_statement_formula():
    D = np.random.default_rng(6).normal(scale=2.0, size=100)
    ceiling = 1000.0
    pw = st.power_statement(D, ceiling, alpha=0.05, power=0.80)
    z = sps.norm.ppf(0.975) + sps.norm.ppf(0.80)
    sd = np.std(D, ddof=1)
    assert pw["mde_mean_daily"] == pytest.approx(z * sd / np.sqrt(100))
    assert pw["mde_total"] == pytest.approx(100 * pw["mde_mean_daily"])
    assert pw["mde_pct_of_ceiling"] == pytest.approx(pw["mde_total"] / ceiling)


def test_power_scales_with_sqrt_n():
    rng = np.random.default_rng(7)
    D_small = rng.normal(scale=2.0, size=64)
    D_big = rng.normal(scale=2.0, size=256)
    p_small = st.power_statement(D_small, 1.0)["mde_mean_daily"]
    p_big = st.power_statement(D_big, 1.0)["mde_mean_daily"]
    # 4x the days -> 2x tighter MDE on the per-day mean (roughly, same sd)
    assert p_small / p_big == pytest.approx(2.0, rel=0.25)


# --------------------------------------------------------------------------- #
#  Full bundle
# --------------------------------------------------------------------------- #
def test_paired_report_keys():
    D = np.random.default_rng(8).normal(loc=1.0, size=50)
    rep = st.paired_report(D, ceiling=500.0)
    for k in ("sign_test", "bootstrap_ci_sum", "bootstrap_ci_mean",
              "block_sensitivity_sum", "concentration", "jackknife_sum", "power"):
        assert k in rep
    assert rep["n_days"] == 50


# --------------------------------------------------------------------------- #
#  Figures — smoke test (synthetic cache, no ERCOT data, headless Agg backend)
# --------------------------------------------------------------------------- #
def test_figures_smoke(tmp_path):
    """Every figure function must produce a non-empty PNG from a synthetic in-memory cache.
    Exercises the plotting code paths (labels, mathtext, annotations) in CI without any real
    data — a guard against the currency/mathtext rendering bugs found during the build."""
    import matplotlib
    matplotlib.use("Agg")
    import pandas as pd
    from src import figures

    rng = np.random.default_rng(0)
    daily = pd.DataFrame({
        "dp_emp": rng.normal(20, 100, 60), "dp_lrn": rng.normal(18, 100, 60),
        "mpc_learned": rng.normal(15, 100, 60), "mpc_naive": rng.normal(-20, 100, 60),
        "floor": rng.normal(-30, 100, 60),
    })
    daily.attrs.update({"ceiling_full": 13206.0, "clair_full": 12847.0, "dp_full": 2364.0,
                        "learned_full": -303.0, "naive_full": -3453.0, "floor_full": -5267.0})
    dur = pd.DataFrame({"E": [0.5, 1, 2, 4, 8], "v_pf": [5064, 8588, 13206, 18709, 22921],
                        "v_dp": [-153, 505, 2364, 4366, 5643],
                        "capture": [-0.03, 0.06, 0.18, 0.23, 0.25]})
    psi = {"psi_iv": np.abs(rng.normal(0, 3, 500)), "median_price": 22.8}

    figures._style()
    for name, fn, arg in [("l", figures.fig_ladder, daily), ("d", figures.fig_duration, dur),
                          ("c", figures.fig_concentration, daily),
                          ("b", figures.fig_bootstrap, daily),
                          ("s", figures.fig_signtest, daily), ("p", figures.fig_psi, psi)]:
        out = tmp_path / f"{name}.png"
        fn(arg, str(out))
        assert out.exists() and out.stat().st_size > 1000
