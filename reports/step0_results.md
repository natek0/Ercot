# Step 0 — Viability Test: Results

**Status:** complete. **Gate verdict: qualified PROCEED** (CLAUDE.md Decision 18).
Regenerate every number below with `python -m src.step0_run` (reads cached raw
data under `data/raw/`). Read with `docs/step0_spec.md` (the contract) and
`reports/step0_preregistration.md` (the frozen parameters). Math is plain ASCII.

> **Changelog (Stage 1, Option A).** Numbers regenerated on the **deduped**
> panel: the source pull contained **6 exact-duplicate 15-minute intervals**
> (identical prices, an API page-boundary artifact), now dropped by
> `ingest.dedup_panel` (default). This is a data-hygiene fix, not a parameter
> change, so it is consistent with the frozen pre-registration (which freezes the
> modelling parameters, not the raw pull). Effect: T 18,891 → **18,885**; the
> headline contingency-2 h binding fraction 7.98% → **8.00%**; psi_up max
> **$32.75 unchanged**; **verdict unchanged**. The only non-trivial move is the
> `all-products` psi_up max (a degenerate Regulation-artifact run, never a
> headline — Decision 2). Pre-dedup numbers reproduce with
> `build_panel(..., dedup=False)`.

---

## 1. What was tested

One question (spec §1): does RTC+B's "hold enough charge to back your upward
reserves" rule — the energy-headroom constraint (EH-up) — bind often enough, and
hard enough, that its shadow price `psi_up` (Q2) has a real answer? If it
essentially never binds, Q2 has no answer and the project re-scopes.

Method: a perfect-foresight linear program (prices for the whole window known, no
forecasting) of a single battery, maximizing arbitrage + ancillary revenue minus
degradation, subject to physics (state of charge) and the RTC+B energy-headroom
constraints. The valuable output is not profit but the **dual** on (EH-up),
`psi_up`, in $/MWh.

## 2. Setup (all frozen pre-registration, spec §4 / prereg)

- **Settlement point:** HB_NORTH (a trading hub — AS clears systemwide, Decision 6).
- **Window:** 2025-12-05 → 2026-06-20. **T = 18,885** 15-minute intervals over
  **198 days** (full post-launch window per Decision 1; summer Jul–Sep not yet in
  the data — see §7).
- **Data:** energy price NP6-905-CD (query API); RT MCPC via NP6-796-ER yearly
  bundles (Correction 1). AS types ECRS, NSPIN, REGDN, REGUP, RRS.
- **Parameters (prereg):** dt = 0.25 h, p_bar = 1 MW, E_max ∈ {1, 2, 4} MWh,
  eta_c = eta_d = 0.95, c_deg = $25/MWh, S_min = 0, tau (post-RTC) =
  {RRS 0.5, ECRS 1, NSPIN 4, REGUP 0.5, REGDN 0.5} h.
- **Tolerance (prereg, Decision 4):** 1% of median |P| = **$0.228/MWh**.
- **Binding reading:** nested a/b/c (Decision 3); **(c) governs** = psi_up > tol
  AND sum of up-reserve commitments > 0.

## 3. Diagnostics — 2 runs × 3 durations

EH-up binding fraction, reading (c). `psiMean` is over binding intervals; `psiMax`
over all. `min(c,d)` and `complSlack` are verification checks (§6); both are
0 to solver tolerance everywhere.

| run | E (h) | EH-up (c) | days | psiMean $ | psiMax $ | min(c,d) | complSlack |
|---|---|---|---|---|---|---|---|
| contingency | 1 | 8.46% | 130 | 0.955 | 59.00 | 0 | 0 |
| **contingency** | **2** | **8.00%** | **129** | **0.813** | **32.75** | 0 | 0 |
| contingency | 4 | 7.67% | 127 | 0.753 | 21.13 | 0 | 0 |
| all-products | 1 | 39.80% | 185 | 0.765 | 254.70 | 0 | 0 |
| all-products | 2 | 9.92% | 144 | 0.888 | 159.64 | 0 | 0 |
| all-products | 4 | 8.19% | 133 | 0.871 | 118.37 | 0 | 0 |

The **contingency-only, 2 h** row is the gate cell (spec §6). The
**all-products, 1 h** cell showing 39.8% is the Regulation artifact predicted by
Decision 2 — a deterministic LP sees Regulation as near-free revenue and sells it
to the headroom limit; it is NOT a real binding signal and is why contingency-only
is the clean headline.

## 4. The honest magnitude — it binds cheaply

Binding *frequency* is not the story; binding *magnitude* is. Distribution of
`psi_up` (contingency, 2 h), $/MWh:

| p50 | p90 | p95 | p99 | max |
|---|---|---|---|---|
| 0.015 | 0.204 | 0.597 | 1.465 | 32.75 |

The pre-registered tolerance ($0.228) is **too loose** — it counts sub-$0.25
noise-level bindings. Tighten to an economically meaningful bar and the count
collapses:

| threshold $/MWh | % of intervals | distinct days |
|---|---|---|
| 0.228 (pre-registered) | 8.00% | 129 |
| 1 | 1.09% | 44 |
| **5 (materially significant)** | **0.08%** | **5** |
| 10 | 0.03% | 4 |
| 20 | 0.00% | 0 |

**Reading:** the RTC+B SOC-enforcement constraint binds *often but trivially*
(median cost 1.5 cents/MWh), and *materially* (> $5/MWh) on only ~5 days. The
ancillary market is saturated and cheap, so a battery rarely has to sacrifice
arbitrage to back its reserves — the cost of the rule is small except in scarcity.

