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


def _post_warmup_mask(panel, min_train_months=2):
    """Boolean mask of the intervals the walk-forward DP actually TRADES (post warm-up)."""
    ym = panel["ts"].dt.to_period("M")
    months = list(ym.drop_duplicates())
    return (ym >= months[min_train_months]).to_numpy()


def _bootstrap_ci(daily, n=4000, block=5, seed=0):
    """Stationary block bootstrap (§VIII.5b) 95% CI on the SUM of a daily P&L series, with
    geometric block length (mean `block`) to preserve serial dependence. Seeded → reproducible."""
    d = np.asarray(daily, float)
    N = len(d)
    if N < 3:
        return float(d.sum()), float(d.sum())
    rng = np.random.RandomState(seed)
    p = 1.0 / block
    sims = np.empty(n)
    for s in range(n):
        out, i = [], 0
        while i < N:
            start = rng.randint(N)
            L = rng.geometric(p)
            out.extend(d[(start + k) % N] for k in range(min(L, N - i)))
            i += L
        sims[s] = np.sum(out[:N])
    lo, hi = np.percentile(sims, [2.5, 97.5])
    return float(lo), float(hi)


def realized_ladder(date_from, date_to, E=2.0, N_S=200, n_bins=12):
    """The leak-free value-of-foresight ladder (§IV.13). Reports capture on BOTH the
    full-window denominator (conservative — the DP holds through the 2-month warm-up) AND
    the matched traded-period denominator, and a do-nothing = $0 floor row."""
    params = BatteryParams()
    panel = ingest.build_panel(date_from, date_to)
    prices = panel["price"].to_numpy(float)
    n_days = panel["date"].nunique()
    ceiling = solve(prices, {}, E, params, ENERGY_ONLY).objective
    r = _wf_backtest(panel, params, E, N_S, n_bins)
    v_dp = r.profit
    mask = _post_warmup_mask(panel)                       # traded (post-warm-up) intervals
    ceil_tr = solve(prices[mask], {}, E, params, ENERGY_ONLY).objective
    v_dp_tr = r.log["step_profit"].to_numpy()[mask].sum()
    # daily P&L (traded window) -> bootstrap CI on V^DP
    import pandas as pd
    lg = r.log.iloc[np.where(mask)[0]].copy()
    lg["d"] = pd.to_datetime(lg["ts"]).dt.date
    daily = lg.groupby("d")["step_profit"].sum().to_numpy()
    lo, hi = _bootstrap_ci(daily)
    m = MPC_2H
    print(f"\n=== (A) leak-free value-of-foresight ladder @ {E:.0f}h ({n_days} days) ===")
    print(f"  ceiling (perfect-foresight LP):     ${ceiling:>10,.0f}   100%")
    print(f"  MPC, perfect forecast (clairvoyant):${m['clair']:>10,.0f}   {m['clair']/ceiling:>4.0%}")
    print(f"  >>> DP (optimal causal, WALK-FORWARD):${v_dp:>9,.0f}   {v_dp/ceiling:>4.0%} full")
    print(f"      DP capture on the MATCHED traded window (post warm-up): {v_dp_tr/ceil_tr:>4.0%} "
          f"(V^DP ${v_dp_tr:,.0f} / ceiling ${ceil_tr:,.0f})")
    print(f"      DP daily-bootstrap 95% CI on V^DP (traded): [${lo:,.0f}, ${hi:,.0f}]")
    print(f"  do-nothing (never trade):           ${0:>10,.0f}    0%   <- the true floor")
    print(f"  MPC, learned forecast (Stage 3):    ${m['learned']:>10,.0f}")
    print(f"  MPC, same-hour-last-week (Stage 2): ${m['naive']:>10,.0f}")
    print(f"  naive threshold floor:              ${m['floor']:>10,.0f}")
    print(f"\n  §IV.13:  value of information (ceiling-V^DP) = ${ceiling - v_dp:>8,.0f}")
    print(f"           option value (V^DP - learned MPC)  = ${v_dp - m['learned']:>8,.0f}  "
          f"(positive; but INFLATED — the MPC ate warm-up losses the DP was exempted from; the "
          f"honest comparison recomputes the MPC over the matched traded window — a Stage 5 item)")
    print("  V^DP is walk-forward / leak-free (WalkForwardDPPolicy scramble test in tests/test_dp.py).")
    return {"ceiling": ceiling, "v_dp": v_dp, "v_dp_tr": v_dp_tr, "ceil_tr": ceil_tr}


def duration_sweep(date_from, date_to, durations=(0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0),
                   n_bins=12, nodes_per_hour=100):
    """Q3 — V^PF(E) & V^DP(E) (walk-forward) + κ(E). N_S SCALES WITH DURATION (≈constant ΔS)
    so the grid error is duration-invariant (§IV.8) — else long-E rows are grid-depressed."""
    params = BatteryParams()
    panel = ingest.build_panel(date_from, date_to)
    prices = panel["price"].to_numpy(float)
    n_days = panel["date"].nunique()
    print(f"\n=== Q3 — duration-value curves ({n_days} days, energy-only, walk-forward, "
          f"ΔS-constant grid ~{nodes_per_hour} nodes/h) ===")
    print(f"  {'E(h)':>5}{'N_S':>6}{'V_PF $':>10}{'V_DP $':>10}{'capture':>9}{'dV_DP/dE':>11}")
    prev = None
    rows = []
    for E in durations:
        N_S = max(50, int(round(nodes_per_hour * E)))
        v_pf = solve(prices, {}, E, params, ENERGY_ONLY).objective
        v_dp = _wf_backtest(panel, params, E, N_S, n_bins).profit
        marg = (v_dp - prev[1]) / (E - prev[0]) if prev else float("nan")
        print(f"  {E:>5.1f}{N_S:>6}{v_pf:>10,.0f}{v_dp:>10,.0f}{v_dp / v_pf:>8.0%}{marg:>11,.0f}")
        rows.append((E, v_pf, v_dp))
        prev = (E, v_dp)
    print("  do-nothing floor = $0: at 0.5h V^DP < 0, i.e. the causal policy is dominated by "
          "inaction there (round trips positioning for spikes that don't arrive).")
    return rows


