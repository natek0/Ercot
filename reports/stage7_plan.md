# Stage 7 — Fleet benchmark from 60-day disclosure: pre-registration & build plan

**Status: PRE-REGISTERED (committed before code, per the step0_preregistration.md precedent).**
This is the detailed operational plan; the design intent lives in plan Part XIV Stage 7. Scope,
data schema, storage architecture, reconstruction formulas, and the go/no-go gate are fixed here
so the build cannot drift or be tuned to a result.

## 0. Purpose, value, and framing

**What.** Reconstruct what the ~324 real ERCOT batteries actually EARNED from public 60-day
disclosure data, compute what each COULD have earned (its own perfect-foresight ceiling at its own
power, duration, and node), publish the cross-sectional distribution of capture rates, and locate
our modelled DP policy inside that real distribution.

**Value (why this is the highest-leverage add-on).** It attacks the study's two weakest points at
once: (i) it converts a single-asset null on a thin sample into a ~324-asset cross-section observed
across the *same* scarcity days (§VIII.5a item 3 — the strongest answer to the thin-sample
problem); (ii) it operates at *fleet* scale, which the target role names explicitly, and it is the
only component **externally checkable against reality**.

**Framing (non-negotiable, from plan Part XIV / §X.7).** Modo Energy and Ascend Analytics sell
products that do this. It is NOT novel and must not be presented as such. Its value is that it is
open, reproducible, and checkable: agreement with published benchmarks validates the pipeline,
disagreement is itself a finding. Present it as *validating an economic model against observed
behaviour* — a named responsibility of the role.

## 1. Spike findings (verified 2026-07-23; these ground the plan)

A read-only feasibility spike downloaded one real day (operating day 2026-05-24) and confirmed:

- **Access is via the PUBLIC key**, not the ESR key (the ESR key 401s on these products — this
  corrects the CLAUDE.md note). Products: `NP3-965-ER` = 60-Day SCED Disclosure (48 MB zip/day),
  `NP3-966-ER` = 60-Day DAM Disclosure (8 MB zip/day). Retrieval: `GET /archive/{id}` lists daily
  bundles (docId + postDatetime); `GET /archive/{id}?download={docId}` returns the day's zip.
- **`60d_ESR_Data_in_SCED`** (324 ESRs, per 5-min SCED interval, ~95k rows/day) contains
  everything: `Telemetered Net Output` (realized dispatch), `State of Charge`, `Minimum SOC`,
  `Maximum SOC` (**→ duration = MaxSOC/HSL, no external join needed**), `HSL` (power), and
  `AS Awards {NSPIN, RRSPFR, RRSFFR, RRSUFR, ECRS, REGUP, REGDN}` (real-time AS).
- **`60d_DAM_ESR_Data`** (319 ESRs, hourly, ~1 MB/day): `Awarded Quantity` (DA energy),
  `Settlement Point Name` (the resource node, e.g. `ABINDUST_RN`), `Energy Settlement Point Price`
  (DA price), and `{RegUp,RegDown,RRS,ECRS,NonSpin} Awarded + MCPC` (the entire DA AS side).
- **Post→operating-day lag is exactly 60 days** (post 2026-07-23 → operating day 2026-05-24), so
  our window (operating days 2025-12-05 → ~2026-05-24) maps to post dates ~2026-02-03 → 2026-07-23,
  ≈ 170 daily bundles.

Consequence: the reconstruction can be a proper two-settlement one (not a rough approximation),
and the resource-name-mapping headache is moot (post-RTC+B everything is consistently `_ESR1`-named
and the settlement point is handed to us).

## 2. Scope (fixed)

**In scope:** Phase A (energy) + Phase B (ancillary) + C1 (external validation), full window.
- A: ESR universe, physical params (power+duration), per-node prices, realized energy revenue,
  per-asset energy ceiling, cross-sectional capture, locate our DP.
- B: realized AS revenue (DA+RT), energy+AS ceiling, energy-vs-AS revenue split per asset.
- C1: reconstructed fleet-average \$/kW-month vs published Modo/Ascend benchmark.

**Descoped (with reasons, honest):**
- The plan's 3-way shortfall decomposition (forecast error / allocation / SOC management) →
  replaced by the *observable* pieces only: the energy-vs-AS split, and the gap between each asset's
  realized capture and OUR modelled capture on its own node (a clean "skill/information gap"). The
  finer forecast-vs-SOC attribution is not identifiable without each operator's forecast and intent;
  claiming it would be fiction.
- Degradation cost is NOT observed per operator → report **gross** revenue (also what Modo reports,
  so C1 stays comparable).
- Price impact (§XII.1) named, not modelled (single linear-θ sensitivity is a later option).

## 3. Data acquisition — the stream-and-discard architecture (NO 10 GB stored locally)

The raw download over the window is ~10 GB (8.6 GB SCED + 1.4 GB DAM), but **none of it is ever
stored**. The pattern (identical in spirit to `ingest.py`: fetch → transform → compact cache):