**This is a valid measurement, not a null.** `psi_up` is the marginal COST of one
regulatory constraint, not revenue. A small shadow price means the rule is not
taxing the operator much — consistent with, and partly explanatory of, a
profitable fleet.

## 5. Material binding days are scarcity events

The five days with `psi_up > $5` (contingency, 2 h):

| day | psi_up max $ | energy price max that day $ | binding intervals |
|---|---|---|---|
| 2026-03-23 | 12.2 | 950 | 6 |
| 2026-03-24 | 11.0 | 149 | 3 |
| 2026-04-27 | 15.6 | 855 | 2 |
| 2026-05-26 | 9.4 | 224 | 1 |
| 2026-06-06 | 17.5 | 219 | 3 |

The two largest-frequency days (Mar 23, Apr 27) are unambiguous scarcity events
(energy to $950 and $855). The mechanism is genuine, not noise: `psi_up` spikes
when holding charge for reserves forces the battery to forgo a large arbitrage.

## 6. Verification checks (spec §7) — all pass

- **No dumping** (Prop 3): max over all t of min(c_t, d_t) = 0 to solver
  tolerance, every run. The battery never simultaneously charges and discharges.
- **Complementary slackness:** max |dual × slack| on the SOC ceiling = 0 to
  tolerance, every run.
- **u = 0 recursion (sign check, Correction 2):** energy-only solve has
  `psi_up` identically 0 — the ancillary machinery collapses correctly when no
  reserves are sold.
- **Duration identity (check 4, contingency 2 h):** perturb E_max by ±1%,
  re-solve; the LEFT and RIGHT finite differences of the optimum bracket the
  multiplier sum `sum_t(lambda_bar + psi_dn)` (psi_dn ≡ 0 here):
  fd_left = 4649.22, **sum = 4635.91**, fd_right = 4609.65. The multiplier sum
  sits between the one-sided differences, as expected for a kinked, degenerate LP
  (Decision: compute one-sided, never central). This validates the dual
  extraction that Q2 and Q3 depend on.

## 7. Caveats that bound the reading

1. **Asymmetric gate (Decision 8).** Perfect foresight positions SOC to *dodge*
   the constraint better than any real operator can. So the measured `psi_up` is
   a **LOWER BOUND** on what a real, uncertainty-facing operator pays. "It binds"
   is conservative; "it binds cheaply" is a floor, not a ceiling.
2. **Summer is unobserved.** `psi_up` is a scarcity price, and ERCOT scarcity is
   overwhelmingly a July–September phenomenon; the window ends June 20. The
   monthly `psi_up > $1` interval counts are noisy and event-driven, NOT a clean
   seasonal ramp: Dec 21, Jan 58, Feb 18, Mar 49, Apr 86, May 20, Jun 56. April
   is the peak in-sample. But the peak scarcity season is structurally the one we
   have not seen, and by construction summer can only RAISE `psi_up`. Decision B2:
   build now, top up with summer 2026 data as a scheduled refinement (not a
   blocker — summer cannot reverse a proceed).
3. **All-products numbers carry the Regulation artifact** (§3, Decision 2). Use
   contingency-only for any `psi_up` claim.

## 8. Counterfactual duration curves (Q3 preview, Decision 13)

Perfect-foresight objective ($ over the window) by duration and product set. The
difference between columns attributes value; up-reserve value routes through
`lambda_bar` bundled with arbitrage, so this counterfactual — not a multiplier
split — is the correct decomposition.

| E (h) | energy-only | +contingency | +all-products |
|---|---|---|---|
| 1 | 8,588 | 10,118 | 16,345 |
| 2 | 13,206 | 15,656 | 21,943 |
| 4 | 18,709 | 23,110 | 29,161 |

The contingency contribution (+contingency − energy-only) rises with duration:
$1,530 → $2,450 → $4,401 (1 → 2 → 4 h). A longer battery can back more
long-duration Non-Spin, so up-reserve *does* create duration value — bundled in
`lambda_bar`, exactly as Decision 13 anticipates. In the contingency-only run
psi_dn ≡ 0, so this duration curve is pure arbitrage plus that bundled
up-reserve room (Decision 14) — the gate cannot misfire on the down side.

## 9. Gate verdict

**Qualified PROCEED** (Decision 18).

- **By the frozen pre-registration** (tol = 1% median): the contingency-only 2 h
  cell binds in 8.00% of intervals across 129 days, clearing the ">5% / ≥10 days"
  thresholds. The kill condition (< 1% AND < 5 days, surviving the pre-RTC tau
  re-run) is **not** triggered. The pre-RTC tau re-run (Decision 9) is therefore
  not required to conclude, and was not run.
- **By economic honesty:** the constraint binds *cheaply* (median $0.015/MWh,
  material > $5 on ~5 days), because the AS market is saturated — AND the peak
  scarcity season is unobserved, with `psi_up` a lower bound regardless.

**Reframe (Option C intact, Decision 18):** Q2's answer is *"RTC+B's per-resource
SOC enforcement is cheap in today's saturated AS market — median ~$0/MWh, spiking
to $10–33/MWh on scarcity days — and this is a lower bound pending summer."* That
is a real, defensible finding, not the absence of one. Next: the value-of-foresight
build (Decisions 19–20), which recomputes `psi_up` and the duration curve under a
*realistic causal operator* rather than a clairvoyant.
