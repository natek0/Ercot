"""
Perfect-foresight battery-dispatch oracle (Stage 1).

This is the Stage 0 LP (docs/step0_spec.md §2) generalised into a reusable
module. "Oracle" = it sees the whole price window at once (perfect foresight),
so its objective is the CEILING on achievable profit and its psi_up is the
FLOOR on the constraint cost — a clairvoyant bound no causal policy can beat
(CLAUDE.md Decision 19). Every downstream policy is scored against it.

What changed from src/step0_lp.py (which now re-exports from here):
  * Boundary conditions are parameters, not hard-wired. The Stage 0 run is the
    full window with a CYCLIC state of charge (S_0 = S_T). Stage 2's MPC instead
    solves a short rolling window starting from the battery's CURRENT charge, so
    it needs `s_init` fixed and `cyclic` off. `solve(..., s_init=x, cyclic=False)`
    does exactly that. Default `cyclic=True` reproduces Stage 0 unchanged.
  * Results come back as a typed `OracleResult`, not a bare dict, with the dual
    sign/units documented at the point of extraction.
  * Verification checks complementary slackness on EVERY extracted constraint
    (spec §7.2), and the energy-only dual recursion sign (Correction 2), which we
    verified the HiGHS convention against empirically.

Dual sign convention (verified against HiGHS output, matches CLAUDE.md
Correction 2): at the returned optimum the interior state-of-charge stationarity
    mu[k-1] = mu[k] - lam_hi[k] + lam_lo[k]      (k = 1 .. T-1)
holds to solver tolerance, where mu is the balance dual (marginal value of
stored energy, $/MWh), lam_hi the SOC-ceiling dual and lam_lo the SOC-floor
dual. This is `verification()["recursion_resid"]` and is load-bearing.

Units: energy price P is $/MWh; MCPC is $/MW-h and is multiplied by dt in the
objective (Correction 4); all duals psi_up, psi_dn, mu, lam_* are $/MWh.

Running this module directly (python -m src.oracle) runs a self-test on
synthetic prices — no ERCOT data needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cvxpy as cp
import numpy as np


# --------------------------------------------------------------------------- #
# Parameters and product sets                                                 #
# --------------------------------------------------------------------------- #
@dataclass
class BatteryParams:
    """Physical + economic parameters, frozen per reports/step0_preregistration.md."""

    dt: float = 0.25          # hours per interval
    eta_c: float = 0.95       # charge efficiency
    eta_d: float = 0.95       # discharge efficiency
    c_deg: float = 25.0       # $/MWh throughput, charged on BOTH legs (Decision 7)
    p_bar: float = 1.0        # MW power rating
    s_min: float = 0.0        # reserved floor (MWh); 0 for a grid ESR
    tau: dict = field(default_factory=lambda: {   # duration req (hours), Decision 16
        "RRS": 0.5, "ECRS": 1.0, "NSPIN": 4.0, "REGUP": 0.5, "REGDN": 0.5,
    })


# Legacy alias — Stage 0 code imports `Params`.
Params = BatteryParams

# Product sets (kept as plain dicts so `pset["up"]` keeps working everywhere).
CONTINGENCY = {"up": ["RRS", "ECRS", "NSPIN"], "dn": []}
ALL_PRODUCTS = {"up": ["RRS", "ECRS", "NSPIN", "REGUP"], "dn": ["REGDN"]}
ENERGY_ONLY = {"up": [], "dn": []}


# --------------------------------------------------------------------------- #
# Result container                                                            #
# --------------------------------------------------------------------------- #
@dataclass
class OracleResult:
    """Everything a caller needs: the schedule, the duals, and the primal
    slacks (so the verification suite can be recomputed without the cvxpy
    problem object)."""

    status: str
    objective: float
    E_max: float
    T: int
    dt: float
    # primal schedule
    S: np.ndarray          # (T+1,) state of charge, MWh; S[t+1] is post-decision SOC of interval t
    c: np.ndarray          # (T,) charge power, MW
    d: np.ndarray          # (T,) discharge power, MW
    u: dict                # product -> (T,) capacity sold, MW
    product_set: dict
    # duals ($/MWh), magnitudes with the sign convention documented in the module docstring
    mu: np.ndarray         # balance / marginal value of stored energy
    lam_lo: np.ndarray     # SOC floor  S >= 0
    lam_hi: np.ndarray     # SOC ceiling S <= E_max
    omega_up: np.ndarray   # up power-headroom
    omega_dn: np.ndarray   # down power-headroom
    psi_up: np.ndarray     # EH-up  (THE Q2 number)
    psi_dn: np.ndarray     # EH-dn

    def first_action(self) -> dict:
        """Interval-0 dispatch — what Stage 2's MPC executes before advancing."""
        return {
            "c": float(self.c[0]),
            "d": float(self.d[0]),
            "S_next": float(self.S[1]),
            "u": {k: float(v[0]) for k, v in self.u.items()},
        }

    def to_legacy_dict(self) -> dict:
        """Old src/step0_lp.py dict shape, so step0_run.py is untouched."""
        return {
            "status": self.status, "objective": self.objective, "E_max": self.E_max,
            "T": self.T, "S": self.S, "c": self.c, "d": self.d, "u": self.u,
            "product_set": self.product_set, "mu": self.mu, "lam_lo": self.lam_lo,
            "lam_hi": self.lam_hi, "omega_up": self.omega_up, "omega_dn": self.omega_dn,
            "psi_up": self.psi_up, "psi_dn": self.psi_dn,
        }


