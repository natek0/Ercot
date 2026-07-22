"""
Stage 4 tests — the periodic dynamic program core (the gate).

All synthetic and fast; run in CI. The load-bearing test is DP<->LP agreement on a
deterministic price path: the DP's average reward per day must match the
perfect-foresight LP's cyclic per-day objective to discretisation error.
"""

from __future__ import annotations

import numpy as np

from src import dp
from src.oracle import BatteryParams


def test_dp_lp_agreement_deterministic():
    """THE core correctness test (§IV.9 pt 3 / §IV.12): on a deterministic price the
    DP recovers the perfect-foresight LP's per-day value."""
    params = BatteryParams(c_deg=10.0)
    P = dp._synthetic_price()
    for E in (1.0, 2.0):
        d = dp.dp_vs_lp_deterministic(P, params, E, N_S=200)
        assert d["rel_diff"] < 0.01, (E, d)


def test_bellman_fixed_point_converges():
    params = BatteryParams(c_deg=10.0)
    res = dp.solve_dp(np.ones((24, 1, 1)), np.array([0.0]), dp._synthetic_price(),
                      params, 2.0, N_S=100)
    assert res.bellman_residual < 1e-6            # fixed-point span converged
    assert res.iters < 100                        # Gauss-Seidel day-sweeps are fast


def test_mu_monotone_nonincreasing():
    """μ = ∂Ṽ/∂S⁺ must be non-increasing in S⁺ (§IV.7 corollary) — the fuller the
    battery, the less an extra MWh is worth; equivalently the offer curve is monotone."""
    params = BatteryParams(c_deg=10.0)
    res = dp.solve_dp(np.ones((24, 1, 1)), np.array([0.0]), dp._synthetic_price(),
                      params, 2.0, N_S=200)
    assert dp.mu_monotone_violation(res) < 1e-6


def test_grid_convergence_to_lp():
    """The DP value converges to the LP as ΔS -> 0 (the §IV.8 discretisation bound)."""
    params = BatteryParams(c_deg=10.0)
    P = dp._synthetic_price()
    diffs = [dp.dp_vs_lp_deterministic(P, params, 2.0, N_S=n)["rel_diff"]
             for n in (50, 100, 200)]
    assert diffs[-1] < diffs[0]                   # finer grid -> closer to LP
    assert diffs[-1] < 5e-3


def test_flat_price_no_sustainable_profit():
    """A flat price with positive degradation -> the no-trade band (§IV.3) covers it,
    so there is no sustainable arbitrage: the optimal AVERAGE reward is ~0. (The policy
    need not be all-hold — discharging free initial charge is a weakly-optimal transient
    that does not change the long-run average, so ρ_day, not the policy, is the invariant.)"""
    params = BatteryParams(c_deg=10.0)
    flat = np.full(96, 40.0)
    res = dp.solve_dp(np.ones((24, 1, 1)), np.array([0.0]), flat, params, 2.0, N_S=100)
    assert abs(res.rho_day) < 1e-6


def test_spread_is_profitable():
    """A wide diurnal spread must yield strictly positive average reward."""
    params = BatteryParams(c_deg=10.0)
    res = dp.solve_dp(np.ones((24, 1, 1)), np.array([0.0]), dp._synthetic_price(),
                      params, 2.0, N_S=100)
    assert res.rho_day > 0


# --- the DP offer-curve execution (§IV.6) ------------------------------------ #
def test_dpcurve_dispatch_sides():
    """The DP offer curve (DPCurve) built from a continuation value with slope μ≈40
    discharges when the price clears above μ/η_d+c_deg, charges below η_c·μ−c_deg, and
    holds in the band (§IV.3)."""
    from src.policies import DPCurve
    params = BatteryParams(c_deg=25.0)
    E_max, N_S = 2.0, 100
    EK = 40.0 * np.linspace(0, E_max, N_S + 1)          # μ ≈ 40 $/MWh, holding is valuable
    curve = DPCurve(EK, E_max, N_S)
    c, d = curve.dispatch(200.0, soc=1.0, params=params, E_max=E_max)   # rich -> discharge
    assert d > 0 and c == 0
    c, d = curve.dispatch(5.0, soc=1.0, params=params, E_max=E_max)     # cheap -> charge
    assert c > 0 and d == 0
    c, d = curve.dispatch(40.0, soc=1.0, params=params, E_max=E_max)    # in band -> hold
    assert c == 0 and d == 0


def _synth_panel_for_dp(n_days=40, start="2026-01-01", seed=0):
    import pandas as pd
    n = n_days * 96
    ts = pd.date_range(start, periods=n, freq="15min")
    q = np.arange(n) % 96
    rng = np.random.RandomState(seed)
    resid = np.zeros(n)
    for t in range(1, n):
        resid[t] = 0.6 * resid[t - 1] + rng.randn() * 5 + (rng.rand() < 0.01) * 150
    price = 40 + 30 * np.sin((q - 40) / 96 * 2 * np.pi) + resid
    return pd.DataFrame({"ts": ts, "price": price})


def test_dp_policy_is_causal():
    """The DP offer-curve policy is F_t-measurable: scrambling the future leaves the
    decisions before that point byte-identical (no lookahead, §VIII.1/§IV.6)."""
    from src import features as F, markov
    from src.backtest import run_backtest
    from src.policies import DPPolicy
    panel = _synth_panel_for_dp()
    feat = F.build_features(panel)
    seasonal = F.fit_seasonal(feat)
    fr = F.add_residual_features(feat, seasonal).dropna(subset=["resid", "resid_lag_15min"])
    edges = markov.bin_edges(fr["resid"].to_numpy(float), n_bins=8)
    ht = markov.transition_counts(fr, edges)
    prof = seasonal.eval_cal(np.arange(96), np.zeros(96, int), np.full(96, 1))
    params = BatteryParams()
    res = dp.solve_dp(ht.matrices, ht.bin_centers, prof, params, 2.0, N_S=100)
    prices = panel["price"].to_numpy(float)
    ts = panel["ts"].to_numpy()
    cut = 25 * 96
    r1 = run_backtest(prices, DPPolicy(res.V, ht.matrices, edges, seasonal, ts, 2.0, 100),
                      params, 2.0, timestamps=ts)
    p2 = prices.copy()
    p2[cut:] = 9999.0
    r2 = run_backtest(p2, DPPolicy(res.V, ht.matrices, edges, seasonal, ts, 2.0, 100),
                      params, 2.0, timestamps=ts)
    a = r1.log.iloc[:cut][["c", "d"]].to_numpy()
    b = r2.log.iloc[:cut][["c", "d"]].to_numpy()
    assert np.allclose(a, b)
