"""
Stage 4 — periodic dynamic program: the LEAK-FREE headline results.

Everything here uses the walk-forward DP (src.policies.WalkForwardDPPolicy): the kernel,
seasonal, bin edges, reserve prices and the DP solve are ALL re-fit online by calendar
month on strictly-prior data (§VIII.3), so V^DP is genuinely out-of-sample. (An earlier
version used a full-window in-sample kernel, which inflated V^DP ~2.4x — fixed here.)

Deliverables:
  realized_ladder     — V^DP in the value-of-foresight ladder (§IV.13)
  duration_sweep      — Q3: V^PF(E) & V^DP(E) + capture-rate curve
  capture_rate_prong  — §V.26: empirical vs learned kernel, walk-forward realised capture
  q2_psi_up           — Q2: co-optimised reserve DP, causal ψ_up, ρ_k sweep, C1 validation

    python -m src.stage4_run --full
"""

from __future__ import annotations

import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore", message="invalid value encountered in reduce")

from src import ingest
from src.backtest import run_backtest
from src.oracle import ENERGY_ONLY, BatteryParams, solve
from src.policies import WalkForwardDPPolicy

FULL = ("2025-12-05", "2026-06-20")
DEMO = ("2025-12-05", "2026-04-05")

# Stage 2/3 walk-forward MPC comparators on the identical full window (documented,
# reproduced bit-for-bit by the Stage 3 model-risk review) — cited so the slow MPC
# backtests are not recomputed each run.
MPC_2H = {"ceiling": 13206, "clair": 12847, "learned": -303, "naive": -3453, "floor": -5267}


def _wf_backtest(panel, params, E, N_S=200, n_bins=12, reserves=False, rho=0.05,
                 kernel_kind="empirical"):
    prices = panel["price"].to_numpy(float)
    ts = panel["ts"].to_numpy()
    pol = WalkForwardDPPolicy(panel, params, E, N_S=N_S, n_bins=n_bins,
                              reserves=reserves, rho=rho, kernel_kind=kernel_kind)
    return run_backtest(prices, pol, params, E, s_init=0.0, timestamps=ts)


def realized_ladder(date_from, date_to, E=2.0, N_S=200, n_bins=12):
    """The leak-free value-of-foresight ladder (§IV.13). V^DP is the walk-forward DP;
    the MPC comparators are the documented Stage 2/3 walk-forward numbers on this window."""
    params = BatteryParams()
    panel = ingest.build_panel(date_from, date_to)
    prices = panel["price"].to_numpy(float)
    n_days = panel["date"].nunique()
    ceiling = solve(prices, {}, E, params, ENERGY_ONLY).objective
    v_dp = _wf_backtest(panel, params, E, N_S, n_bins).profit
    m = MPC_2H
    print(f"\n=== (A) leak-free value-of-foresight ladder @ {E:.0f}h ({n_days} days) ===")
    print(f"  ceiling (perfect-foresight LP):     ${ceiling:>10,.0f}   100%")
    print(f"  MPC, perfect forecast (clairvoyant):${m['clair']:>10,.0f}   {m['clair']/ceiling:>4.0%}")
    print(f"  >>> DP (optimal causal, WALK-FORWARD):${v_dp:>9,.0f}   {v_dp/ceiling:>4.0%}")
    print(f"  MPC, learned forecast (Stage 3):    ${m['learned']:>10,.0f}")
    print(f"  MPC, same-hour-last-week (Stage 2): ${m['naive']:>10,.0f}")
    print(f"  naive threshold floor:              ${m['floor']:>10,.0f}")
    print(f"\n  §IV.13:  value of information (ceiling-V^DP) = ${ceiling - v_dp:>8,.0f}")
    print(f"           option value (V^DP - learned MPC)  = ${v_dp - m['learned']:>8,.0f}  "
          f"({'DP beats the CE MPC — positive option value' if v_dp > m['learned'] else 'DP does NOT beat the MPC'})")
    print("  V^DP is walk-forward / leak-free (kernel re-fit per fold, no lookahead — test-pinned).")
    return {"ceiling": ceiling, "v_dp": v_dp, "clair": m["clair"], "learned": m["learned"]}


