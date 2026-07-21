"""
Step 0 perfect-foresight LP (see docs/step0_spec.md section 2).

Plain-terms summary: given a full window of known prices, find the battery
schedule that maximizes profit, subject to physics (state of charge) and RTC+B's
energy-headroom rules. The valuable output is not the profit but the *shadow
prices* (duals): psi_up on the "hold charge to back upward reserves" rule is the
number Step 0 exists to measure.

This module has NO ERCOT dependency. Running it directly (python -m src.step0_lp)
runs a self-test on synthetic prices, which validates the solver and the
verification checks before any real data exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cvxpy as cp
import numpy as np


@dataclass
class Params:
    dt: float = 0.25          # hours per interval
    eta_c: float = 0.95       # charge efficiency
    eta_d: float = 0.95       # discharge efficiency
    c_deg: float = 25.0       # $/MWh throughput, charged on both legs
    p_bar: float = 1.0        # MW rating
    s_min: float = 0.0        # reserved floor (MWh); 0 for grid ESR
    tau: dict = field(default_factory=lambda: {   # duration req (hours), Decision 16
        "RRS": 0.5, "ECRS": 1.0, "NSPIN": 4.0, "REGUP": 0.5, "REGDN": 0.5,
    })


CONTINGENCY = {"up": ["RRS", "ECRS", "NSPIN"], "dn": []}
ALL_PRODUCTS = {"up": ["RRS", "ECRS", "NSPIN", "REGUP"], "dn": ["REGDN"]}
ENERGY_ONLY = {"up": [], "dn": []}


def solve_lp(P, mcpc, E_max, params: Params, product_set) -> dict:
    """Solve the perfect-foresight LP and return schedule + duals.

    P     : (T,) energy price, $/MWh
    mcpc  : dict product -> (T,) capacity price, $/MW-h (needed only for active products)
    E_max : MWh
    """
    P = np.asarray(P, dtype=float)
    T = len(P)
    dt, eta_c, eta_d = params.dt, params.eta_c, params.eta_d
    c_deg, p, s_min = params.c_deg, params.p_bar, params.s_min
    up, dn = product_set["up"], product_set["dn"]

    c = cp.Variable(T, nonneg=True)
    d = cp.Variable(T, nonneg=True)
    S = cp.Variable(T + 1)
    u = {k: cp.Variable(T, nonneg=True) for k in up + dn}
    Splus = S[1:]  # post-decision SOC of interval t is S[t+1]

    # objective ($). MCPC is $/MW-h, so multiply by dt (Correction 4).
    profit = cp.sum(cp.multiply(P, d - c)) * dt - c_deg * cp.sum(c + d) * dt
    for k in up + dn:
        profit = profit + cp.sum(cp.multiply(np.asarray(mcpc[k], float), u[k])) * dt

    up_sum = sum((u[k] for k in up), start=0)
    dn_sum = sum((u[k] for k in dn), start=0)

    cons = {
        "balance": (S[1:] == S[:-1] + (eta_c * c - d / eta_d) * dt),
        "soc_lo": (S >= 0),
        "soc_hi": (S <= E_max),
        "cyclic": (S[0] == S[T]),
        "c_hi": (c <= p),
        "d_hi": (d <= p),
        "phdr_up": (d - c + up_sum <= p),
        "phdr_dn": (c - d + dn_sum <= p),
    }
    if up:
        cons["eh_up"] = (Splus - s_min >= (1.0 / eta_d) * sum(params.tau[k] * u[k] for k in up))
    if dn:
        cons["eh_dn"] = (E_max - Splus >= eta_c * sum(params.tau[k] * u[k] for k in dn))

    prob = cp.Problem(cp.Maximize(profit), list(cons.values()))
    prob.solve(solver=cp.HIGHS)

    def dv(name):
        return np.asarray(cons[name].dual_value) if name in cons else None

    return {
        "status": prob.status,
        "objective": float(prob.value),
        "E_max": E_max,
        "T": T,
        "S": np.asarray(S.value),
        "c": np.asarray(c.value),
        "d": np.asarray(d.value),
        "u": {k: np.asarray(u[k].value) for k in up + dn},
        "product_set": product_set,
        # duals (magnitudes; signs calibrated in verify_recursion)
        "mu": dv("balance"),
        "lam_lo": dv("soc_lo"),
        "lam_hi": dv("soc_hi"),
        "omega_up": dv("phdr_up"),
        "omega_dn": dv("phdr_dn"),
        "psi_up": dv("eh_up") if up else np.zeros(T),
        "psi_dn": dv("eh_dn") if dn else np.zeros(T),
        "cons": cons,
    }


def diagnostics(res: dict, params: Params, tol: float, timestamps=None) -> dict:
    """Binding fractions (nested a/b/c, Decision 3) for EH-up and EH-dn."""
    T = res["T"]
    up, dn = res["product_set"]["up"], res["product_set"]["dn"]
    out = {}
    for side, psi_name, sum_products in (("up", "psi_up", up), ("dn", "psi_dn", dn)):
        psi = np.abs(res[psi_name])
        u_total = (
            np.sum([res["u"][k] for k in sum_products], axis=0)
            if sum_products else np.zeros(T)
        )
        b = psi > tol
        c_read = b & (u_total > 1e-9)
        out[side] = {
            "frac_b_multiplier": float(b.mean()),
            "frac_c_governing": float(c_read.mean()),
            "n_intervals_c": int(c_read.sum()),
            "psi_mean_when_c": float(psi[c_read].mean()) if c_read.any() else 0.0,
            "psi_max": float(psi.max()) if psi.size else 0.0,
        }
        if timestamps is not None and c_read.any():
            days = {str(np.datetime64(t, "D")) for t in np.asarray(timestamps)[c_read]}
            out[side]["distinct_binding_days"] = len(days)
        else:
            out[side]["distinct_binding_days"] = 0
    return out


def verify(res: dict, params: Params) -> dict:
    """Verification checks from docs/step0_spec.md section 7 (convention-robust)."""
    checks = {}

    # (3) no dumping: min(c,d) ~ 0
    checks["no_dumping_min_cd"] = float(np.max(np.minimum(res["c"], res["d"])))

    # (2) complementary slackness: dual * slack ~ 0 for the SOC ceiling
    S = res["S"]
    slack_hi = res["E_max"] - S
    checks["compl_slack_soc_hi"] = float(np.max(np.abs(res["lam_hi"] * slack_hi)))

    return checks


def duration_identity(P, mcpc, E_max, params, product_set, h=0.01) -> dict:
    """Verification check (4): compare LEFT and RIGHT finite differences of the
    optimum w.r.t. E_max to sum_t(lam_hi + psi_dn). Kinked LP -> do NOT average."""
    base = solve_lp(P, mcpc, E_max, params, product_set)
    up = solve_lp(P, mcpc, E_max * (1 + h), params, product_set)
    dn = solve_lp(P, mcpc, E_max * (1 - h), params, product_set)
    step = h * E_max
    right = (up["objective"] - base["objective"]) / step
    left = (base["objective"] - dn["objective"]) / step
    multiplier_sum = float(np.sum(base["lam_hi"]) + np.sum(base["psi_dn"]))
    return {"fd_right": right, "fd_left": left, "sum_lam_hi_plus_psi_dn": multiplier_sum}


# --------------------------------------------------------------------------- #
# Self-test on synthetic prices (no ERCOT needed).                            #
# --------------------------------------------------------------------------- #
def _synthetic(T=192, seed_offset=0):
    """A diurnal price with evening spikes + flat-ish MCPC. Deterministic
    (no RNG — Date/random are unavailable in some harness contexts)."""
    hours = (np.arange(T) * 0.25) % 24
    # low overnight, high evening, occasional spike
    P = 25 + 15 * np.sin((hours - 17) / 24 * 2 * np.pi) + 20
    P = np.where((hours > 17) & (hours < 20), P + 120, P)   # evening spike
    P = np.where((hours > 2) & (hours < 5), 5.0, P)         # cheap overnight
    mcpc = {
        "RRS": 3.0 + 2 * (hours > 17),
        "ECRS": 4.0 + 3 * (hours > 17),
        "NSPIN": 2.0 + 1.0 * (hours > 17),
        "REGUP": 3.0 * np.ones(T),
        "REGDN": 1.0 * np.ones(T),
    }
    return P, mcpc


if __name__ == "__main__":
    params = Params()
    tol = 0.01 * np.median(np.abs(_synthetic()[0]))
    P, mcpc = _synthetic()
    print(f"Self-test: T={len(P)} intervals, tol={tol:.3f} $/MWh\n")

    for label, pset in (("energy-only", ENERGY_ONLY),
                         ("contingency", CONTINGENCY),
                         ("all-products", ALL_PRODUCTS)):
        print(f"=== {label} ===")
        for E in (1.0, 2.0, 4.0):
            res = solve_lp(P, mcpc, E, params, pset)
            dg = diagnostics(res, params, tol)
            vf = verify(res, params)
            print(
                f"  {E:.0f}h  status={res['status']:<8} obj=${res['objective']:8.1f}  "
                f"EHup(c)={dg['up']['frac_c_governing']*100:5.1f}%  "
                f"psi_up_max=${dg['up']['psi_max']:6.1f}  "
                f"min(c,d)={vf['no_dumping_min_cd']:.1e}  "
                f"complSlack={vf['compl_slack_soc_hi']:.1e}"
            )
        # duration identity at 2h
        di = duration_identity(P, mcpc, 2.0, params, pset)
        print(f"  duration id @2h: fd_left={di['fd_left']:.2f} fd_right={di['fd_right']:.2f} "
              f"sum(lam_hi+psi_dn)={di['sum_lam_hi_plus_psi_dn']:.2f}")
        print()
