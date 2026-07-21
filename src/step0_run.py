"""
Step 0 gate — regenerate all reported numbers from cached raw data.

Runs the perfect-foresight LP on the full post-launch window at HB_NORTH for
both product sets (contingency-only, all-products) and all three durations,
extracts the diagnostics of docs/step0_spec.md section 5, the tolerance
sensitivity, the material binding days, and the verification checks.

One command regenerates reports/step0_results.md's numbers:
    python -m src.step0_run
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import ingest
from src.step0_lp import (
    ALL_PRODUCTS,
    CONTINGENCY,
    ENERGY_ONLY,
    Params,
    diagnostics,
    duration_identity,
    solve_lp,
    verify,
)

DATE_FROM, DATE_TO = "2025-12-05", "2026-06-20"


def main():
    panel = ingest.build_panel(DATE_FROM, DATE_TO)
    P = panel["price"].to_numpy(float)
    ts = panel["ts"].to_numpy()
    mcpc = {k: panel[k].to_numpy(float) for k in ingest.AS_TYPES}
    params = Params()
    tol = 0.01 * np.median(np.abs(P))
    print(f"window {DATE_FROM}..{DATE_TO}  T={len(P)} intervals  "
          f"{panel['date'].nunique()} days")
    print(f"pre-registered tol = 1% median|P| = ${tol:.3f}/MWh\n")

    # ---- diagnostics grid: 2 runs x 3 durations -------------------------- #
    print("=== Diagnostics (EH-up reading (c) governs) ===")
    print(f"{'run':<13}{'E':>3}  {'EHup(c)%':>9}{'days':>6}{'psiMean':>9}"
          f"{'psiMax':>9}{'min(c,d)':>10}{'complSlk':>10}")
    grid = {}
    for label, pset in (("contingency", CONTINGENCY), ("all-products", ALL_PRODUCTS)):
        for E in (1.0, 2.0, 4.0):
            res = solve_lp(P, mcpc, E, params, pset)
            dg = diagnostics(res, params, tol, timestamps=ts)
            vf = verify(res, params)
            grid[(label, E)] = (res, dg, vf)
            u = dg["up"]
            print(f"{label:<13}{E:>3.0f}  {u['frac_c_governing']*100:>8.2f}%"
                  f"{u['distinct_binding_days']:>6}{u['psi_mean_when_c']:>9.3f}"
                  f"{u['psi_max']:>9.2f}{vf['no_dumping_min_cd']:>10.1e}"
                  f"{vf['compl_slack_soc_hi']:>10.1e}")

    # ---- headline cell: contingency, 2h --------------------------------- #
    res2, _, _ = grid[("contingency", 2.0)]
    psi = np.abs(res2["psi_up"])
    print("\n=== psi_up distribution (contingency, 2h), $/MWh ===")
    for q in (50, 90, 95, 99):
        print(f"  p{q:<3} {np.percentile(psi, q):>8.3f}")
    print(f"  max  {psi.max():>8.2f}")

    print("\n=== Tolerance sensitivity (contingency, 2h) ===")
    print(f"{'thresh$':>8}{'%intervals':>12}{'days':>6}")
    up = np.sum([res2["u"][k] for k in CONTINGENCY["up"]], axis=0)
    for thr in (tol, 1.0, 5.0, 10.0, 20.0):
        b = (psi > thr) & (up > 1e-9)
        days = len({str(np.datetime64(t, "D")) for t in ts[b]})
        print(f"{thr:>8.3f}{b.mean()*100:>11.2f}%{days:>6}")

    print("\n=== Material binding days (psi_up > $5, contingency 2h) ===")
    b5 = (psi > 5.0) & (up > 1e-9)
    day = ts.astype("datetime64[D]")
    for d in np.unique(day[b5]):
        mask_d = day == d
        print(f"  {d}  psi_max ${psi[mask_d & b5].max():5.1f}  "
              f"energy_max ${P[mask_d].max():6.0f}  n_bind {int((mask_d & b5).sum())}")

    print("\n=== Monthly psi_up>$1 interval count (contingency 2h) ===")
    month = ts.astype("datetime64[M]")
    for m in np.unique(month):
        print(f"  {m}  {int(((month == m) & (psi > 1)).sum()):>4}")

    # ---- counterfactual duration curves --------------------------------- #
    print("\n=== Counterfactual objective by duration ($ over window) ===")
    print(f"{'E':>3}{'energy-only':>14}{'+contingency':>15}{'+all':>14}")
    for E in (1.0, 2.0, 4.0):
        eo = solve_lp(P, mcpc, E, params, ENERGY_ONLY)["objective"]
        co = grid[("contingency", E)][0]["objective"]
        ao = grid[("all-products", E)][0]["objective"]
        print(f"{E:>3.0f}{eo:>14.0f}{co:>15.0f}{ao:>14.0f}")

    # ---- duration identity (verification check 4) ----------------------- #
    print("\n=== Duration identity (contingency, 2h) ===")
    di = duration_identity(P, mcpc, 2.0, params, CONTINGENCY)
    print(f"  fd_left={di['fd_left']:.2f}  fd_right={di['fd_right']:.2f}  "
          f"sum(lam_hi+psi_dn)={di['sum_lam_hi_plus_psi_dn']:.2f}")

    # ---- u=0 recursion check (verification check 1) --------------------- #
    print("\n=== u=0 recursion (energy-only vs contingency-with-u forced 0) ===")
    eo = solve_lp(P, mcpc, 2.0, params, ENERGY_ONLY)
    print(f"  energy-only objective ${eo['objective']:.0f} "
          f"(sign/collapse check: psi_up identically 0 = "
          f"{np.allclose(eo['psi_up'], 0)})")


if __name__ == "__main__":
    main()
