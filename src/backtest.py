"""
Walk-forward backtest harness (Stage 2 — the simulation environment).

Marches through the price series one 15-minute interval at a time. At each
interval t it hands the policy ONLY the realised past (prices[:t], mcpc[:t]),
receives a pre-committed decision, clears it against the realised price[t],
accrues realised profit (energy arbitrage + reserve capacity revenue − degradation),
and updates the state of charge. No policy ever sees the present or future when
deciding — the no-lookahead property is structural, and the tests confirm a
decision at t is invariant to prices[t:].

The returned decision log is the seed of the project's live decision log.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.policies import History, Policy


@dataclass
class BacktestResult:
    profit: float          # realised $ over the window (energy + reserves − degradation)
    energy_profit: float   # energy-arbitrage component
    reserve_revenue: float  # reserve-capacity component
    soc: np.ndarray        # (T+1,) state of charge, MWh
    c: np.ndarray
    d: np.ndarray
    prices: np.ndarray
    psi_up: np.ndarray     # (T,) causal shadow price on the headroom constraint
    log: pd.DataFrame


def run_backtest(prices, policy: Policy, params, E_max, s_init=0.0, mcpc=None,
                 timestamps=None) -> BacktestResult:
    prices = np.asarray(prices, dtype=float)
    mcpc = {k: np.asarray(v, float) for k, v in (mcpc or {}).items()}
    T = len(prices)
    dt, eta_c, eta_d, c_deg = params.dt, params.eta_c, params.eta_d, params.c_deg
    up = getattr(policy, "product_set", {}).get("up", [])
    tau = params.tau

    soc = np.empty(T + 1)
    soc[0] = float(s_init)
    c = np.zeros(T)
    d = np.zeros(T)
    psi = np.zeros(T)
    energy_profit = 0.0
    reserve_revenue = 0.0
    rows = []

    for t in range(T):
        hist = History(prices[:t], {k: v[:t] for k, v in mcpc.items()})
        decision = policy.decide(soc[t], hist, E_max, params)
        ct, dt_ = decision.dispatch(prices[t], soc[t], params, E_max)
        u = getattr(decision, "u_plan", {}) or {}
        psi[t] = getattr(decision, "psi_up", 0.0)

        soc[t + 1] = soc[t] + (eta_c * ct - dt_ / eta_d) * dt
        e_step = prices[t] * (dt_ - ct) * dt - c_deg * (ct + dt_) * dt
        r_step = sum(float(mcpc[k][t]) * float(u.get(k, 0.0))
                     for k in u if k in mcpc) * dt
        energy_profit += e_step
        reserve_revenue += r_step
        c[t], d[t] = ct, dt_

        # reserve commitments must be backed by held charge (EH-up): the LP
        # guaranteed this at the true s_init, so executing exactly must preserve it.
        req = (1.0 / eta_d) * sum(tau[k] * float(u.get(k, 0.0)) for k in up)
        assert soc[t + 1] >= req - 1e-6, (
            f"reserve headroom violated at t={t}: SOC {soc[t+1]:.4f} < required {req:.4f}")

        rows.append({
            "t": t, "ts": timestamps[t] if timestamps is not None else t,
            "price": prices[t], "soc_pre": soc[t], "c": ct, "d": dt_,
            "u_up": float(sum(u.get(k, 0.0) for k in up)),
            "psi_up": psi[t], "soc_post": soc[t + 1],
            "energy_profit": e_step, "reserve_revenue": r_step,
            "step_profit": e_step + r_step,
        })

    assert soc.min() > -1e-9, f"SOC went negative: {soc.min()}"
    assert soc.max() < E_max + 1e-9, f"SOC exceeded E_max: {soc.max()} > {E_max}"

    return BacktestResult(
        profit=float(energy_profit + reserve_revenue),
        energy_profit=float(energy_profit),
        reserve_revenue=float(reserve_revenue),
        soc=soc, c=c, d=d, prices=prices, psi_up=psi,
        log=pd.DataFrame(rows),
    )
