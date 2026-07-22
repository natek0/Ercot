"""
Stage 2 tests — the causal-policy backtest, offer-curve execution, and the
value-of-foresight ordering. All synthetic and fast; run in CI.
"""

from __future__ import annotations

import numpy as np

from src.backtest import run_backtest
from src.forecast import PerfectForecaster, PersistenceForecaster, SeasonalNaiveForecaster
from src.oracle import CONTINGENCY, ENERGY_ONLY, BatteryParams, solve, synthetic_prices
from src.policies import CommittedDispatch, MPCPolicy, NaiveThresholdPolicy, Offer

ATOL = 1e-6


def _periodic(n_days: int) -> np.ndarray:
    """Daily-periodic price with a wide spread so arbitrage is clearly profitable
    (roughly -15..95 $/MWh). Weekly-periodic too, since it repeats every day."""
    q = np.arange(n_days * 96) % 96
    return 40.0 + 55.0 * np.sin((q - 40) / 96 * 2 * np.pi)


# --- offer-curve clearing ---------------------------------------------------- #
def test_offer_dispatch_sides_and_clipping():
    pp = BatteryParams()
    off = Offer(p_charge_below=10.0, p_discharge_above=50.0, cap=1.0)
    c, d = off.dispatch(60.0, soc=1.0, params=pp, E_max=2.0)   # rich price -> discharge
    assert d > 0 and c == 0
    c, d = off.dispatch(5.0, soc=0.5, params=pp, E_max=2.0)    # cheap price -> charge
    assert c > 0 and d == 0
    c, d = off.dispatch(30.0, soc=1.0, params=pp, E_max=2.0)   # in the band -> hold
    assert c == 0 and d == 0
    c, d = off.dispatch(60.0, soc=0.0, params=pp, E_max=2.0)   # empty -> cannot discharge
    assert d == 0
    c, d = off.dispatch(5.0, soc=2.0, params=pp, E_max=2.0)    # full -> cannot charge
    assert c == 0


def test_committed_dispatch_clips_to_feasibility():
    """The certainty-equivalent MPC's committed quantity is clipped so a plan can
    never over-draw an empty battery or over-fill a full one."""
    pp = BatteryParams()
    _, d = CommittedDispatch(0.0, 1.0).dispatch(50.0, soc=0.0, params=pp, E_max=2.0)
    assert d == 0                       # empty -> cannot discharge the planned 1 MW
    c, _ = CommittedDispatch(1.0, 0.0).dispatch(50.0, soc=2.0, params=pp, E_max=2.0)
    assert c == 0                       # full -> cannot charge the planned 1 MW
    c, _ = CommittedDispatch(1.0, 0.0).dispatch(5.0, soc=0.0, params=pp, E_max=2.0)
    assert c > 0                        # room available -> executes


# --- forecaster causality ---------------------------------------------------- #
def test_seasonal_naive_is_causal_and_exact_on_periodic():
    P = _periodic(3)
    f = SeasonalNaiveForecaster(period=96)
    # after 1 day of history, the day-ago slot forecasts the periodic signal exactly
    hist = P[:150]
    fc = f.predict(hist, horizon=48)
    assert np.allclose(fc, P[150:198])


# --- the harness withholds the future (no-lookahead is structural) ----------- #
def test_backtest_no_lookahead():
    P = _periodic(4)
    pp = BatteryParams(c_deg=1.0)
    r1 = run_backtest(P, NaiveThresholdPolicy(), pp, 2.0)
    P2 = P.copy()
    P2[200:] = 999.0                       # scramble the future
    r2 = run_backtest(P2, NaiveThresholdPolicy(), pp, 2.0)
    cols = ["c", "d"]
    a = r1.log.iloc[:200][cols].to_numpy()
    b = r2.log.iloc[:200][cols].to_numpy()
    assert np.allclose(a, b)               # decisions before t=200 are unchanged


