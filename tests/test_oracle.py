"""
Verification suite for the perfect-foresight oracle (docs/step0_spec.md §7),
as pytest so CI enforces it on every change.

The four required checks:
  1. u=0 recursion / sign check (Correction 2)  -> test_recursion_*
  2. complementary slackness, every constraint   -> test_complementary_slackness
  3. no dumping, min(c,d)=0                        -> test_no_dumping
  4. duration identity, one-sided bracket         -> test_duration_identity_brackets
Plus boundary-condition and Stage-2-reuse coverage for the refactored API, and
one analytical small-instance test whose optimum is computable by hand.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from src import ingest, oracle
from src.oracle import (
    ALL_PRODUCTS,
    CONTINGENCY,
    ENERGY_ONLY,
    BatteryParams,
    binding_diagnostics,
    duration_identity,
    solve,
    verification,
)

ATOL = 1e-6
PRODUCT_SETS = [ENERGY_ONLY, CONTINGENCY, ALL_PRODUCTS]
REAL_PANEL = "data/raw/energy_HB_NORTH_2025-12-05_2026-06-20.parquet"


def _syn():
    P, mcpc = oracle.synthetic_prices()
    return P, mcpc, BatteryParams()


# --- check 1: u=0 recursion sign (Correction 2) ---------------------------- #
def test_energy_only_collapses_psi():
    """Forcing no reserves (energy-only) must zero out both headroom duals."""
    P, mcpc, pp = _syn()
    r = solve(P, mcpc, 2.0, pp, ENERGY_ONLY)
    assert np.allclose(r.psi_up, 0.0)
    assert np.allclose(r.psi_dn, 0.0)


def test_recursion_sign_on_binding_instance():
    """A strictly-rising price forces both SOC bounds to bind with NONZERO duals,
    so the three-term stationarity mu[k-1]=mu[k]-lam_hi[k]+lam_lo[k] (Correction 2)
    is exercised on every term, not vacuously. This pins the HiGHS dual sign."""
    P = np.array([5.0, 10.0, 20.0, 35.0, 55.0, 80.0])
    pp = BatteryParams(dt=1.0, eta_c=1.0, eta_d=1.0, c_deg=0.0, p_bar=1.0)
    r = solve(P, {}, 1.0, pp, ENERGY_ONLY)
    v = verification(r, pp)
    assert v["recursion_resid"] < 1e-7
    # not vacuous: the bound duals must actually be nonzero here
    assert np.max(np.abs(r.lam_hi)) > 1e-3
    assert np.max(np.abs(r.lam_lo)) > 1e-3


def test_recursion_sign_energy_only_full_window():
    P, mcpc, pp = _syn()
    r = solve(P, mcpc, 2.0, pp, ENERGY_ONLY)
    assert verification(r, pp)["recursion_resid"] < ATOL


# --- check 2: complementary slackness -------------------------------------- #
@pytest.mark.parametrize("pset", PRODUCT_SETS)
def test_complementary_slackness(pset):
    P, mcpc, pp = _syn()
    for E in (1.0, 2.0, 4.0):
        r = solve(P, mcpc, E, pp, pset)
        v = verification(r, pp)
        assert v["compl_slack_max"] < ATOL, (pset, E, v["compl_slack"])


# --- check 3: no dumping (Prop 3) ------------------------------------------ #
@pytest.mark.parametrize("pset", PRODUCT_SETS)
def test_no_dumping(pset):
    P, mcpc, pp = _syn()
    for E in (1.0, 2.0, 4.0):
        r = solve(P, mcpc, E, pp, pset)
        assert verification(r, pp)["no_dumping_min_cd"] < ATOL


# --- check 4: duration identity, one-sided bracket ------------------------- #
@pytest.mark.parametrize("pset", [CONTINGENCY, ALL_PRODUCTS])
def test_duration_identity_brackets(pset):
    """sum_t(lam_hi + psi_dn) must lie BETWEEN the left and right finite
    differences of the optimum w.r.t. E_max (never a central average — the LP is
    kinked). This validates the dual extraction Q2/Q3 depend on."""
    P, mcpc, pp = _syn()
    di = duration_identity(P, mcpc, 2.0, pp, pset)
    lo, hi = sorted([di["fd_left"], di["fd_right"]])
    s = di["sum_lam_hi_plus_psi_dn"]
    assert lo - 1e-6 <= s <= hi + 1e-6, di


# --- analytical small instance --------------------------------------------- #
def test_analytical_arbitrage():
    """Two intervals, price [1, 100], unit efficiency, no degradation, start and
    end empty: buy 1 MWh @ $1, sell 1 MWh @ $100 -> profit exactly $99."""
    P = np.array([1.0, 100.0])
    pp = BatteryParams(dt=1.0, eta_c=1.0, eta_d=1.0, c_deg=0.0, p_bar=1.0)
    r = solve(P, {}, 1.0, pp, ENERGY_ONLY, s_init=0.0, s_final=0.0)
    assert r.status == "optimal"
    assert abs(r.objective - 99.0) < ATOL


def test_flat_price_no_arbitrage():
    """A flat price with positive degradation: the optimum does nothing (0 profit)."""
    P = np.full(48, 42.0)
    pp = BatteryParams(dt=0.25, c_deg=25.0)
    r = solve(P, {}, 2.0, pp, ENERGY_ONLY)
    assert abs(r.objective) < ATOL
    assert np.max(r.c) < ATOL and np.max(r.d) < ATOL


# --- boundary conditions (the Stage-2 reuse surface) ----------------------- #
def test_boundary_s_init():
    P, mcpc, pp = _syn()
    r = solve(P, mcpc, 2.0, pp, CONTINGENCY, s_init=1.3, cyclic=False)
    assert abs(r.S[0] - 1.3) < ATOL


def test_boundary_s_final():
    P, mcpc, pp = _syn()
    r = solve(P, mcpc, 2.0, pp, CONTINGENCY, s_final=0.7, cyclic=False)
    assert abs(r.S[-1] - 0.7) < ATOL


def test_boundary_cyclic_default():
    P, mcpc, pp = _syn()
    r = solve(P, mcpc, 2.0, pp, CONTINGENCY)  # cyclic default
    assert abs(r.S[0] - r.S[-1]) < ATOL


def test_first_action_shape():
    P, mcpc, pp = _syn()
    r = solve(P, mcpc, 2.0, pp, CONTINGENCY)
    a = r.first_action()
    assert set(a) == {"c", "d", "S_next", "u"}
    assert abs(a["S_next"] - r.S[1]) < ATOL


def test_rolling_reuse_soc_continuity():
    """Mimic Stage 2's MPC loop: solve a short window from the current SOC, take
    the first action, carry S_next into the next solve as s_init. The oracle must
    honor each hand-off exactly (this is what makes it reusable in a rolling loop)."""
    P, mcpc, pp = _syn()
    s = 1.0
    for t0 in range(0, 40, 8):
        window = slice(t0, t0 + 32)
        Pw = P[window]
        mw = {k: v[window] for k, v in mcpc.items()}
        r = solve(Pw, mw, 2.0, pp, CONTINGENCY, s_init=s, cyclic=False)
        assert r.status == "optimal"
        assert abs(r.S[0] - s) < ATOL
        s = r.first_action()["S_next"]
        assert -ATOL <= s <= 2.0 + ATOL


# --- real-data gate: oracle computes the ceiling for every duration -------- #
@pytest.mark.skipif(not os.path.exists(REAL_PANEL), reason="cached panel not present (CI)")
def test_ceiling_every_duration_real_data():
    """Stage 1 gate: the oracle solves optimally and returns a finite ceiling for
    every duration in the Q3 sweep, and the counterfactual ordering
    energy-only <= +contingency <= +all-products holds at each duration."""
    panel = ingest.build_panel("2025-12-05", "2026-06-20", dedup=True)
    P = panel["price"].to_numpy(float)
    mcpc = {k: panel[k].to_numpy(float) for k in ingest.AS_TYPES}
    pp = BatteryParams()
    for E in (1.0, 2.0, 4.0):
        eo = solve(P, mcpc, E, pp, ENERGY_ONLY)
        co = solve(P, mcpc, E, pp, CONTINGENCY)
        ao = solve(P, mcpc, E, pp, ALL_PRODUCTS)
        for r in (eo, co, ao):
            assert r.status == "optimal"
            assert np.isfinite(r.objective)
        assert eo.objective <= co.objective + 1e-6 <= ao.objective + 1e-6
        # verification holds on the real solve too
        assert verification(co, pp)["no_dumping_min_cd"] < 1e-5