```
for each operating day in the window (resume-safe, see below):
    1. resolve the day's docId from the archive listing (filtered by postDatetime)
    2. GET the zip into MEMORY (io.BytesIO) — never written to disk
    3. open the zip in memory; extract ONLY the one inner CSV we need
       (60d_ESR_Data_in_SCED for NP3-965; 60d_DAM_ESR_Data + settlement-point cols for NP3-966)
    4. parse just that CSV, filter to ESRs, aggregate 5-min → 15-min settlement intervals
    5. APPEND the compact aggregated rows to the DuckDB warehouse
    6. mark the day done in the manifest table; let the ~48 MB blob be garbage-collected
```

**Peak local footprint** = one ~48 MB zip held transiently in RAM + the growing compact warehouse.
The 10 GB flows *through* memory; it never lands as files.

**What actually persists on disk (the storage budget):**
| artifact | approx size | location | committed? |
|---|---|---|---|
| DuckDB warehouse (facts + dims, aggregated) | ~150–300 MB | `data/warehouse_fleet.duckdb` | no (gitignored) |
| node RT prices (NP6-905, our ~324 nodes) parquet | ~50–150 MB | `data/raw/` | no (gitignored) |
| derived per-ESR revenue/ceiling/capture tables | < 5 MB | `data/raw/` | no (gitignored) |
| figures + writeup | < 1 MB | `reports/` | **yes** (deliverables) |

Total persistent local footprint ≈ **under ~0.5 GB**, all regenerable, none of it the raw zips.
**Cost = \$0** (ERCOT public API is free with existing keys; only bandwidth + time are spent).