def test_backtest_soc_stays_feasible():
    P = _periodic(4)
    pp = BatteryParams(c_deg=1.0)
    r = run_backtest(P, MPCPolicy(SeasonalNaiveForecaster(period=96), horizon=48),
                     pp, 2.0)
    assert r.soc.min() > -ATOL
    assert r.soc.max() < 2.0 + ATOL


# --- terminal value prevents the finite-horizon drain ------------------------ #
def test_terminal_value_prevents_drain():
    P = np.full(48, 50.0)
    pp = BatteryParams(c_deg=0.0)
    no_tv = solve(P, {}, 2.0, pp, ENERGY_ONLY, s_init=1.0, cyclic=False)
    with_tv = solve(P, {}, 2.0, pp, ENERGY_ONLY, s_init=1.0, cyclic=False,
                    terminal_value=100.0)
    assert no_tv.S[-1] < 0.1        # leftover energy is worthless at the edge -> dumped
    assert with_tv.S[-1] > 0.9      # valued at $100/MWh -> retained
    assert no_tv.S[-1] < with_tv.S[-1]


# --- the value-of-foresight ordering ----------------------------------------- #
def test_ceiling_ge_mpc_ge_floor():
    P = _periodic(4)
    pp = BatteryParams(c_deg=1.0)
    ceiling = solve(P, {}, 2.0, pp, ENERGY_ONLY).objective
    mpc = run_backtest(P, MPCPolicy(SeasonalNaiveForecaster(period=96), horizon=48),
                       pp, 2.0).profit
    floor = run_backtest(P, NaiveThresholdPolicy(), pp, 2.0).profit
    assert ceiling + 1e-6 >= mpc          # perfect foresight is unbeatable
    assert mpc + 1e-6 >= floor            # a good forecast beats the naive floor
    assert mpc > 0                        # and makes real money on a periodic signal


def test_clairvoyant_mpc_recovers_most_of_ceiling():
    """Validates the MPC machinery: fed a perfect forecast, the causal controller
    recovers most of the clairvoyant ceiling (the shortfall is the startup ramp
    from an empty battery). If this failed, low naive-MPC profit would be a bug,
    not forecast error."""
    P = _periodic(8)
    pp = BatteryParams(c_deg=1.0)
    ceiling = solve(P, {}, 2.0, pp, ENERGY_ONLY).objective
    clair = run_backtest(P, MPCPolicy(PerfectForecaster(P), horizon=48), pp, 2.0).profit
    assert clair > 0.80 * ceiling


# --- reserve co-optimisation + causal psi_up --------------------------------- #
def test_reserve_mpc_backs_headroom_and_earns():
    """The reserve-selling MPC must (a) keep every sold reserve MW backed by held
    charge — the RTC+B headroom rule, asserted inside the backtest — and (b) earn
    non-negative reserve revenue, with a finite non-negative causal psi_up."""
    P = _periodic(3)
    pp = BatteryParams(c_deg=1.0)
    mcpc = {k: np.full(len(P), 2.0) for k in ("ECRS", "NSPIN", "REGDN", "REGUP", "RRS")}
    r = run_backtest(
        P, MPCPolicy(SeasonalNaiveForecaster(period=96), horizon=48, product_set=CONTINGENCY),
        pp, 2.0, mcpc=mcpc,
    )  # reaching here without AssertionError means headroom held every interval
    assert r.reserve_revenue >= 0
    assert np.all(np.isfinite(r.psi_up)) and r.psi_up.min() >= -1e-9
    assert r.profit == r.energy_profit + r.reserve_revenue


def test_stage0_unchanged_by_terminal_value_default():
    """The terminal_value addition must not perturb the default (Stage 0) path."""
    P, mcpc = synthetic_prices()
    a = solve(P, mcpc, 2.0, BatteryParams(), ENERGY_ONLY)
    b = solve(P, mcpc, 2.0, BatteryParams(), ENERGY_ONLY, terminal_value=None)
    assert abs(a.objective - b.objective) < ATOL
