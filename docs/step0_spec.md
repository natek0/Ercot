# Step 0 — Viability Test: Build Specification

**Status:** approved design, ready to build. Read together with `CLAUDE.md`
(Decisions 1–16, Corrections 1–4) and `reports/step0_preregistration.md` (the
frozen numbers). This document is the *contract*; the pre-registration is the
*committed parameters*. Math is written in plain ASCII so it reads directly in
the editor.

---

## 1. Purpose

One question: **does RTC+B's "hold enough charge to back your reserves" rule
(the energy-headroom constraint EH-up) bind often enough that its shadow price
psi_up has a real answer?** If it essentially never binds, Q2 has no answer and
the project re-scopes before any modelling code is written.

Everything here is a **perfect-foresight linear program (LP)** — prices for the
whole window are known, no forecasting, no dynamic programming yet. Per Decisions
11/14, the viability signal is **psi_up** (the up-reserve floor), NOT the
duration curve's ancillary term (that is the downward multiplier psi_dn, which is
~0 by construction in the headline run — see Decision 11).

---

## 2. What we build — the LP

Intervals t = 0..T-1, each dt = 0.25 h. Per-interval variables:

- `c_t >= 0`  charge power (MW)
- `d_t >= 0`  discharge power (MW)
- `S_t >= 0`  state of charge (MWh)
- `u^k_t >= 0`  capacity sold to ancillary product k (MW), for k in the active set

Objective (maximize total profit over the window):
```
max  sum_t [  P_t*(d_t - c_t)*dt            # energy arbitrage
            - c_deg*(c_t + d_t)*dt          # degradation, charged on BOTH legs (Decision 7)
            + sum_k P^k_t * u^k_t * dt ]     # ancillary capacity revenue
```
No phi_k (AS throughput) term: deployment is not modelled in Step 0, so phi_k = 0.

Constraints, for every t:
```
[balance]  S_{t+1} = S_t + (eta_c*c_t - d_t/eta_d)*dt            dual mu_t
[soc]      0 <= S_t <= E_max                    duals: underline_lambda_t (lower), lambda_bar_t (upper)
[power]    0 <= c_t <= p_bar ,  0 <= d_t <= p_bar
[phdr-up]  (d_t - c_t) + sum_{k in Kup} u^k_t <= p_bar           dual omega_up_t
[phdr-dn]  (c_t - d_t) + sum_{k in Kdn} u^k_t <= p_bar           dual omega_dn_t
[EH-up]    S_{t+1} - S_min >= (1/eta_d)*sum_{k in Kup} tau_k*u^k_t   dual psi_up_t   <-- THE constraint
[EH-dn]    E_max - S_{t+1} >= eta_c*sum_{k in Kdn} tau_k*u^k_t       dual psi_dn_t
[reg-cap]  u^k_t <= p_bar   (registration cap set non-binding for Step 0)
```
Notes:
- Energy-headroom binds on the POST-decision SOC `S_{t+1}` (plan III.17).
- We do NOT impose `c_t*d_t = 0`; with `c_deg > 0` it holds at the optimum
  automatically (plan IV.7 Prop 3). ASSERT `min(c_t,d_t) < 1e-6` after solving.
  If it ever fires, switch [balance] to the inequality `S_{t+1} <= ...`
  (Correction 3).
- MCPC prices `P^k_t` are $/MW-h, so they are multiplied by `dt` in the objective
  (Correction 4). Put the units in a comment next to every dual extraction.
- The dual sign convention must satisfy the energy-only recursion
  `mu_{t-1} = mu_t - lambda_bar_t + underline_lambda_t` (Correction 2). This is
  verification check 1 and is load-bearing.

---

## 3. Two runs × three durations

Run both product sets (Decision 2):
- **Contingency-only** (headline for psi_up): `Kup = {RRS, ECRS, Non-Spin}`, `Kdn = {}`.
- **All-products**: `Kup = {RRS, ECRS, Non-Spin, Reg-Up}`, `Kdn = {Reg-Down}`.

At durations `E_max = {1, 2, 4}` MWh (with `p_bar = 1` MW → 1 h, 2 h, 4 h).

`tau_k` (hours), post-RTC (Decision 16): RRS 0.5, ECRS 1.0, Non-Spin 4.0,
Reg-Up 0.5, Reg-Down 0.5. Pre-RTC re-run (Decision 9, only if the gate says
"never binds"): ECRS 2.0, RRS 1.0, Reg-Up 1.0, Reg-Down 1.0, Non-Spin 4.0.

Why contingency-only is the clean headline: it is all upward products, so
`Kdn` is empty, psi_dn is identically 0, and the run isolates the up-reserve
floor cost psi_up without the "Regulation looks free in a deterministic LP"
artifact (Decision 2).

---

## 4. Data — two series at HB_NORTH

| Series | Product | Endpoint |
|---|---|---|
| RT settlement-point price, 15-min (`P_t`) | NP6-905-CD | `/np6-905-cd/spp_node_zone_hub`, filter `settlementPoint = HB_NORTH` |
| RT MCPC, 15-min (`P^k_t`) | **NP6-331-CD** (report 24898) | **Archive only** — NOT in the query API. Use `GET /archive/NP6-331-CD` (auth-gated), then download + parse per-interval files. Verified 21 Jul 2026 against the live OpenAPI spec. |