**Resume + robustness (ERCOT's API is intermittently flaky):**
- A `manifest(operating_day, product, rows, status, fetched_at)` table records completed days; on
  restart the loop skips done days, so a dropped connection never restarts the whole 10 GB.
- Exponential backoff + capped retries per request; a per-day row-count assertion
  (≈ 324 ESRs × 288 SCED intervals for SCED; ≈ 319 × 24 for DAM) before a day is marked done.
- Optional `--sample-days N` flag: curate ~40 days (all scarcity days + a random sample) to cut the
  download to ~2.2 GB — a documented sampling choice, fallback only, not the default.

**Node prices & RT MCPC:** each ESR's node comes from `Settlement Point Name`. Pull NP6-905-CD by
delivery date (all settlement points/day, filter to our ~324 nodes) via the existing `ercot_api`
client. RT MCPC (NP6-331-CD) is already ingested for Stages 0–4 and is reused for RT AS pricing.

## 4. Warehouse schema (DuckDB star schema)

```
dim_esr(resource_name PK, settlement_point, qse, hsl_mw, max_soc_mwh, min_soc_mwh,
        duration_h = max_soc_mwh / hsl_mw)                      -- one row per ESR
fact_sced_esr(resource_name, ts_15min, telem_output_mwh, soc_mwh,
              as_award_{nspin,rrs,ecrs,regup,regdn}_mw)          -- 15-min, RT side
fact_dam_esr(resource_name, delivery_date, hour_ending, da_energy_award_mw, da_spp,
             da_as_award_{regup,regdn,rrs,ecrs,nonspin}_mw, da_mcpc_{...})  -- hourly, DA side
prices_node(settlement_point, ts_15min, rt_lmp)                 -- RT node LMP
prices_mcpc_rt(ts_15min, mcpc_{regup,regdn,rrs,ecrs,nonspin})   -- reused from Stage 0
manifest(operating_day, product, rows, status, fetched_at)      -- resume bookkeeping
```

The feature/aggregation logic is expressed as **SQL views** over these tables (per the plan's
"SQL as evidence, not decoration" commitment, §IX.4). This is the natural home for a real star
schema — reconstruction is a set of joins and group-bys, which is exactly what SQL is for.

## 5. Realized-revenue reconstruction (formulas, per ESR)

Two-settlement, gross of degradation. Charging = negative output = a purchase (negative revenue).

- **Energy (DA position + RT deviation):**
  $R_{energy} = \sum_h A_h \cdot P_h^{DA} + \sum_t (o_t - A_t)\cdot P_t^{RT}\cdot \Delta t$
  where $A_h$ = DA energy award (MW) for hour $h$, $P_h^{DA}$ = DA node price, $o_t$ = telemetered
  output (MW) in 15-min interval $t$, $A_t$ = the hourly award mapped to interval $t$, $P_t^{RT}$ =
  RT node LMP, $\Delta t = 0.25$ h.
- **Ancillary (capacity payments):**
  $R_{AS} = \sum_k \big[ \sum_h w_{k,h}^{DA}\cdot m_{k,h}^{DA} + \sum_t w_{k,t}^{RT}\cdot m_{k,t}^{RT}\cdot\Delta t \big]$
  over products $k$, where $w^{DA},m^{DA}$ are DA award/MCPC (from the DAM file) and $w^{RT},m^{RT}$
  are RT award (SCED file) / RT MCPC (NP6-331). **Named approximation:** the exact DA/RT AS
  two-settlement netting under RTC+B is subtle; this sums the DA capacity payment and the RT
  incremental award. C1 (§8) is what tells us whether this is close enough.
- **Total realized** $= R_{energy} + R_{AS}$, reported gross, normalized to **\$/kW-month** on HSL
  (the industry convention; makes assets and the Modo benchmark directly comparable — Decision 13).

## 6. Per-asset perfect-foresight ceiling (reuse the oracle)

For each ESR, run the existing `oracle.solve` on its own node RT price path, at its own $HSL$
(power) and $MaxSOC$ (energy), producing $\mathcal{V}^{PF}_i$ — energy-only and energy+AS (the
reserve-co-optimised oracle from Stage 4). **Capture** $\kappa_i = R_i / \mathcal{V}^{PF}_i$.
Guardrails from §VIII.4: never report a capture for an asset whose $\mathcal{V}^{PF}$ is near zero;
sanity-band the fleet distribution against the 50–80% typical range (a fleet median near 100% ⇒
suspect a reconstruction leak; near 0% ⇒ suspect a units/sign bug).

## 7. Cross-section + locating our policy (the punchline)

- Publish the **distribution of $\kappa_i$** across the ~324 ESRs (energy-only and energy+AS), and
  the **energy-vs-AS revenue split** per asset (directly observable, genuinely interesting).
- Place each real asset on our **Stage-4 Q3 duration curve** (we now know each asset's duration).
- **Run our Stage-4 DP** on each asset's node price path at its own power/duration; compute our
  modelled capture per asset and report the **percentile at which our policy would rank** in the
  real fleet. Honest both ways: rank high ⇒ the policy is good; rank low ⇒ real operators exploit
  information we don't model (co-located solar, bilateral contracts, better forecasts) — which is
  the §2-writeup "bottleneck is exogenous signal" thesis confirmed from the outside.

## 8. C1 — external validation (the credibility multiplier; do EARLY, with §5)

Compare our reconstructed **fleet-average \$/kW-month** (by month) to Modo Energy's published ERCOT
BESS revenue index (free summaries) and any Ascend figure available. **Go/no-go gate:** if our
monthly fleet-average is within a stated tolerance (target: within ~20%, and the same month-to-month
*shape*) of the published benchmark, the reconstruction pipeline is validated and the cross-section
is trustworthy. If not, the discrepancy localizes the reconstruction error (most likely in the AS
two-settlement, §5) and is fixed or reported before any capture-rate claims are made. Build §5 and
§8 together — do not defer validation to the end.

## 9. Risks & mitigations

| risk | mitigation |
|---|---|
| ERCOT API hangs/flakiness | manifest-based resume + backoff; per-day row-count asserts |
| AS two-settlement netting wrong | C1 validation catches it; report AS split so the error is visible |
| schema drift across the window | assert expected columns per day before parsing; fail loud |
| selection/survivorship | universe = ESRs that settled revenue in-window; report N and exclusions |
| node price gaps | timestamp-gap audit (reuse Stage 1); drop/flag assets with sparse node data |
| reconstruction ≠ true settlement | it is an open, documented approximation; C1 is the reality check |

## 10. Deliverables & build order (milestones)

1. `src/disclosure_ingest.py` — stream-and-discard fetcher (archive listing, in-memory unzip, ESR
   filter, 15-min aggregation, manifest/resume). **Milestone A0:** one week of data in the warehouse.
2. `src/fleet_warehouse.py` — DuckDB schema + SQL views (dims, facts, reconstruction views).
3. `src/stage7_run.py` — realized-revenue reconstruction (§5), per-asset ceilings (§6), capture
   cross-section (§7), and **C1 validation (§8) run alongside §5**. **Milestone A1:** energy-only
   cross-section + C1 first pass. **B:** add AS. **C:** locate-our-policy + writeup.
4. `tests/test_stage7.py` — reconstruction unit tests on a synthetic ESR (known dispatch/prices →
   known revenue), duration derivation, manifest/resume, a leak-free assertion on the ceiling.
5. `reports/stage7_notes.md` — findings; figures in `reports/figures/`. Update the README + plan.

## 11. Pre-registration commitments (freeze before code)

- Universe = all resources of `Resource Type == ESR` that settled energy or AS revenue in the window.
- Revenue is **gross** (degradation not observed), normalized to **\$/kW-month** on HSL.
- Capture ceiling is **full-window perfect foresight** per asset (never daily-reset), on the asset's
  **own node** prices, at its **own** HSL and MaxSOC.
- C1 tolerance and the fleet sanity band (§VIII.4) are the acceptance gates; a fleet median outside
  50–80% triggers a bug hunt before any headline is written.
- The 3-way decomposition is **out**; only the observable energy/AS split + our-policy skill gap are
  reported. This descoping is declared, not silent.
