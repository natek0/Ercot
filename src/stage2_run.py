"""
Stage 2 — the first value-of-foresight gap.

Runs three policies over the real price window and reports the ladder:

    perfect-foresight ceiling  >=  MPC (same-hour-last-week)  >=  naive floor

- CEILING: the perfect-foresight LP objective (clairvoyant — it optimises the
  whole path knowing every future price). The unbeatable upper bound.
- MPC: the receding-horizon controller, causal, walked forward with no lookahead.
- FLOOR: the naive trailing-quantile threshold policy.

Reported per duration: realised profit of each, the value-of-foresight GAP
(ceiling - MPC), the CAPTURE rate (MPC / ceiling), and the UPLIFT of the MPC over
the naive floor (MPC - floor). Energy-only (arbitrage) for this first cut; the
reserve co-optimisation and the causal psi_up recompute are the Stage 2 follow-up.

    python -m src.stage2_run                # default demo window (fast)
    python -m src.stage2_run --full         # full post-launch window (slow, ~min)
"""

from __future__ import annotations

import os
import sys
import warnings

import numpy as np

# cvxpy sums an uninitialised np.empty() placeholder during shape inference;
# benign and third-party (see pyproject.toml filter for the test suite).
warnings.filterwarnings("ignore", message="invalid value encountered in reduce")

from src import ingest
from src.backtest import run_backtest
from src.forecast import PerfectForecaster, SameHourLastWeekForecaster
from src.oracle import CONTINGENCY, ENERGY_ONLY, BatteryParams, solve
from src.policies import MPCPolicy, NaiveThresholdPolicy

FULL = ("2025-12-05", "2026-06-20")
DEMO = ("2025-12-05", "2026-02-05")   # ~2 months: enough for a real gap, fast


def run(date_from, date_to, durations=(1.0, 2.0, 4.0), horizon=96):
    panel = ingest.build_panel(date_from, date_to)
    prices = panel["price"].to_numpy(float)
    ts = panel["ts"].to_numpy()
    mcpc = {k: panel[k].to_numpy(float) for k in ingest.AS_TYPES}
    params = BatteryParams()
    s0 = 0.0
    print(f"window {date_from}..{date_to}  T={len(prices)} intervals  "
          f"{panel['date'].nunique()} days  horizon={horizon} ({horizon/4:.0f}h)\n")

    print(f"{'E(h)':>5}{'ceiling$':>11}{'clairMPC$':>11}{'naiveMPC$':>11}"
          f"{'floor$':>10}  |  {'execCost$':>10}{'foreErr$':>10}")
    results = {}
    for E in durations:
        ceiling = solve(prices, {}, E, params, ENERGY_ONLY).objective
        clair = run_backtest(
            prices, MPCPolicy(PerfectForecaster(prices), horizon=horizon),
            params, E, s_init=s0, timestamps=ts,
        )
        mpc = run_backtest(
            prices, MPCPolicy(SameHourLastWeekForecaster(), horizon=horizon),
            params, E, s_init=s0, timestamps=ts,
        )
        floor = run_backtest(
            prices, NaiveThresholdPolicy(), params, E, s_init=s0, timestamps=ts,
        )
        results[E] = (ceiling, clair, mpc, floor)
        exec_cost = ceiling - clair.profit          # cost of causal execution + startup
        fore_err = clair.profit - mpc.profit         # cost of an imperfect forecast
        print(f"{E:>5.0f}{ceiling:>11.0f}{clair.profit:>11.0f}{mpc.profit:>11.0f}"
              f"{floor.profit:>10.0f}  |  {exec_cost:>10.0f}{fore_err:>10.0f}")

    # headline at 2 h (reuse the loop's solves)
    E = 2.0 if 2.0 in results else durations[0]
    ceiling, clair, mpc, floor = results[E]
    print(f"\n=== Value of foresight @ {E:.0f}h ===")
    print(f"  ceiling (clairvoyant LP):        ${ceiling:,.0f}")
    print(f"  MPC, perfect forecast:           ${clair.profit:,.0f}  "
          f"({clair.profit/ceiling:.0%} of ceiling — the rest is startup/execution)")
    print(f"  MPC, same-hour-last-week:        ${mpc.profit:,.0f}")
    print(f"  naive threshold floor:           ${floor.profit:,.0f}")
    print(f"  VALUE OF FORESIGHT (ceiling - naive MPC): ${ceiling - mpc.profit:,.0f}")
    print(f"    = execution/startup cost ${ceiling - clair.profit:,.0f} "
          f"+ forecast-error cost ${clair.profit - mpc.profit:,.0f}")
    # ---- reserve co-optimisation + the CAUSAL psi_up (Decision 19), at 2 h ---- #
    print(f"\n=== Reserve co-optimisation @ {E:.0f}h (contingency: RRS/ECRS/NSPIN) ===")
    res_mpc = run_backtest(
        prices,
        MPCPolicy(SameHourLastWeekForecaster(), horizon=horizon, product_set=CONTINGENCY),
        params, E, s_init=s0, mcpc=mcpc, timestamps=ts,
    )
    print(f"  energy arbitrage:   ${res_mpc.energy_profit:,.0f}")
    print(f"  reserve capacity:   ${res_mpc.reserve_revenue:,.0f}")
    print(f"  total (causal MPC): ${res_mpc.profit:,.0f}   "
          f"(reserves turn the energy-only ${mpc.profit:,.0f} into "
          f"${res_mpc.profit:,.0f})")

    psi = res_mpc.psi_up
    tol = 0.01 * np.median(np.abs(prices))
    sold = res_mpc.log["u_up"].to_numpy() > 1e-9
    binding = (psi > tol) & sold
    print(f"\n  CAUSAL psi_up (shadow price of RTC+B SOC enforcement, real operator):")
    print(f"    median ${np.median(psi[sold]) if sold.any() else 0:.3f}  "
          f"p90 ${np.percentile(psi[sold], 90) if sold.any() else 0:.3f}  "
          f"p99 ${np.percentile(psi[sold], 99) if sold.any() else 0:.3f}  "
          f"max ${psi.max():.2f}")
    print(f"    binds (psi>tol & reserves sold) in {binding.mean()*100:.2f}% of intervals")
    print("    vs Stage 0 perfect-foresight psi_up (median $0.015, p99 $1.47, max "
          "$32.75). Decision 19: the causal operator cannot dodge the constraint as "
          "well as a clairvoyant, so this is the higher, real-operator number "
          "(forecast-limited here; the definitive value comes from the Stage 4 DP).")

    # ---- persist the live decision log (gitignored raw dir) ------------------ #
    os.makedirs("data/raw", exist_ok=True)
    logpath = f"data/raw/stage2_decision_log_{date_from}_{date_to}.parquet"
    res_mpc.log.to_parquet(logpath)
    print(f"\n  live decision log ({len(res_mpc.log)} rows) -> {logpath}")
    cols = ["ts", "price", "soc_pre", "c", "d", "u_up", "psi_up", "step_profit"]
    print(res_mpc.log[cols].tail(4).to_string(index=False))
    print("\nNote: ceiling is cyclic full-window; MPC/floor are causal from S0=0 "
          "(boundary effect negligible over the window). psi_up here is the "
          "naive-forecast operator's; Stage 4's DP gives the definitive causal value.")


def main():
    full = "--full" in sys.argv
    date_from, date_to = FULL if full else DEMO
    if not full:
        print("(demo window — pass --full for the whole post-launch window)\n")
    run(date_from, date_to)


if __name__ == "__main__":
    main()
