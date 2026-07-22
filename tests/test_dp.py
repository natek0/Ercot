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
