"""
Stage 4 — periodic dynamic program on the real ERCOT residual kernel (energy-only).

This is the FIRST Stage 4 milestone: solve the optimal causal policy's value function
on the Stage 3 hour-indexed transition kernel and report its in-model expected profit
per day, with the correctness gate (DP<->LP, Bellman residual, μ-monotonicity, grid
convergence). It reconstructs the price as seasonal(h) + residual-bin-centre for a
representative weekday in the recent season (plan "STAGE 4 updates" item 3).

IMPORTANT — what this number is and is NOT. ρ_day here is the EXPECTED average reward
under the LEARNED model (the DP's own transition kernel), for a representative day. It
is NOT yet the realised out-of-sample value V^DP of §IV.13 — that requires simulating
the DP's offer-curve policy forward on the real price path (walk-forward, no lookahead),
which is the next Stage 4 step and the number that slots into the value-of-information
ladder. Reserves/(AS)/ψ_up (Q2), the duration sweep (Q3), the tail recalibration, and
the §V.26 capture-rate prong are also subsequent steps.

    python -m src.stage4_run            # demo (fast)
    python -m src.stage4_run --full     # full window kernel, more durations + grid sweep
"""

from __future__ import annotations

import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore", message="invalid value encountered in reduce")

from src import dp, features as F, ingest, markov
from src.oracle import BatteryParams

FULL = ("2025-12-05", "2026-06-20")
DEMO = ("2025-12-05", "2026-04-05")


def build_dp_inputs(date_from, date_to, n_bins=12):
    """Fit the seasonal + residual kernel on the window and assemble the DP inputs:
    the hour-indexed kernel, the residual bin centres, and a representative-weekday
    seasonal price profile seasonal(h), h=0..95."""
    panel = ingest.build_panel(date_from, date_to)
    feat = F.build_features(panel)
    seasonal = F.fit_seasonal(feat)                       # full-window fit (in-model value)
    fr = F.add_residual_features(feat, seasonal).dropna(subset=["resid", "resid_lag_15min"])
    edges = markov.bin_edges(fr["resid"].to_numpy(float), n_bins=n_bins)
    ht = markov.transition_counts(fr, edges)              # the empirical kernel
    # representative-weekday seasonal profile for the most recent month in the window
    rep_month = int(feat.sort_values("ts")["month"].iloc[-1])
    qod = np.arange(96)
    seasonal_profile = seasonal.eval_cal(qod, np.zeros(96, int), np.full(96, rep_month))
    return ht, seasonal_profile, rep_month, panel


def run(date_from, date_to, durations=(1.0, 2.0, 4.0), N_S=200, n_bins=12):
    params = BatteryParams()
    ht, seasonal_profile, rep_month, panel = build_dp_inputs(date_from, date_to, n_bins)
    print(f"window {date_from}..{date_to}  {panel['date'].nunique()} days  "
          f"kernel: {ht.n_bins} bins x 24 hours  rep-month={rep_month}  N_S={N_S}\n")
    print(f"  seasonal profile: min ${seasonal_profile.min():.1f}  max "
          f"${seasonal_profile.max():.1f}  (representative-weekday diurnal level)")
    chk = ht.check()
    print(f"  kernel: matrix-irreducible={chk['irreducible']}  "
          f"raw-count-irreducible={chk['counts_irreducible']}\n")

    print(f"  {'E(h)':>5}{'DP $/day':>11}{'DP $/window':>13}{'bellman':>10}{'muMonoViol':>12}{'iters':>7}")
    for E in durations:
        res = dp.solve_dp(ht.matrices, ht.bin_centers, seasonal_profile, params, E, N_S=N_S)
        window_val = res.rho_day * panel["date"].nunique()
        print(f"  {E:>5.0f}{res.rho_day:>11.2f}{window_val:>13.0f}"
              f"{res.bellman_residual:>10.1e}{dp.mu_monotone_violation(res):>12.1e}"
              f"{res.iters:>7d}")

    # DP<->LP sanity on a deterministic reduction (the correctness gate, on THIS seasonal)
    det = dp.dp_vs_lp_deterministic(seasonal_profile, params, 2.0, N_S=N_S)
    print(f"\n  DP<->LP on the deterministic seasonal (E=2h): DP ${det['dp_rho_day']:.2f}/day "
          f"vs LP ${det['lp_per_day']:.2f}/day  reldiff={det['rel_diff']:.1e}")

    if N_S == 200:
        print("\n  grid convergence @2h (stochastic kernel):")
        for n in (50, 100, 200, 400):
            r = dp.solve_dp(ht.matrices, ht.bin_centers, seasonal_profile, params, 2.0, N_S=n)
            print(f"    N_S={n:3d}  DP ${r.rho_day:.3f}/day")

    print("\n  NOTE: ρ_day is the DP's IN-MODEL expected profit/day for a representative "
          "weekday.\n  The realised out-of-sample V^DP (backtest the DP offer curve on real "
          "prices), reserves/ψ_up (Q2), the duration sweep (Q3), the tail recalibration, and "
          "the §V.26 capture-rate prong are the next Stage 4 steps.")


def main():
    full = "--full" in sys.argv
    date_from, date_to = FULL if full else DEMO
    run(date_from, date_to, durations=(1.0, 2.0, 4.0) if full else (2.0,))


if __name__ == "__main__":
    main()