# --------------------------------------------------------------------------- #
# The solve                                                                   #
# --------------------------------------------------------------------------- #
def solve(
    P,
    mcpc,
    E_max,
    params: BatteryParams,
    product_set,
    *,
    s_init: float | None = None,
    s_final: float | None = None,
    cyclic: bool = True,
    terminal_value: float | None = None,
    solver=cp.HIGHS,
) -> OracleResult:
    """Solve the perfect-foresight LP over a price window and return the schedule
    plus duals.

    P     : (T,) energy price, $/MWh
    mcpc  : dict product -> (T,) capacity price, $/MW-h (only active products read)
    E_max : MWh (with p_bar = 1 MW this is also the duration in hours)

    Boundary conditions (this is the Stage-2 reuse surface):
      * cyclic=True (default): S[0] == S[T]. The Stage 0 full-window convention —
        no free energy is created or destroyed over the window.
      * s_init not None: S[0] == s_init. The battery's CURRENT charge; a rolling
        MPC step fixes this.
      * s_final not None: S[T] == s_final. A hard terminal-SOC target.
      Fixing either endpoint turns OFF the cyclic constraint (they would conflict).
      NOTE for Stage 2: a finite horizon with a FREE end (s_init set, s_final None)
      will drain the battery at the horizon edge — the classic MPC end effect. Pass
      `terminal_value` ($/MWh) to value leftover charge S[T] in the objective and
      stop the drain. A simple placeholder (a trailing/reference price) is right for
      Stage 2; the principled terminal value is the converged DP value function
      (Stage 4).
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
    if terminal_value is not None:
        # value leftover charge at the horizon edge ($/MWh on the final SOC node)
        profit = profit + terminal_value * S[T]

    up_sum = sum((u[k] for k in up), start=0)
    dn_sum = sum((u[k] for k in dn), start=0)

    cons = {
        "balance": (S[1:] == S[:-1] + (eta_c * c - d / eta_d) * dt),
        "soc_lo": (S >= 0),
        "soc_hi": (S <= E_max),
        "c_hi": (c <= p),
        "d_hi": (d <= p),
        "phdr_up": (d - c + up_sum <= p),
        "phdr_dn": (c - d + dn_sum <= p),
    }
    if up:
        cons["eh_up"] = (Splus - s_min >= (1.0 / eta_d) * sum(params.tau[k] * u[k] for k in up))
    if dn:
        cons["eh_dn"] = (E_max - Splus >= eta_c * sum(params.tau[k] * u[k] for k in dn))

    # Boundary conditions. Fixing an endpoint overrides the cyclic default.
    if s_init is not None:
        cons["s_init"] = (S[0] == s_init)
    if s_final is not None:
        cons["s_final"] = (S[T] == s_final)
    if cyclic and s_init is None and s_final is None:
        cons["cyclic"] = (S[0] == S[T])

    prob = cp.Problem(cp.Maximize(profit), list(cons.values()))
    prob.solve(solver=solver)

    def dv(name):
        return np.asarray(cons[name].dual_value) if name in cons else np.zeros(T)

    return OracleResult(
        status=prob.status,
        objective=float(prob.value),
        E_max=float(E_max),
        T=T,
        dt=dt,
        S=np.asarray(S.value),
        c=np.asarray(c.value),
        d=np.asarray(d.value),
        u={k: np.asarray(u[k].value) for k in up + dn},
        product_set=product_set,
        mu=dv("balance"),
        lam_lo=dv("soc_lo"),
        lam_hi=dv("soc_hi"),
        omega_up=dv("phdr_up"),
        omega_dn=dv("phdr_dn"),
        psi_up=dv("eh_up") if up else np.zeros(T),
        psi_dn=dv("eh_dn") if dn else np.zeros(T),
    )


# --------------------------------------------------------------------------- #
# Diagnostics and verification (operate on an OracleResult)                   #
# --------------------------------------------------------------------------- #
def binding_diagnostics(res: OracleResult, tol: float, timestamps=None) -> dict:
    """Binding fractions (nested a/b/c, Decision 3) for EH-up and EH-dn.
    Reading (c) — psi > tol AND up-reserve commitments > 0 — governs the gate."""
    T = res.T
    up, dn = res.product_set["up"], res.product_set["dn"]
    out = {}
    for side, psi, sum_products in (
        ("up", np.abs(res.psi_up), up),
        ("dn", np.abs(res.psi_dn), dn),
    ):
        u_total = (
            np.sum([res.u[k] for k in sum_products], axis=0)
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


def verification(res: OracleResult, params: BatteryParams) -> dict:
    """The spec §7 checks, as raw residuals (a test asserts each is ~0).

    Convention-robust where possible; the recursion residual uses the HiGHS sign
    convention verified against Correction 2.
    """
    S, E = res.S, res.E_max
    out = {}

    # (3) no dumping: min(c, d) ~ 0  (Prop 3 holds automatically when c_deg > 0)
    out["no_dumping_min_cd"] = float(np.max(np.minimum(res.c, res.d)))

    # (2) complementary slackness: |dual * slack| ~ 0 for EVERY extracted constraint.
    up, dn = res.product_set["up"], res.product_set["dn"]
    up_sum = np.sum([res.u[k] for k in up], axis=0) if up else np.zeros(res.T)
    dn_sum = np.sum([res.u[k] for k in dn], axis=0) if dn else np.zeros(res.T)
    tau = params.tau
    Splus = S[1:]
    slacks = {
        "soc_lo": res.lam_lo * (S - 0.0),
        "soc_hi": res.lam_hi * (E - S),
        "phdr_up": res.omega_up * (params.p_bar - (res.d - res.c + up_sum)),
        "phdr_dn": res.omega_dn * (params.p_bar - (res.c - res.d + dn_sum)),
    }
    if up:
        eh_up_slack = (Splus - params.s_min) - (1.0 / params.eta_d) * np.sum(
            [tau[k] * res.u[k] for k in up], axis=0)
        slacks["eh_up"] = res.psi_up * eh_up_slack
    if dn:
        eh_dn_slack = (E - Splus) - params.eta_c * np.sum(
            [tau[k] * res.u[k] for k in dn], axis=0)
        slacks["eh_dn"] = res.psi_dn * eh_dn_slack
    out["compl_slack"] = {k: float(np.max(np.abs(v))) for k, v in slacks.items()}
    out["compl_slack_max"] = float(max(out["compl_slack"].values()))

    # (1) energy-only dual recursion sign check (Correction 2), interior nodes k=1..T-1:
    #     mu[k-1] = mu[k] - lam_hi[k] + lam_lo[k]
    Tt = res.T
    resid = res.mu[:-1] - (res.mu[1:] - res.lam_hi[1:Tt] + res.lam_lo[1:Tt])
    out["recursion_resid"] = float(np.max(np.abs(resid)))

    return out


def duration_identity(P, mcpc, E_max, params, product_set, h=0.01, **solve_kw) -> dict:
    """Verification check (4): compare the LEFT and RIGHT finite differences of the
    optimum w.r.t. E_max to sum_t(lam_hi + psi_dn). The LP is degenerate/kinked, so
    compute one-sided differences and check the multiplier sum sits BETWEEN them —
    a central difference would average across the kink and hide it (plan IV.11)."""
    base = solve(P, mcpc, E_max, params, product_set, **solve_kw)
    up = solve(P, mcpc, E_max * (1 + h), params, product_set, **solve_kw)
    dn = solve(P, mcpc, E_max * (1 - h), params, product_set, **solve_kw)
    step = h * E_max
    right = (up.objective - base.objective) / step
    left = (base.objective - dn.objective) / step
    multiplier_sum = float(np.sum(base.lam_hi) + np.sum(base.psi_dn))
    return {"fd_right": right, "fd_left": left, "sum_lam_hi_plus_psi_dn": multiplier_sum}


# --------------------------------------------------------------------------- #
# Legacy shims — keep src/step0_lp.py and step0_run.py working unchanged.      #
# --------------------------------------------------------------------------- #
def solve_lp(P, mcpc, E_max, params, product_set) -> dict:
    """Stage 0 entry point: returns the old dict shape."""
    return solve(P, mcpc, E_max, params, product_set).to_legacy_dict()


def diagnostics(res: dict, params, tol: float, timestamps=None) -> dict:
    """Stage 0 diagnostics over a legacy dict (or an OracleResult)."""
    if isinstance(res, dict):
        res = _dict_to_result(res)
    return binding_diagnostics(res, tol, timestamps)


def verify(res: dict, params) -> dict:
    """Stage 0 verify over a legacy dict: returns the two fields step0_run reads."""
    if isinstance(res, dict):
        res = _dict_to_result(res)
    v = verification(res, params)
    return {
        "no_dumping_min_cd": v["no_dumping_min_cd"],
        "compl_slack_soc_hi": v["compl_slack"]["soc_hi"],
    }


def _dict_to_result(d: dict) -> OracleResult:
    return OracleResult(
        status=d["status"], objective=d["objective"], E_max=d["E_max"], T=d["T"],
        dt=d.get("dt", 0.25), S=d["S"], c=d["c"], d=d["d"], u=d["u"],
        product_set=d["product_set"], mu=d["mu"], lam_lo=d["lam_lo"], lam_hi=d["lam_hi"],
        omega_up=d["omega_up"], omega_dn=d["omega_dn"], psi_up=d["psi_up"], psi_dn=d["psi_dn"],
    )


# --------------------------------------------------------------------------- #
# Self-test on synthetic prices (no ERCOT needed).                            #
# --------------------------------------------------------------------------- #
def synthetic_prices(T=192):
    """A diurnal price with evening spikes + flat-ish MCPC. Deterministic
    (no RNG — Date/random are unavailable in some harness contexts)."""
    hours = (np.arange(T) * 0.25) % 24
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
    params = BatteryParams()
    P, mcpc = synthetic_prices()
    tol = 0.01 * np.median(np.abs(P))
    print(f"Self-test: T={len(P)} intervals, tol={tol:.3f} $/MWh\n")

    for label, pset in (("energy-only", ENERGY_ONLY),
                        ("contingency", CONTINGENCY),
                        ("all-products", ALL_PRODUCTS)):
        print(f"=== {label} ===")
        for E in (1.0, 2.0, 4.0):
            res = solve(P, mcpc, E, params, pset)
            dg = binding_diagnostics(res, tol)
            vf = verification(res, params)
            print(
                f"  {E:.0f}h  status={res.status:<8} obj=${res.objective:8.1f}  "
                f"EHup(c)={dg['up']['frac_c_governing']*100:5.1f}%  "
                f"psi_up_max=${dg['up']['psi_max']:6.1f}  "
                f"min(c,d)={vf['no_dumping_min_cd']:.1e}  "
                f"complSlack={vf['compl_slack_max']:.1e}  "
                f"recursion={vf['recursion_resid']:.1e}"
            )
        di = duration_identity(P, mcpc, 2.0, params, pset)
        print(f"  duration id @2h: fd_left={di['fd_left']:.2f} fd_right={di['fd_right']:.2f} "
              f"sum(lam_hi+psi_dn)={di['sum_lam_hi_plus_psi_dn']:.2f}")
        print()
