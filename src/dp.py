"""
Stage 4 — the periodic dynamic program (the headline: the optimal causal policy).

This solves the average-reward Bellman equation (§IV.1) on the 24-periodic (here
H=96 quarter-of-day) structure, using the post-decision-state formulation (§IV.2)
and GRID-ALIGNED actions (§IV.8b) so the DP is exact on the SOC grid with no
interpolation. The exogenous price process is the hour-indexed Markov chain on the
deseasonalised residual built in Stage 3 (src/markov); the reward reconstructs the
actual price P = seasonal(h) + residual-bin-centre (plan "STAGE 4 updates" item 3).

State: (h, j, b) — time-of-day index h∈0..H-1, SOC grid index j∈0..N_S, residual
bin b∈0..N_b-1. Value function V[h] has shape (N_S+1, N_b).

Action: an integer number of SOC grid-steps m (net), grid-aligned so S⁺ = S + mΔS
lands exactly on a grid node (§IV.8b). Charge (m>0): c = mΔS/(η_c Δt); discharge
(m<0): d = |m|ΔS η_d/Δt; hold (m=0). Feasible when c,d ≤ p̄ and 0 ≤ j+m ≤ N_S.

Post-decision value (§IV.2): Ṽ_h(S⁺,b) = Σ_b' K_h[b,b'] V_{h+1}(S⁺,b') — computed
ONCE per (h) as EK = V_{h+1} @ K_hᵀ, then reused across all actions. The marginal
value of stored energy μ_h = ∂Ṽ_h/∂S⁺ is the discrete S-derivative of EK — the
opportunity cost, the decision threshold, and the bid price (§IV.2), and it must be
non-increasing in S⁺ (§IV.7 corollary) — a correctness test, not an assumption.

Average-reward relative value iteration (§IV.9): synchronous backups
V_new[h] = T_h V[h+1]; at the periodic fixed point V_new − V = ρ·1 (a constant
per-interval gain), so ρ_interval = that constant and ρ_day = H·ρ_interval is the
optimal profit per day. Anchoring at a reference state keeps the iterates bounded.
No terminal condition is needed — the fixed point is self-consistent across the day
boundary by construction (§IV.9).

Verification (the Stage 4 gate): Bellman residual < ε at every (h,j,b); μ monotone
non-increasing in S⁺; DP↔LP agreement on a deterministic price path (ρ_day equals
the perfect-foresight LP's cyclic per-day objective); grid convergence over N_S.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from src.oracle import BatteryParams


@dataclass
class DPResult:
    V: np.ndarray            # (H, N_S+1, N_b) relative value function (bias)
    policy: np.ndarray       # (H, N_S+1, N_b) optimal action m (grid-steps)
    mu: np.ndarray           # (H, N_S+1, N_b) marginal value of stored energy ($/MWh)
    rho_interval: float      # average reward per 15-min interval ($)
    rho_day: float           # average reward per day ($) = H * rho_interval
    E_max: float
    N_S: int
    dt: float
    S_grid: np.ndarray       # (N_S+1,) SOC nodes (MWh)
    bellman_residual: float  # max |ρ + V - T V| after convergence
    iters: int
    span_history: list = field(default_factory=list)
    actions: np.ndarray = None            # (A,) grid-step action set
    reserve_psi: np.ndarray = None        # (H, N_S+1, A) ψ_up at (h, post-decision node, action)
    reserve_rho_day: float = 0.0          # reserve income component of ρ_day ($)


def _admissible_actions(params: BatteryParams, E_max: float, N_S: int) -> np.ndarray:
    """Integer grid-step moves m (net SOC change in units of ΔS) whose implied
    power is within [0, p̄] on the relevant leg (§IV.8b)."""
    dS = E_max / N_S
    m_charge_max = int(np.floor(params.p_bar * params.eta_c * params.dt / dS + 1e-9))
    m_dis_max = int(np.floor(params.p_bar * params.eta_d * params.dt / dS + 1e-9))
    return np.arange(-m_dis_max, m_charge_max + 1)


def _net_discharge(actions, params, E_max, N_S):
    """Net discharge (d-c, MW) per action m — sets the up-reserve power budget p̄-(d-c)."""
    dS = E_max / N_S
    nd = np.zeros(len(actions))
    for a, m in enumerate(actions):
        if m > 0:
            nd[a] = -(m * dS / (params.eta_c * params.dt))     # charging: net discharge < 0
        elif m < 0:
            nd[a] = -m * dS * params.eta_d / params.dt          # discharging
    return nd


def _interp_fixedP(gridvals, E_grid, P_grid, E_query, P):
    """Bilinear lookup of a (nE,nP) table at all E in E_query for a fixed P."""
    colP = np.array([np.interp(P, P_grid, gridvals[i]) for i in range(len(E_grid))])
    return np.interp(E_query, E_grid, colP)


def _reserve_by_action(reserve_tables, actions, params, E_max, N_S, S_grid, H):
    """(H, N_S+1, A) reserve VALUE and ψ_up at (time-of-day h, post-decision node S⁺, action)
    — A2: the power budget p̄-(d-c) depends on the action, the energy budget on S⁺. The
    reserve tables are hour-indexed (24); expand to the DP's H quarter-of-day indices."""
    rval, rpsi, E_grid, P_grid = reserve_tables          # rval, rpsi: (24, nE, nP)
    nd = _net_discharge(actions, params, E_max, N_S)
    val = np.zeros((H, N_S + 1, len(actions)))
    psi = np.zeros((H, N_S + 1, len(actions)))
    for a in range(len(actions)):
        pb = params.p_bar - nd[a]
        for h in range(H):
            hour = h * 24 // H
            val[h, :, a] = _interp_fixedP(rval[hour], E_grid, P_grid, S_grid, pb)
            psi[h, :, a] = _interp_fixedP(rpsi[hour], E_grid, P_grid, S_grid, pb)
    return val, psi


