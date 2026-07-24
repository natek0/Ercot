# Stage 7 — fleet benchmark: build record, results, decisions & self-critique

The complete record of what was built for Stage 7 (the ~300-asset ERCOT fleet benchmark from 60-day
disclosure), the results, the decisions and their rationale, and the known problems — written so a
reviewer has full context. Companion to `reports/stage7_plan.md` (the pre-registration) and plan
Part XIV Stage 7 / §VIII.5a item 3 / §X.7.

**Framing (non-negotiable, from the plan).** Modo Energy and Ascend Analytics sell products that do
this; it is NOT novel and must not be presented as such. The value is that it is open, reproducible,
and **externally checkable**: agreement with published benchmarks validates the pipeline, and it is
"validating an economic model against observed behaviour" — a named responsibility of the target
role (Base Power, Markets quant intern).

**Purpose.** Turn the single-asset study into a fleet-scale, externally-validated result: reconstruct
what the real ERCOT batteries EARNED, compute what each COULD have earned (its own perfect-foresight
ceiling), publish the capture distribution, and locate our modelled Stage-4 DP within the real fleet.

> **Round-2 update (post three-agent adversarial review + synthesizer, reports `stage7_review_*.md`).**
> The review verdict: **the reconstruction is sound — every headline reproduces to the dollar, no join
> fan-out, the AS two-settlement is the correct RTC+B structure (confirmed by the desk-quant reviewer)
> — no blocker.** The problems were two *overstated comparative claims*, now FIXED (all de-confounding,
> none manufactures a better number):
> - **Capture basis (A/A3, A/M1):** capture is now the **RT-physical realized value / RT ceiling on
>   traded days** (apples-to-apples) → **median 34%** (was 35%), **max 83%** (was an impossible 121%
>   from a two-settlement-numerator-vs-RT-ceiling mismatch); the ceiling now excludes ~10
>   pre-commissioning days it was inflated over (~3-4%).
> - **C1 (A2):** the shipped "$1.74 in a $1-4 band" was too lax (band widened post-hoc from $3-6).
>   Replaced with the **pre-registered MONTHLY test**: our shape **MATCHES Modo (Jan>Apr>Feb)** but the
>   **level is systematically ~21% light** (Jan 0.74, Feb 0.83, Apr 0.80). Honest verdict: **shape
>   validated, level tracks to ~20%** — NOT "validated" full stop. The ~20% residual is the diagnosable
>   finding (candidate causes: AS two-settlement under-count, telemetered-vs-SMNE energy, scarcity-day
>   node-price gaps).
> - **Joint capture (B1):** delivered the pre-registered **energy+AS joint** ceiling → fleet **joint
>   capture median 76% [95% CI 71-81%]**, squarely in the 50-80% "well-run operator" band. **This is
>   the key reframe:** the low energy-only 34% is NOT a skill deficit — operators rationally hold SOC
>   to sell (cheap but positive) AS, sacrificing energy arbitrage; the joint number is the fair measure
>   of fleet skill, and it is healthy.
> - **CIs + gap audit + figure (B2, B3):** bootstrap CIs on the fleet median capture; a node-price gap
>   audit (4 days <90% coverage — a **genuine ERCOT NP6-905 gap** on the early-May scarcity block, a
>   fresh fetch returns the same partial data — <1% of $, documented); a fleet-capture distribution
>   figure. **ECRSMD (A/M4): REFUTED** — the raw DAM file has only `ECRSSD Awarded`; the parser is
>   correct and complete.
> - **Locate-our-policy (the pivotal must-fix) — FULL-FLEET FAIR RESULT:** re-run gross-vs-gross,
>   matched post-warm-up window (Feb-1+), ceiling on that same window (302 assets): **our DP median
>   energy capture 31% vs the fleet's matched-window 40%; our DP beats 28% of operators and ranks at
>   the ~29th percentile** (the shipped **10% / 14th was ~2x inflated** by a net-vs-gross +
>   warm-up-vs-full-window confound; the fair number matches the synthesizer's 40-asset ~32%/30th).
>   **The "our DP is information-limited" conclusion SURVIVES** — our price-only DP sits *below* the
>   fleet median but *not* near the bottom, and read against the fleet's **76% joint** capture the gap
>   is squarely an exogenous-information limit (no NWP/load/co-located-gen), confirming the Stage-5
>   thesis externally. Figure: `reports/figures/fig7_fleet_capture.png`. §8 below is the ORIGINAL
>   self-critique; these Round-2 fixes resolve items 1-6 and 8.

---

## 1. Data acquisition (all public, free, stream-and-discard)

- **60-Day SCED Disclosure** (`NP3-965-ER`) and **60-Day DAM Disclosure** (`NP3-966-ER`), retrieved
  via `/archive/{id}?download={docId}` with the **PUBLIC** key (spike finding — corrects the plan's
  "needs the ESR key"). Dedicated ESR files inside each daily zip: `60d_ESR_Data_in_SCED` (per 5-min:
  telemetered net output, State of Charge, Min/Max SOC, HSL, RT AS awards) and `60d_DAM_ESR_Data`
  (hourly: DA energy award, settlement point, DA price, DA AS awards + MCPC).
- **Stream-and-discard**: each ~48 MB daily zip is pulled into memory, the one ESR CSV extracted,
  aggregated 5-min→15-min, appended to DuckDB, and the zip discarded — **no bulk local storage**
  (~10 GB flowed through; persistent footprint <0.5 GB). Manifest table → resume-safe.
- **Node prices** (`NP6-905-CD`): each ESR settles energy at its own resource-node RT LMP; pulled per
  node (281 distinct), **one request/node via a large page size** after a 429 rate-limit fix
  (429-aware client + proactive pacing). Deduped 1,686/4.5M ERCOT price-correction rows.
- **RT MCPC** (`NP6-331`): reused from Stage 0 (system-wide, no locational component), loaded into
  `prices_mcpc_rt` (16,412 rows).
- **Coverage.** 327 ESRs; ~4.95M SCED 15-min rows; ~1.25M DAM hourly rows; window 2025-12-05 →
  2026-05-24; **170 manifest days but 161 distinct trading dates** (a few archives share operating
  days / a few missing — a documented minor gap).

## 2. Warehouse (DuckDB star schema)

`dim_esr` (resource, node, HSL, Min/Max SOC, **duration = MaxSOC/HSL**), `fact_sced_esr` (15-min RT:
telem output, SOC, RT AS awards), `fact_dam_esr` (hourly DA: energy award, node, DA price, DA AS
awards + MCPC), `stg_esr_physical`, `prices_node`, `prices_mcpc_rt`, `manifest`. **Integrity checks
that passed:** derived **duration median 1.64 h vs ERCOT's published fleet-average 1.65 h**
(independent validation); SOC within [0, MaxSOC] on 0/93,312 sampled rows.

## 3. Eligibility (data-hygiene rule, documented)

`eligibility()` drops assets that cannot carry a meaningful capture: **302 of 327 eligible**
(excluded: 17 power<0.5 MW stubs, 4 no-node, 3 duration<0.25 h degenerate-SOC, 1 duration>12 h
implausible). Returns a per-asset reason so the selection is reported, not hidden.

## 4. A1 — realized energy revenue, ceiling, capture

- **Two-settlement energy:** DA award × DA node price (hourly) + (telemetered output − DA award) ×
  RT node LMP × 0.25 (per interval). NULL-robust SQL; the hour-ending↔15-min join is unit-tested.
- **Per-asset ceiling:** the Stage-0 oracle LP on each asset's OWN node prices at its OWN HSL and
  MaxSOC, **c_deg=25, gross revenue reported** (realized is also gross; ceiling policy is
  degradation-aware so it does not over-cycle, then we read its gross energy revenue).
- **Results (302 eligible, 161 days):** energy **capture median 35%** (p25 21%, p75 46%); energy
  **$/kW-month median $1.03 / mean $1.15**; fleet energy revenue **$132.4M = DA $55.1M + RT-deviation
  $77.2M**. Robust: capture ∈ [−0.27, 1.2], no near-zero-ceiling outliers.

## 5. Phase B — ancillary revenue, total, C1 validation

- **DA AS** = Σ award × DA MCPC (hourly). **RT AS (two-settlement)** = Σ (RT award − DA award) ×
  RT MCPC × 0.25. Products: RegUp, RegDown, RRS(=PFR+FFR+UFR), ECRS, NonSpin. NULL-robust; the AS
  two-settlement join is unit-tested.
- **Results:** AS revenue **$54.2M** (DA $47.3M + RT-deviation $6.9M; **rt_as_total diagnostic
  $18.5M**). **Total revenue $186.5M**; **AS share 29%**; **total $/kW-month mean $1.74 / median
  $1.72**.
- **C1 (external validation).** Initial reference band ($3–6) was **stale** (2023–24 levels) and
  flagged our number as "outside → investigate." Corrected against Modo's ACTUAL settled figures for
  this window — **Jan-26 $3.94, Feb-26 $1.08, Apr-26 $3.12/kW-month** (2025 was the lowest in 3 years,
  ~$2.45/mo avg). Our **$1.74 is WITHIN that range → pipeline validated to first order.** On the low
  side (AS approximation + underperformers in the mean). Sources: Modo Energy ERCOT BESS monthly
  benchmarks.
- **AS share 29% (vs the historical ~80–90%)** is argued to be REAL: Modo confirms AS saturated and
  spreads compressed in 2025–26, pushing batteries toward energy; high-revenue months (Jan cold snap)
  were energy-scarcity-led — consistent with our own Stage 0–5 finding that value here is
  spike/energy-driven while AS is cheap. Argued, not proven.

## 6. Locate-our-policy — where our DP ranks in the real fleet

- Ran our **Stage-4 walk-forward DP** on each eligible asset's OWN node prices at its power/duration,
  energy-only, N_S=100, causal (like the real operators), reusing `WalkForwardDPPolicy` unchanged.
- **Results (302 assets):** our DP **energy capture median 10%** vs realized **35%**; our DP **beats
  the real operator on 13% of assets**; our DP median ranks at the **~14th percentile** of realized
  captures. Heterogeneous: we beat the ~13% who do energy poorly (deep-AS units, some realize
  negative energy), lose to the ~87% who arbitrage well.
- **Interpretation:** our modelled DP ranks near the bottom **because it is information-limited**
  (price-only kernel, no NWP/load/co-located-gen/better forecasts), NOT because the optimizer is
  weak. This **confirms the Stage-5 "bottleneck is exogenous signal" thesis externally**, against
  ~300 real batteries.

## 7. Deliverables & tests

`src/disclosure_ingest.py` (stream-and-discard ETL), `src/fleet_warehouse.py` (schema), `src/
fleet_prices.py` (node prices + RT MCPC), `src/stage7_run.py` (A1 + Phase B + locate). `tests/
test_stage7.py` — 14 tests (pure parsers, eligibility, both two-settlement SQL joins, manifest
resume, oracle ceiling, append column-name regression). Suite 117 green. Committed + pushed.

---

## 8. Self-critique — known problems, approximations, and open questions

Recorded so the review can cross-check and nothing is hidden. Roughly ordered by how much each could
change a headline.

1. **AS two-settlement mechanics are an APPROXIMATION (the load-bearing uncertainty).** Under RTC+B,
   AS is co-optimized in real time; the exact DA/RT AS settlement netting is subtle. Our two-settlement
   (DA award×DA MCPC + (RT−DA)×RT MCPC) gives AS $54.2M, but the `rt_as_total` diagnostic ($18.5M)
   shows a different assumption (RT-total not deviation) would change AS materially. C1 validated the
   TOTAL to first order, but AS specifically could be mis-stated, which would move the 29% AS share.
2. **Is 29% AS share real or is AS understated?** Historically ERCOT storage is ~80–90% AS. We argue
   the 2025–26 AS collapse + energy-led scarcity explains 29%, consistent with Modo and our own
   findings — but this is an argument, not a proof, and it hinges on (1) being right.
3. **Locate-our-policy comparison fairness.** (a) **Warm-up penalty:** our DP holds through its
   2-month walk-forward warm-up (earns $0) while the ceiling and the operators' realized both include
   those months → our capture is dragged down; a traded-window-matched comparison is fairer.
   (b) **Energy-only vs joint optimization:** the operators' "energy capture" is a by-product of a
   JOINT energy+AS strategy; comparing it to our pure-energy DP is not perfectly clean. (c) **N_S=100**
   (coarser than Stage 4's 200) slightly lowers our DP capture. (d) Our DP is **price-only** (no NWP).
4. **Energy settlement quantity.** RT energy uses telemetered net output; true settlement uses SMNE
   metered energy (`60d_SCED_SMNE_GEN_RES`). Telemetered output is a close proxy but an approximation.
5. **Ceiling convention (c_deg=25, gross).** A different degradation assumption changes the ceiling
   and thus every capture rate. Gross-of-degradation matches Modo but is revenue, not profit.
6. **C1 is not perfectly apples-to-apples.** We compare our fleet MEAN $/kW-month to Modo's published
   benchmark, whose methodology (a standard/representative asset, or fleet-average, mean vs median,
   TB2/TB4 metrics) may differ. A per-MONTH reconstruction vs Modo's monthly figures is the rigorous
   refinement; the current check is a window-level sanity band.
7. **161 vs 170 days** (some archives share operating dates / a few missing) — minor; affects the
   $/kW-month denominator slightly (months = 161/30.44).
8. **Node-price join coverage** < SCED rows (some SCED intervals lack a matching node price) — a small
   coverage gap that slightly understates RT energy for affected intervals.
9. **Survivorship / selection.** Universe = ESRs that appear in disclosure (settled revenue); the
   eligibility rule further drops 25. Documented, but the excluded set is not analyzed.
10. **Duration from telemetry** (MaxSOC/HSL) — a few implausible values were excluded; the rest are
    trusted without cross-checking to EIA-860 nameplate.
11. **Price impact / simultaneity (§XII.1)** not modeled — less relevant here (this benchmarks
    REALIZED behaviour, not a counterfactual fleet dispatch), but worth stating.

## 9. What is solid (stated plainly, so the review is balanced)

- The ingest is stream-and-discard, resume-safe, and tested; duration reproduces ERCOT's published
  fleet average (an independent check); SOC integrity holds.
- The two-settlement ENERGY reconstruction and both SQL joins are unit-tested on known examples.
- C1 validated the TOTAL revenue against the real Modo benchmark (after correcting a stale band) —
  the "externally checkable against reality" claim is literally satisfied.
- The locate-our-policy result is honest and humbling (our policy ranks low) and ties the fleet
  result back to the single-asset Stage-5 thesis — a coherent, non-self-congratulatory narrative.