def duration_sweep(date_from, date_to, durations=(0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0),
                   N_S=200, n_bins=12):
    """Q3 — V^PF(E) & V^DP(E) (walk-forward) + the capture-rate curve κ(E)."""
    params = BatteryParams()
    panel = ingest.build_panel(date_from, date_to)
    prices = panel["price"].to_numpy(float)
    n_days = panel["date"].nunique()
    print(f"\n=== Q3 — duration-value curves ({n_days} days, energy-only, walk-forward) ===")
    print(f"  {'E(h)':>5}{'V_PF $':>10}{'V_DP $':>10}{'capture':>9}{'dV_DP/dE':>11}")
    prev = None
    rows = []
    for E in durations:
        v_pf = solve(prices, {}, E, params, ENERGY_ONLY).objective
        v_dp = _wf_backtest(panel, params, E, N_S, n_bins).profit
        marg = (v_dp - prev[1]) / (E - prev[0]) if prev else float("nan")
        print(f"  {E:>5.1f}{v_pf:>10,.0f}{v_dp:>10,.0f}{v_dp / v_pf:>8.0%}{marg:>11,.0f}")
        rows.append((E, v_pf, v_dp))
        prev = (E, v_dp)
    return rows


def capture_rate_prong(date_from, date_to, E=2.0, N_S=200, n_bins=12):
    """§V.26 capture-rate prong, WALK-FORWARD: empirical vs learned kernel, realised capture."""
    params = BatteryParams()
    panel = ingest.build_panel(date_from, date_to)
    prices = panel["price"].to_numpy(float)
    v_pf = solve(prices, {}, E, params, ENERGY_ONLY).objective
    print(f"\n=== §V.26 capture-rate prong @ {E:.0f}h (walk-forward) ===")
    print(f"  ceiling ${v_pf:,.0f}\n  {'kernel':12}{'V_DP $':>10}{'capture':>9}")
    best = (None, -np.inf)
    for kind in ("empirical", "learned"):
        v = _wf_backtest(panel, params, E, N_S, n_bins, kernel_kind=kind).profit
        print(f"  {kind:12}{v:>10,.0f}{v / v_pf:>8.0%}")
        if v > best[1]:
            best = (kind, v)
    print(f"  ADOPT: {best[0]} kernel (best realised walk-forward capture).")
    return best


def q2_psi_up(date_from, date_to, E=2.0, N_S=200, n_bins=12, rhos=(0.0, 0.05, 0.15)):
    """Q2 — the causal ψ_up (cost of RTC+B SOC enforcement), from the CO-OPTIMISED reserve
    DP (A2/B2/C1), walk-forward, with a ρ_k sensitivity sweep. The C1 identity (ψ_up = the
    finite-difference of the reserve value) is validated on the reserve LP."""
    from src import reserves
    params = BatteryParams()
    panel = ingest.build_panel(date_from, date_to)

    # C1 validation gate (ψ_up = dValue/dE on the reserve LP)
    tau = np.array([params.tau[k] for k in reserves.UP_PRODUCTS])
    a = tau / params.eta_d
    v = (np.array([3.0, 3.0, 3.0]) - params.c_deg * 0.05 * tau) * params.dt
    oks = [reserves.validate_psi(Ei, 1.0, v, a)[3] for Ei in (0.1, 0.3, 0.5, 0.8, 1.2)]
    print(f"\n=== Q2 — causal ψ_up (co-optimised reserve DP, walk-forward) ===")
    print(f"  C1 validation (ψ_up = FD of reserve value): {sum(oks)}/{len(oks)} points pass")

    print(f"  {'ρ_k':>6}{'median ψ':>11}{'p90':>9}{'p99':>9}{'max':>9}{'binds%':>9}")
    for rho in rhos:
        log = _wf_backtest(panel, params, E, N_S, n_bins, reserves=True, rho=rho).log
        psi = log["psi_up"].to_numpy(float)
        psi = psi[psi >= 0]
        tol = 0.01 * np.median(np.abs(panel["price"].to_numpy(float)))
        print(f"  {rho:>6.2f}{np.median(psi):>11.3f}{np.percentile(psi,90):>9.3f}"
              f"{np.percentile(psi,99):>9.3f}{psi.max():>9.2f}{(psi>tol).mean()*100:>8.1f}%")
    print("  vs Stage 0 perfect-foresight floor (median $0.015): the causal median should "
          "EXCEED it (Decision 19). B2 hour-mean MCPC smooths the ψ_up tail (a named caveat).")


def main():
    full = "--full" in sys.argv
    date_from, date_to = FULL if full else DEMO
    realized_ladder(date_from, date_to)
    if full:
        duration_sweep(date_from, date_to)
        capture_rate_prong(date_from, date_to)
        q2_psi_up(date_from, date_to)


if __name__ == "__main__":
    main()