- Base URL `https://api.ercot.com/api/public-reports`; auth + headers per
  `CLAUDE.md` "Environment and API notes."
- **NOT NP4-212-CD** — that is the Ancillary Service Demand Curves (ASDC), the
  wrong product (CLAUDE.md Correction 1).
- NP6-331-CD gives one MCPC per AS type per 15-min interval; pivot to columns
  REGUP, REGDN, RRS, ECRS, NSPIN (use RRS excluding FFR). Print the returned
  `fields` list — do not assume column names.
- Window: **1-month smoke test first** (pipeline check), then the **full
  post-launch window** (2025-12-05 → latest) for the gate (Decision 1). Assert
  96 rows/day per series before concatenating; handle pagination (CLAUDE.md).

---

## 5. Diagnostics (per run, per duration)

1. **EH-up binding fraction** — three nested numbers (Decision 3), (c) governs:
   (a) slack < tol_slack; (b) psi_up > tol; (c) psi_up > tol AND
   `sum_{Kup} u^k_t > 0`. **Load-bearing.**
2. **EH-dn binding fraction** — same nesting. Expected ~0 contingency-only
   (Kdn empty); small even all-products (Reg-Down is a minor market).
3. **psi_up, psi_dn distribution** — magnitude and by hour-of-day, when active.
4. **Distinct binding days** — number of calendar days containing a reading-(c)
   binding interval. This is the effective sample size (plan VIII.5a).

Plus (Decision 14, counterfactual): at each E_max also solve **energy-only**
(no u) and **energy+contingency**; report the perfect-foresight objective vs
duration for each. Their difference is the contingency contribution to duration
value — it routes through lambda_bar and cannot be read from psi alone.

Robustness (report, not gate-governing): re-run with `S_min = 0.02*E_max`
(separates EH-up from the empty-battery bound, Decision 3); report the binding
fraction at `c_deg in {0, 25, 50}`.

---

## 6. The gate — read on psi_up (Decision 14 / Option C)

Evaluated **contingency-only, 2 h duration, full window, binding reading (c)**:

| Outcome | Signal | Response |
|---|---|---|
| Binds meaningfully | psi_up > tol in > 5% of ALL intervals across >= 10 distinct days | PROCEED with the plan |
| Binds short-duration only | significant at 1 h, ~0 at 4 h | PROCEED; reframe Q3 as "where duration stops paying" |
| Essentially never | < 1% of intervals AND < 5 days, AND survives the pre-RTC tau re-run | STOP; re-scope (kill condition) |
| Binds nearly everywhere | > 60% of intervals | Investigate first: Regulation artifact (Dec 2) → duplicate-constraint (Dec 3) → units (Corr 4) |

The gate reads asymmetrically (Decision 8): "binds" is a conservative lower
bound (perfect foresight positions SOC to avoid constraints better than any real
operator); "does not bind" is not conclusive. State this in the results.

---

## 7. Verification checks (all required — CLAUDE.md)

1. **u=0 recursion:** force all `u^k = 0`; the dual recursion must collapse to
   `mu_{t-1} = mu_t - lambda_bar_t + underline_lambda_t` (Correction 2 signs).
   Load-bearing sign check.
2. **Complementary slackness:** multiplier * slack ~ 0 for every constraint.
3. **No dumping:** `min(c_t, d_t) < 1e-6` for all t (Prop 3).
4. **Duration identity:** perturb E_max by +/-1%, re-solve; compare the LEFT and
   RIGHT finite differences of the optimum SEPARATELY against
   `sum_t (lambda_bar_t + psi_dn_t)` (plan IV.11; the LP is degenerate/kinked, so
   a central difference hides the kink). In contingency-only psi_dn~0, so this
   reduces to `sum lambda_bar`.
5. **Units:** confirm every dual's units in a comment; psi in $/MWh, checked
   against MCPC*dt (Correction 4).

Print PASS/FAIL for each in the results.

---

## 8. Out of scope for Step 0 (CLAUDE.md — do not add)

Deployment factors / phi_k; day-ahead MCPC; NP6-332 vs NP6-331 cross-check;
Total AS Capability cross-check; effective-sample-size stats; concentration
(top-1/5 day) reporting; ESR API data. These return in later steps.

---

## 9. Deliverables

- `reports/step0_results.md`: the four diagnostics × 2 runs × 3 durations, the
  counterfactual duration curves, the gate verdict (§6), and a PASS/FAIL line for
  every verification check in §7.
- One script/command regenerates the results from raw data.
- **STOP at the gate.** Do not begin Step 1 until the user reviews the results.
- **Do not tune parameters after seeing results** — the pre-registration is
  frozen. If the gate says "essentially never binds," run the pre-RTC tau re-run
  (Decision 9) before concluding.

---

## 10. Suggested stack

Python 3.11+. `cvxpy` with the HiGHS solver (readable per-constraint duals via
`constraint.dual_value`) or `highspy` directly (faster, more bookkeeping).
`gridstatus` or direct ERCOT API calls for ingest; `pandas`, `numpy`,
`python-dotenv`. Keep the LP in one readable module with the constraint names
above so the duals map 1:1 to §2.
