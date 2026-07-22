"""
Stage 4 — reserve co-optimisation for Q2 (the causal cost of RTC+B SOC enforcement).

The DP earns energy arbitrage AND ancillary (reserve) income. Up-reserves (RRS, ECRS,
Non-Spin) are promises to inject more power on call; to make the promise credibly the
battery must HOLD backing charge (the energy-headroom rule, EH-up). The same stored MWh
cannot be both sold as arbitrage and pledged as reserve, so the two compete — that is
what "co-optimisation" resolves, and ψ_up (the shadow price of EH-up) is the marginal
cost the SOC-enforcement rule imposes. This module supplies the reserve VALUE that makes
the DP hold charge for reserves, and the ψ_up it implies.

Design (the locked Stage 4 decisions):
  * A2 — the reserve value is a function of BOTH the post-decision charge S⁺ (energy
    budget, via EH-up) AND the power budget left after the energy action, P = p̄ − (d−c).
  * B2 — reserves priced at the hour-EXPECTED MCPC; a constant deployment factor ρ_k
    charges the expected throughput degradation c_deg·ρ_k·τ_k per MW, and ρ_k is SWEPT
    as a sensitivity. (The full state-dependent deployment/forgone-energy term needs
    dispatch telemetry — out of scope, Decision 17 — so it is the named simplification.)
  * C1 — ψ_up is read as the DUAL on the EH-up (energy) constraint of the reserve LP.

The reserve sub-problem, for a fixed energy action, is a tiny 2-constraint LP (a
fractional knapsack) with a clean dual, solved here with HiGHS via scipy.linprog.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import linprog

UP_PRODUCTS = ["RRS", "ECRS", "NSPIN"]


def hour_reserve_prices(panel, products=UP_PRODUCTS) -> np.ndarray:
    """(24, K) hour-of-day MEAN MCPC for the up-products (B2 — the expected price)."""
    hh = panel["ts"].dt.hour.to_numpy()
    return np.array([[panel[k].to_numpy(float)[hh == h].mean() for k in products]
                     for h in range(24)])


def reserve_lp(E: float, P: float, v: np.ndarray, a: np.ndarray):
    """Solve  max_{u>=0}  v·u   s.t.  a·u <= E (energy headroom) [ψ_up],  sum(u) <= P (power).
    Returns (value, psi_up) with psi_up = the dual (marginal value) on the ENERGY constraint.

    v : (K,) net value per MW of each product ($/interval).  a : (K,) = τ_k/η_d (MWh of
    backing charge per MW).  E : available backing charge (MWh).  P : available power (MW)."""
    E = max(E, 0.0)
    P = max(P, 0.0)
    K = len(v)
    if P <= 0 or E <= 0 or np.all(v <= 0):
        return 0.0, 0.0
    A_ub = np.vstack([a, np.ones(K)])
    b_ub = np.array([E, P])
    res = linprog(-v, A_ub=A_ub, b_ub=b_ub, bounds=[(0, None)] * K, method="highs")
    if not res.success:
        return 0.0, 0.0
    value = float(-res.fun)
    # HiGHS marginals for a <= constraint in a min problem are <= 0 and equal
    # d(min)/d(b). Our objective is -value, so d(value)/dE = -marginals[energy] >= 0 = ψ_up.
    psi_up = float(-res.ineqlin.marginals[0])
    return value, max(psi_up, 0.0)


def validate_psi(E: float, P: float, v: np.ndarray, a: np.ndarray, delta: float = 1e-4):
    """§IV.11-style multiplier check for C1: ψ_up (the LP dual on the energy constraint)
    must equal the finite-difference of the reserve value w.r.t. the energy budget E. The
    value is concave-kinked in E, so ψ_up should sit BETWEEN the left and right differences.
    Returns (psi_dual, fd_left, fd_right, ok)."""
    val, psi = reserve_lp(E, P, v, a)
    vr, _ = reserve_lp(E + delta, P, v, a)
    vl, _ = reserve_lp(max(E - delta, 0.0), P, v, a)
    fd_right = (vr - val) / delta
    fd_left = (val - vl) / delta
    lo, hi = min(fd_left, fd_right), max(fd_left, fd_right)
    ok = (lo - 1e-6) <= psi <= (hi + 1e-6)
    return float(psi), float(fd_left), float(fd_right), bool(ok)


def reserve_value_arrays(rp_h: np.ndarray, tau: np.ndarray, rho: float, c_deg: float,
                         dt: float, eta_d: float, p_bar: float, s_min: float,
                         E_grid: np.ndarray, P_grid: np.ndarray):
    """For ONE hour, tabulate reserve value and ψ_up over (E = S⁺ − s_min, P = power budget).
    v_k = (MCPC_k − c_deg·ρ·τ_k)·dt (B2 deployment-degradation); a_k = τ_k/η_d (A2 energy)."""
    v = (rp_h - c_deg * rho * tau) * dt
    a = tau / eta_d
    val = np.zeros((len(E_grid), len(P_grid)))
    psi = np.zeros((len(E_grid), len(P_grid)))
    for i, E in enumerate(E_grid):
        for j, P in enumerate(P_grid):
            val[i, j], psi[i, j] = reserve_lp(max(E - s_min, 0.0), P, v, a)
    return val, psi


def build_reserve_tables(rp: np.ndarray, params, E_max: float, rho: float,
                         n_E: int = 21, products=UP_PRODUCTS):
    """Precompute value[h,E,P] and psi[h,E,P] tables (A2/B2/C1) on a coarse (E,P) grid.
    Returns (value, psi, E_grid, P_grid). The DP interpolates these at (S⁺, power budget)."""
    tau = np.array([params.tau[k] for k in products])
    # refine near E=0 where ψ_up is largest and changes fastest (else the E=0→0.1 jump
    # smooths the tail — the second understatement source the review flagged)
    E_grid = np.unique(np.concatenate([np.linspace(0.0, 0.3, 10), np.linspace(0.0, E_max, n_E)]))
    # power budget ranges over [0, p̄ + p̄] (charging frees extra up-headroom); coarse grid
    P_grid = np.linspace(0.0, 2.0 * params.p_bar, 5)
    val = np.zeros((24, len(E_grid), len(P_grid)))
    psi = np.zeros((24, len(E_grid), len(P_grid)))
    for h in range(24):
        val[h], psi[h] = reserve_value_arrays(
            rp[h], tau, rho, params.c_deg, params.dt, params.eta_d,
            params.p_bar, params.s_min, E_grid, P_grid)
    return val, psi, E_grid, P_grid
