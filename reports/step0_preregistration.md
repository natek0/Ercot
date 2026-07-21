# Step 0 Pre-Registration — parameters and kill condition

**Committed before the first real run (Decision 10).**

Why this file exists (the short version, since you asked): binding frequency
depends on the numbers below — c_deg, the efficiencies, tau, the tolerance. If we
picked those *after* seeing results, we could get almost any answer we wanted;
that is p-hacking, and an interviewer will ask "how do I know you didn't tune the
parameters until the mechanism looked alive?" This file is the answer: the
numbers were frozen first, in the repo, before any result existed. It costs one
short document and buys the whole viability test its credibility. Do not change
these after seeing output; if a change is ever genuinely needed, record why and
re-commit.

---

## Frozen parameters

| Symbol | Meaning | Value |
|---|---|---|
| `dt` | interval length | 0.25 h |
| `p_bar` | power rating | 1 MW (reporting convention; the problem is scale-free) |
| `E_max` | capacity / duration | {1, 2, 4} MWh = {1, 2, 4} h |
| `eta_c, eta_d` | charge, discharge efficiency | 0.95, 0.95 (round-trip 0.9025) |
| `c_deg` | degradation cost | $25 / MWh throughput (gate value); also report at $0 and $50 as non-governing robustness |
| `S_min` | reserved floor | 0 (grid ESR); robustness re-run at 0.02 * E_max |
| `phi_k` | AS throughput factor | 0 (no deployment modelled in Step 0) |
| `tau` (post-RTC) | duration requirement (h) | RRS 0.5, ECRS 1.0, Non-Spin 4.0, Reg-Up 0.5, Reg-Down 0.5 |
| `tau` (pre-RTC) | Decision 9 re-run | ECRS 2.0, RRS 1.0, Reg-Up 1.0, Reg-Down 1.0, Non-Spin 4.0 |
| `u_qual` | registration cap | p_bar (non-binding) |
| `tol` | "multiplier above tolerance" | kappa * median(|P_t|), kappa = 0.01 (Decision 4) |
| `tol_slack` | "constraint active" | 1e-4 MWh |
| gate denominator | "% of intervals" | ALL intervals (Decision 5) |
| settlement point | | HB_NORTH (Decision 6) |
| window | | smoke: 1 month; gate: full post-launch 2025-12-05 → latest (Decision 1) |

---

## Gate thresholds (contingency-only, 2 h, full window, binding reading (c))

- **PROCEED:** psi_up > tol in > 5% of all intervals AND on >= 10 distinct days.
- **PROCEED (reframe):** binds at 1 h, ~0 at 4 h.
- **STOP (kill):** psi_up > tol in < 1% of all intervals AND on < 5 distinct
  days, AND this still holds under the pre-RTC tau re-run.
- **INVESTIGATE:** > 60% of intervals (artifact check before any proceed).

---

## Kill condition (verbatim, Decision 10)

> If, over the full post-launch window, at 2-hour duration, contingency products
> only, using binding reading (c), psi_up exceeds tolerance in fewer than 1% of
> ALL intervals and on fewer than 5 distinct days, AND this survives the
> pre-RTC+B tau re-run, then Q2 is dead and the project re-scopes before any
> further building.

The parameters above are frozen as of the commit of this file.