def capture_rate_prong(date_from, date_to, E=2.0, N_S=200, n_bins_grid=(10, 12, 14)):
    """§V.26 capture-rate prong, WALK-FORWARD, SWEPT OVER n_bins — the empirical-vs-learned
    margin is within the discretisation swing (sign flips at n_bins=10), so this reports the
    sweep rather than a single 'adopt' verdict."""
    params = BatteryParams()
    panel = ingest.build_panel(date_from, date_to)
    prices = panel["price"].to_numpy(float)
    v_pf = solve(prices, {}, E, params, ENERGY_ONLY).objective
    print(f"\n=== §V.26 capture-rate prong @ {E:.0f}h (walk-forward, n_bins sweep) ===")
    print(f"  ceiling ${v_pf:,.0f}\n  {'n_bins':>7}{'empirical $':>13}{'learned $':>11}{'emp-lrn':>9}")
    flips = 0
    for nb in n_bins_grid:
        ve = _wf_backtest(panel, params, E, N_S, nb, kernel_kind="empirical").profit
        vl = _wf_backtest(panel, params, E, N_S, nb, kernel_kind="learned").profit
        flips += (ve < vl)
        print(f"  {nb:>7}{ve:>13,.0f}{vl:>11,.0f}{ve-vl:>9,.0f}")
    print(f"  READING: empirical ≈ learned — the margin (~$190/1.4pp) is within the "
          f"discretisation swing and the sign FLIPS across n_bins ({flips}/{len(n_bins_grid)} "
          f"learned-wins). NOT separable without Stage-5 CIs; the earlier 'adopt empirical, "
          f"confirmed' is downgraded to 'empirical marginally ahead at the default bins'.")


def q2_psi_up(date_from, date_to, E=2.0, N_S=200, n_bins=12, rhos=(0.0, 0.05, 0.15)):
    """Q2 — the causal ψ_up. Reports BOTH: (i) the median sensitivity via the hour-mean-MCPC
    co-optimised DP over a ρ_k sweep, and (ii) THE TAIL from the REALISED INTERVAL MCPC at the
    EXECUTED post-decision SOC (fixes the two ways the first cut under-stated the tail — B2
    smoothing and reading ψ at the planned rather than executed action)."""
    from src import reserves
    params = BatteryParams()
    panel = ingest.build_panel(date_from, date_to)
    tau = np.array([params.tau[k] for k in reserves.UP_PRODUCTS])
    a = tau / params.eta_d
    prices = panel["price"].to_numpy(float)

    vv = (np.array([3.0, 3.0, 3.0]) - params.c_deg * 0.05 * tau) * params.dt
    oks = [reserves.validate_psi(Ei, 1.0, vv, a)[3] for Ei in (0.1, 0.3, 0.5, 0.8, 1.2)]
    print(f"\n=== Q2 — causal ψ_up (co-optimised reserve DP, walk-forward) ===")
    print(f"  C1 validation (ψ_up = FD of reserve value): {sum(oks)}/{len(oks)} points pass")

    print(f"  (i) median sensitivity, hour-mean MCPC, ρ_k sweep:")
    print(f"  {'ρ_k':>6}{'median':>10}{'p90':>9}{'p99':>9}{'max':>9}{'binds%':>9}")
    for rho in rhos:
        psi = _wf_backtest(panel, params, E, N_S, n_bins, reserves=True, rho=rho).log["psi_up"].to_numpy(float)
        psi = psi[psi >= 0]
        tol = 0.01 * np.median(np.abs(prices))
        print(f"  {rho:>6.2f}{np.median(psi):>10.3f}{np.percentile(psi,90):>9.3f}"
              f"{np.percentile(psi,99):>9.3f}{psi.max():>9.2f}{(psi>tol).mean()*100:>8.1f}%")

    # (ii) THE TAIL — realised interval MCPC at the executed SOC (ρ=0.05)
    r = _wf_backtest(panel, params, E, N_S, n_bins, reserves=True, rho=0.05)
    log = r.log
    mcpc = {k: panel[k].to_numpy(float) for k in reserves.UP_PRODUCTS}
    soc_post = log["soc_post"].to_numpy(float)
    netd = (log["d"].to_numpy(float) - log["c"].to_numpy(float))
    psi_iv = np.zeros(len(log))
    for t in range(len(log)):
        v_t = (np.array([mcpc[k][t] for k in reserves.UP_PRODUCTS]) - params.c_deg * 0.05 * tau) * params.dt
        _, psi_iv[t] = reserves.reserve_lp(soc_post[t] - params.s_min, params.p_bar - netd[t], v_t, a)
    pos = psi_iv[psi_iv > 0]
    print(f"\n  (ii) TAIL, realised INTERVAL MCPC at the EXECUTED SOC (ρ=0.05):")
    print(f"      median ${np.median(psi_iv):.3f}  p99 ${np.percentile(psi_iv,99):.3f}  "
          f"max ${psi_iv.max():.2f}  binds {(psi_iv>tol).mean()*100:.1f}%")
    print(f"  vs Stage 0 perfect-foresight floor (median $0.015, p99 $1.47, max $32.75). "
          f"Interval MCPC restores the scarcity tail the hour-mean smoothed away; the median "
          f"exceeding the Stage 0 floor (Decision 19) holds only at ρ=0 and is razor-thin.")


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