def _reward_table(P_hb: np.ndarray, actions: np.ndarray, params: BatteryParams,
                  E_max: float, N_S: int) -> np.ndarray:
    """Reward r(h,b,m) ($ per interval) for every (h, b, action). Depends on (h,b)
    only through the reconstructed price P_hb; independent of the SOC node j."""
    dS = E_max / N_S
    eta_c, eta_d, c_deg = params.eta_c, params.eta_d, params.c_deg
    H, N_b = P_hb.shape
    R = np.zeros((H, N_b, len(actions)))
    for a, m in enumerate(actions):
        if m > 0:       # charge: c = mΔS/(η_c Δt); reward = -(P + c_deg) c Δt
            c = m * dS / (eta_c * params.dt)
            R[:, :, a] = -(P_hb + c_deg) * c * params.dt
        elif m < 0:     # discharge: d = |m|ΔS η_d/Δt; reward = (P - c_deg) d Δt
            d = -m * dS * eta_d / params.dt
            R[:, :, a] = (P_hb - c_deg) * d * params.dt
        # m == 0 -> hold -> 0
    return R


def solve_dp(kernel_by_hour: np.ndarray, resid_center: np.ndarray, seasonal: np.ndarray,
             params: BatteryParams, E_max: float, N_S: int = 100, *,
             max_iter: int = 4000, tol: float = 1e-7,
             ref: tuple = (0, 0), reserve_tables=None) -> DPResult:
    """Solve the periodic average-reward DP.

    kernel_by_hour : (24, N_b, N_b) row-stochastic residual transition matrices.
    resid_center   : (N_b,) representative residual per bin ($/MWh).
    seasonal       : (H,) representative price level per time-of-day index ($/MWh).
    Reconstructed price P[h,b] = seasonal[h] + resid_center[b].
    reserve_tables : optional (value, psi, E_grid, P_grid) from src.reserves — if given,
        the reserve VALUE is added to the reward so the DP CO-OPTIMISES energy + reserves
        (holds charge for reserves), and the reserve ψ_up is stored for Q2 extraction.
    """
    seasonal = np.asarray(seasonal, float)
    resid_center = np.asarray(resid_center, float)
    H = len(seasonal)
    N_b = len(resid_center)
    dS = E_max / N_S
    S_grid = np.linspace(0.0, E_max, N_S + 1)

    # per-h kernel (expand hour-indexed -> H time-of-day indices)
    K = np.array([kernel_by_hour[h * 24 // H] for h in range(H)])   # (H, N_b, N_b)
    P_hb = seasonal[:, None] + resid_center[None, :]                # (H, N_b)
    actions = _admissible_actions(params, E_max, N_S)
    R = _reward_table(P_hb, actions, params, E_max, N_S)            # (H, N_b, A)
    A = len(actions)
    jref, bref = ref

    # reserve value/ψ_up per (h, post-decision node, action) — added to the reward so the
    # DP holds charge for reserves (A2/B2/C1); zero if no reserves.
    rv = rpsi = None
    if reserve_tables is not None:
        rv, rpsi = _reserve_by_action(reserve_tables, actions, params, E_max, N_S, S_grid, H)

    def bellman_row(h, Vnext):
        """(T_h Vnext)(·) over all (j,b): max over grid-aligned actions."""
        EK = Vnext @ K[h].T                            # (N_S+1, N_b) post-decision value
        best = np.full((N_S + 1, N_b), -np.inf)
        for a, m in enumerate(actions):
            lo, hi = max(0, -m), min(N_S, N_S - m)     # valid j: 0 <= j+m <= N_S
            if lo > hi:
                continue
            jp = np.arange(lo, hi + 1) + m
            cand = R[h, :, a][None, :] + EK[jp]
            if rv is not None:
                cand = cand + rv[h, jp, a][:, None]    # + reserve income at S⁺ (co-opt)
            cur = best[lo:hi + 1]
            np.maximum(cur, cand, out=cur)
        return best, EK

    # Relative value iteration via a backward GAUSS-SEIDEL day-sweep: each sweep
    # propagates a full day of look-ahead (V[h] uses the freshly-updated V[h+1]),
    # so convergence is a few tens of DAY-sweeps rather than thousands of interval
    # backups. V[0] is the day-boundary value; V[H-1]'s successor is the prior V[0].
    V = np.zeros((H, N_S + 1, N_b))
    span_hist = []
    rho_day = 0.0
    for it in range(max_iter):
        V0_prev = V[0].copy()
        Vpass = np.empty_like(V)
        for h in reversed(range(H)):
            Vnext = Vpass[h + 1] if h < H - 1 else V[0]   # day boundary -> prior V[0]
            Vpass[h], _ = bellman_row(h, Vnext)
        d0 = Vpass[0] - V0_prev
        rho_day = float(np.mean(d0))
        sp = float(d0.max() - d0.min())               # span of the daily increment
        span_hist.append(sp)
        Vpass -= Vpass[0][jref, bref]                  # anchor to keep iterates bounded
        V = Vpass
        if sp < tol:
            break
    rho_interval = rho_day / H

    # policy and μ from the converged V. The convergence certificate for the
    # average-reward fixed point is the span of the daily increment D(V0)-V0 (it -> a
    # constant = ρ_day, so its span -> 0); that final span is the Bellman residual here.
    policy = np.zeros((H, N_S + 1, N_b), int)
    mu = np.zeros((H, N_S + 1, N_b))
    reserve_psi = np.zeros((H, N_S + 1, N_b)) if rpsi is not None else None
    for h in range(H):
        Vnext = V[(h + 1) % H]
        EK = Vnext @ K[h].T
        best = np.full((N_S + 1, N_b), -np.inf)
        arg = np.zeros((N_S + 1, N_b), int)
        argpsi = np.zeros((N_S + 1, N_b)) if rpsi is not None else None
        for a, m in enumerate(actions):
            lo, hi = max(0, -m), min(N_S, N_S - m)
            if lo > hi:
                continue
            jp = np.arange(lo, hi + 1) + m
            cand = R[h, :, a][None, :] + EK[jp]
            if rv is not None:
                cand = cand + rv[h, jp, a][:, None]
            better = cand > best[lo:hi + 1]
            best[lo:hi + 1] = np.where(better, cand, best[lo:hi + 1])
            arg[lo:hi + 1] = np.where(better, m, arg[lo:hi + 1])
            if rpsi is not None:
                argpsi[lo:hi + 1] = np.where(better, rpsi[h, jp, a][:, None], argpsi[lo:hi + 1])
        policy[h] = arg
        if reserve_psi is not None:
            reserve_psi[h] = argpsi
        # μ_h = ∂Ṽ/∂S⁺ (discrete forward difference of the post-decision value EK)
        mu[h, 1:] = (EK[1:] - EK[:-1]) / dS
        mu[h, 0] = mu[h, 1]

    return DPResult(V=V, policy=policy, mu=mu, rho_interval=rho_interval,
                    rho_day=rho_day, E_max=E_max, N_S=N_S, dt=params.dt,
                    S_grid=S_grid, bellman_residual=(span_hist[-1] if span_hist else 0.0),
                    iters=len(span_hist), span_history=span_hist,
                    actions=actions, reserve_psi=reserve_psi)


# --------------------------------------------------------------------------- #
# Verification (the Stage 4 gate)                                             #
# --------------------------------------------------------------------------- #
def mu_monotone_violation(res: DPResult) -> float:
    """Max positive Δμ along S⁺ (should be ~0: μ non-increasing in S⁺, §IV.7)."""
    d = np.diff(res.mu, axis=1)                        # μ[j+1]-μ[j]
    return float(np.max(d)) if d.size else 0.0


def dp_vs_lp_deterministic(price_path: np.ndarray, params: BatteryParams,
                           E_max: float, N_S: int = 200) -> dict:
    """DP↔LP agreement on a DETERMINISTIC periodic price path (§IV.9 pt 3 / §IV.12):
    a single-bin (degenerate) kernel makes the DP's ρ_day equal the perfect-foresight
    LP's cyclic per-day objective, to discretisation error. THE core correctness test."""
    from src import oracle
    H = len(price_path)
    kernel = np.ones((24, 1, 1))                       # degenerate: one residual bin
    res = solve_dp(kernel, np.array([0.0]), price_path, params, E_max, N_S=N_S)
    lp = oracle.solve(price_path, {}, E_max, params, oracle.ENERGY_ONLY, cyclic=True)
    return {"dp_rho_day": res.rho_day, "lp_per_day": lp.objective,
            "abs_diff": abs(res.rho_day - lp.objective),
            "rel_diff": abs(res.rho_day - lp.objective) / (abs(lp.objective) + 1e-9),
            "bellman_residual": res.bellman_residual,
            "mu_monotone_violation": mu_monotone_violation(res)}


# --------------------------------------------------------------------------- #
# Self-test on a deterministic diurnal price (no ERCOT data needed)           #
# --------------------------------------------------------------------------- #
def _synthetic_price(H=96):
    q = np.arange(H)
    return 40.0 + 35.0 * np.sin((q - 40) / H * 2 * np.pi)   # cheap night, rich evening


if __name__ == "__main__":
    params = BatteryParams(c_deg=10.0)
    P = _synthetic_price()
    print("DP self-test — deterministic diurnal price, energy-only\n")
    for E in (1.0, 2.0, 4.0):
        d = dp_vs_lp_deterministic(P, params, E, N_S=200)
        print(f"  E={E:.0f}h  DP ρ/day=${d['dp_rho_day']:7.2f}  LP/day=${d['lp_per_day']:7.2f}  "
              f"reldiff={d['rel_diff']:.2e}  bellman={d['bellman_residual']:.1e}  "
              f"μ-mono-viol={d['mu_monotone_violation']:.1e}")
    print("\n  grid convergence (E=2h):")
    for N_S in (50, 100, 200, 400):
        d = dp_vs_lp_deterministic(P, params, 2.0, N_S=N_S)
        print(f"    N_S={N_S:3d}  DP ρ/day=${d['dp_rho_day']:7.3f}  reldiff vs LP={d['rel_diff']:.2e}")
