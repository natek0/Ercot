# Stage 7 review — reconstruction / ETL audit (adversarial data-engineer lens)

Reviewer mandate: assume the reconstruction is wrong until reproduced against the warehouse. Every
claimed bug below is labelled **verified** (reproduced against `data/warehouse_fleet.duckdb`) or
**suspected** (could not fully reproduce). I read all Stage-7 source + the record, then ran ~15
direct DuckDB query passes and hand-reconstructed one asset end-to-end.

## Bottom line

**The reconstruction is fundamentally SOUND.** Every headline aggregate reproduces to the dollar
from the current warehouse, there is no join fan-out anywhere, the two-settlement energy SQL
hand-verifies exactly, DST is handled correctly, and the AS netting is structurally right. There is
**no blocker**. The findings are second-order biases and honest-reporting sharpenings, none of which
reverses a headline. The single highest-value fix is **M1 (ceiling window mismatch)** because it is a
clean, systematic, ~3% bias on *every* capture number and is trivially correct to fix.

### What I reproduced exactly (stated plainly, so the review is balanced)
| quantity | notes claim | my independent recompute |
|---|---|---|
| DA energy | $55.1M | **$55.114M** ✓ |
| RT-deviation energy | $77.2M | **$77.278M** ✓ |
| DA AS | $47.3M | **$47.259M** ✓ |
| RT-AS incremental | $6.9M | **$6.920M** ✓ |
| RT-AS total (diagnostic) | $18.5M | **$18.513M** ✓ |
| Total revenue | $186.5M | **$186.5M** ✓ |
| AS share | 29% | **29.0%** ✓ |
| Total $/kW-month | mean $1.74 / med $1.72 | **$1.74 / $1.72** ✓ |
| capture | med 35% / p25 21% / p75 46% | **35% / 21% / 46%** ✓ |

Additional things I checked and found **correct**:
- **No join fan-out.** 0 duplicate keys in `fact_sced_esr(resource,ts)`, `fact_dam_esr(resource,date,HE)`,
  `prices_node(sp,ts)`, `prices_mcpc_rt(ts)`. The single riskiest ETL failure mode (row multiplication
  through the two-settlement joins) is clean. This is the most important positive result.
- **Two-settlement energy hand-check.** For `ADL_ESR1` I re-derived DA=$68,787.9 and RT-dev=$95,887.0
  from the raw facts in Python; the SQL returns the identical figures.
- **DST spring-forward is handled correctly.** On 2026-03-08 the DAM has HE {1,2,4..24} (HE3 skipped)
  and SCED has wall-hours {0,1,3..23} (hour-2 skipped); `extract(hour)+1` maps the 3am hour to HE4,
  which exists → the join aligns. The unmatched-award rate on Mar-8 (4.9%) is in line with a normal
  day (Mar-9: 3.8%). No DST break.
- **AS two-settlement netting is structurally right.** `rt_as_incr = Σ(RT_award − DA_award)·RT_MCPC·0.25`
  is the correct deviation; `rt_as_total` is used ONLY as a printed diagnostic and is *not* summed into
  the headline, so there is no double-count. RRS = PFR+FFR+UFR is mapped consistently on both DAM and
  SCED sides, priced at the single RRS MCPC (correct — RRS clears as one product).
- **Sign conventions correct.** DA energy award and telemetered output are signed (charging negative,
  −240..+240 MW); all AS awards and all RT MCPC values are ≥0 (capacity). Charging is a purchase
  (negative revenue) throughout.
- **RT MCPC covers 100% of SCED timestamps** (4,954,905 / 4,954,905) — no AS-side price gap.
- **Ceiling LP is deterministic** (bit-identical on re-solve) and node-priced (all 281 nodes present in
  `prices_node`, 0 missing-node).
- **Eligibility exclusions are immaterial to the fleet total** — the 25 excluded assets carry a net
  **$0.01M**, so dropping them does not bias the $186.5M or the $/kW-month.
- **Partial-coverage normalization is immaterial** — only 13/302 eligible assets have <161 active days
  (min 103); recomputing $/kW-month on each asset's OWN active-day count vs the fixed 161-day
  denominator changes mean/median by <$0.01. The "$1.74 is on the low side" is NOT a normalization
  artifact.

---

## Findings (severity-ordered)

### M1 — Ceiling is solved over the full node price path, including ~10 days the asset never traded → systematic ceiling inflation, capture understated ~3% on every asset. **[major / verified / raises-bar]**

**What.** `energy_cross_section` fetches `SELECT rt_lmp FROM prices_node WHERE settlement_point=? ORDER BY ts_15min`
(src/stage7_run.py:190) and solves the PF ceiling over the *entire* node series. But `prices_node` was
ingested for the full window [2025-12-05, 2026-05-24] (170 days), whereas the SCED disclosure — the
realized side — only covers 161 distinct dates. The 10 dates present in `prices_node` but absent from
the SCED universe are **exactly** the 10 DAM-only days (Dec 6,7,25; Mar 3,4,5,7,14,29; Apr 21) whose
SCED archives failed at ingest.

**Where.** src/stage7_run.py:190-192 (`asset_energy_ceiling` gets the full-window price vector);
`capture = realized_energy_rev / ceiling_gross` at :196.

**Why it's wrong (reasoning).** Capture is `realized / ceiling`. The clairvoyant ceiling is handed
~10 extra days of arbitrage opportunity the real operator never had a shot at (no SCED/dispatch on
those days), so the denominator is inflated and every capture rate is biased **down** by the value of
those extra days. I measured this on `ADL_RN`: ceiling_gross over the full 16,294-point path = $582,733
vs over the SCED-covered dates only = $565,416 — a **+3.06% inflation**. It is systematic (same 10 days
for every asset) and larger for the 13 partial-coverage assets.

**Fix (reasoning).** Restrict the ceiling price path to the timestamps the asset actually operated —
`... WHERE settlement_point=? AND ts_15min IN (SELECT ts_15min FROM fact_sced_esr WHERE resource_name=?)`,
or minimally to the SCED-covered date set. This makes the ceiling "what this asset could have earned in
the window it was dispatchable," which is the correct clairvoyant counterfactual and the only one that
puts numerator and denominator on the same days. Effect: median capture rises ~35% → ~36%; the fix is
correct because it removes opportunity the operator provably could not act on.

### M2 — Node-price coverage gap is NOT diffuse; 96% of it is the May 1-5 block, concentrated on scarcity days, and it is silent. **[major / verified / raises-bar]**

**What.** 106,297 SCED rows (2.15% of all rows; 35,633 = 0.77% of *eligible* rows) have no matching
node price and are dropped by the inner join in the RT-deviation CTE (src/stage7_run.py:84). The notes
(§8 item 8) call this "a small coverage gap that slightly understates RT energy." It is not diffuse:
**34,126 of the 35,633 eligible unpriced intervals (96%) fall in 2026-05-01..05**, and those days
include price spikes (May-2 max $2,046; May-5 max $5,474). Each affected node (DKNS_ESS_RN, DC2SES_ALL,
PYR_PYRON1, RRC_WIND_ALL, …) has full coverage before and after but a hole in that 5-day window.

**Where.** `fetch_one_node` (src/fleet_prices.py:31-51) issues ONE request per node with a large page
size and has **no per-node row-count assertion**; the RT-deviation SQL inner-joins `prices_node`, so a
missing price silently contributes $0. The plan §9 promised "node price gaps → timestamp-gap audit
(reuse Stage 1); drop/flag assets with sparse node data" — grep confirms **no such audit exists** in
`src/fleet_prices.py` or `src/stage7_run.py` (assertions live only in the Stage-1 `src/warehouse.py`).

**Why it's wrong (reasoning).** Silently dropping intervals is defensible only if the drops are random.
Here they are anti-random — they land on the highest-value days of the window — so the reconstruction
loses precisely the scarcity revenue a battery desk cares most about. A promised mitigation was not
executed, and the failure is invisible without an audit. For a "would a battery-desk quant trust this"
bar, this is the class of defect that erodes trust even when the dollar total barely moves.

**Magnitude (honest).** Valued at the fleet-median LMP for each missing interval, the omitted eligible
RT-deviation is ~$0 (the specific affected nodes had ~net-zero deviations at typical prices), so the
**measured aggregate impact is <1%** and does not move the $186.5M. But that proxy understates the tail:
on the May-5 spike the true node LMP could be $2k-5k and any nonzero deviation is lost. So: small
measured number, real tail risk, and a genuine process gap.

**Fix (reasoning).** (a) Add a per-node expected-row assertion to `fetch_one_node` (`≈ 96 × n_days`) and
re-fetch nodes that come up short — ERCOT most likely had not yet posted May 1-5 for those nodes at
fetch time, so a re-run now would fill them. (b) Run the promised timestamp-gap audit over `prices_node`
and report/flag short nodes. Correct because it converts a silent omission into a loud, fixable one and
recovers the scarcity intervals.

### M3 — Ragged DA/RT date coverage: DA revenue spans 168 days, RT deviation 161; two-settlement is not date-aligned, and $/kW-month is normalized by the wrong day count. **[major / verified / neutral]**

**What.** `fact_dam_esr` covers 168 distinct delivery dates; `fact_sced_esr` covers 161. The `da` CTE
sums DA energy/AS over ALL 168 DAM-days, but the RT-deviation CTE only exists where SCED exists (161
days). Concretely: on the **10 DAM-only days** the asset is settled at *exactly* its DA schedule with no
RT correction — that is **$2.0M of DA energy + $1.7M of DA AS = $3.7M** credited with zero RT
settlement. On the **3 SCED-only days** (Dec 5, Dec 31, May 3) the asset is settled fully in RT with a
0 DA position — **$1.3M** of RT-deviation. Separately, `months = 161/30.44` (src/stage7_run.py:184) is
used as the $/kW-month denominator even though DA revenue accrues over 168 days.

**Where.** `_REALIZED_ENERGY_SQL` `da` CTE (:74-77) sums unconditioned; RT CTE (:78-90) is SCED-gated;
`months = n_days/30.44` with `n_days = distinct SCED dates` (:183-184).

**Why it's wrong (reasoning).** A clean two-settlement reconstruction values the *same* operating hours
on both the DA and RT legs. Mixing 168 DA-days with 161 RT-days means (i) the 10 DAM-only days are
mis-settled (no RT deviation — for a fleet whose RT deviation is net +$77M positive, this understates
revenue on those days), and (ii) the per-asset $/kW-month divides 168-day DA revenue by a 161-day-month
denominator, slightly overstating the rate. The notes (§8 item 7) frame 161-vs-170 only as a denominator
nuance and miss the DA-settled-without-RT economic error.

**Fix (reasoning).** Restrict both the DA and RT legs to the intersection of covered dates (or,
preferably, re-ingest the 10 missing SCED days and the DAM for the 3 missing days so the window is
complete), and normalize $/kW-month by the actual covered-day count consistently on both legs. Correct
because two-settlement only nets properly when the DA and RT positions describe the same hours.

### M4 — DAM ECRS reads only `ECRSSD Awarded`; a second ECRS column (ECRSMD) would be silently dropped, creating a DAM/SCED asymmetry in the AS deviation. **[major-if-true / suspected / neutral]**

**What.** `parse_dam_esr` maps `da_ecrs_mw = _num(df["ECRSSD Awarded"])` (src/disclosure_ingest.py:94),
i.e. only the ECRS-SD subtype. The SCED side uses a single total `AS Awards ECRS`. If the DAM ESR file
also carries an ECRS-MD (manual-dispatch) award column for storage, it is dropped, so DA ECRS is
understated while SCED ECRS is total → the RT deviation `(SCED_ecrs − DA_ecrs)` is overstated.

**Why it's wrong / why suspected.** I could not open a raw NP3-966 daily file in this session (no
credentials / no cached DAM CSV), so I cannot confirm whether an ECRSMD column exists. DA ECRS is $8.79M
of the $47.3M AS total, so a partial miss could move AS by a few $M and shift the 29% AS share. It is
plausibly benign (batteries typically clear ECRS-SD), but it is the one product mapping with a
name-level asymmetry between the two files.

**Fix (reasoning).** Print the raw DAM header once and assert the ECRS award column set; if an ECRSMD
column exists, sum it into `da_ecrs_mw` (mirroring the RRS legs). Correct because DA and RT must map the
same product scope for the deviation to net.

### m1 — Capture is computed on mismatched price bases (RT-node ceiling vs DA+RT realized) → capture can exceed 1, and the §VIII.4 sanity guard is ill-posed. **[minor / verified / raises-bar]**

**What.** The ceiling is pure RT-node perfect-foresight arbitrage; realized is the DA+RT two-settlement.
Because DA prices ≠ RT prices (DA avg $35.3 vs RT $31.5), a DA-heavy asset can beat the RT-only
clairvoyant: `PALACIOS_ESR1` has realized energy $230,517 > ceiling $190,503 → **capture 121%**. The
plan §6 / §VIII.4 guard ("fleet median near 100% ⇒ suspect a leak") is not well defined against a
ceiling that is not an upper bound on the reported numerator.

**Why it matters + magnitude (reasoning).** I computed the apples-to-apples alternative — value each
operator's *physical* dispatch (`telem`) at the RT node price, the same basis as both the ceiling and
our DP: fleet physical-@-RT energy = $125.7M vs two-settlement $132.3M (the $6.6M gap is the DA/RT
contango operators captured). Median capture on this basis is **33% vs the reported 35%**, and it has
**0 assets >1** (vs 1) and 19 negative (vs 22). So the DA-basis confound is real but only ~2pp — it does
**not** overturn the "our DP ranks low" punchline (our DP median 10% is still far below 33%). I verified
the confound rather than assuming it was large.

**Fix (reasoning).** Report capture on the RT-physical basis (telem·RT_LMP) as the primary metric — it
is bounded by the ceiling, directly comparable to our RT-only DP, and eliminates the >100% artifact —
and report the two-settlement number as the actual-settlement figure alongside. Correct because a
"capture" only means something when numerator and denominator share a price basis.

### m2 — 22 negative-capture assets are zero-DA-energy AS/solar units; an energy-arbitrage ceiling is meaningless for them and drags the median. **[minor / verified / neutral]**

**What.** All 22 negative-capture assets (RHA, QTUM_SLR, VERT_ESS, HEN, GAIA_SLR, …) have
`da_energy_rev = 0` and negative RT deviation — they only charge in RT (energy is a cost center) and earn
on AS / co-located generation. Their energy capture (realized energy / PF energy ceiling) is negative by
construction and is not a meaningful "how well did they arbitrate energy" number.

**Why / fix (reasoning).** Comparing an energy-arbitrage ceiling to an asset that does not attempt
energy arbitrage mislabels intent as failure and pulls the fleet median down. Segment the cross-section
into energy-participating vs AS/solar-only assets (e.g. flag assets with DA energy award ≈ 0 and/or a
high AS share) and report the energy-capture distribution on the energy-participating subset, keeping the
full-fleet number as context. Correct because the capture metric assumes an energy-arbitraging asset.

### m3 — The cached energy cross-section is stale relative to the warehouse; no consistency guard. **[minor / verified / raises-bar]**

**What.** `data/raw/stage7_energy_cross_section.parquet` (mtime 16:32) predates the final node-price
ingest into the warehouse (mtime 17:28). Recomputing `_REALIZED_ENERGY_SQL` against the current
warehouse gives RT-deviation revenue differing from the cache on 274 assets by up to $2,736 (BLSUMMIT_ESR2),
$132.357M cached vs $132.392M fresh — **$35k / $132M = 0.03%** aggregate. DA revenue is identical (DAM
unchanged); the delta is entirely the post-cache prices_node backfill.

**Why / fix (reasoning).** The deliverable cache and the committed warehouse disagree, so a reviewer who
re-runs `energy_cross_section(use_cache=False)` gets different (correct) numbers than the cache-driven
`--phase-b` / `--locate`. The dollar effect is negligible, but the pipeline is not bit-reproducible from
the current warehouse. Fix: rebuild the cache as the last step after every ingest, and store a cheap
warehouse fingerprint (row counts + max(ts) per table) in the parquet metadata; on load, assert it matches
or invalidate. Correct because a cache must be provably a function of its inputs.

### m4 — Warehouse duration median is 1.705h, but the notes claim 1.64h. **[minor / verified / neutral]**

**What.** `SELECT median(duration_h) FROM dim_esr` = **1.705** (eligible subset 1.703). The notes (§2)
and the plan-level "integrity check" report **1.64h vs ERCOT's 1.65h**. The validation conclusion (≈ERCOT
1.65) still holds at 1.70, but the specific number a reviewer recomputes does not match the record.

**Why / fix.** Either the 1.64 predates the final dim rebuild or it used a different definition (e.g.
`(MaxSOC−MinSOC)/HSL`). Correct the notes to the reproducible 1.70 (or document the exact derivation of
1.64). A validation number that does not reproduce weakens the very check it supports.

### m5 — Fleet total sums all 327 assets while capture / $-per-kW use the 302 eligible. **[minor / verified / cosmetic]**

**What.** `_print_fleet` computes `tot = df["total_rev"].sum()` over all 327 (src/stage7_run.py:254-255),
but the $/kW-month and capture use only the 302 eligible. The 25 ineligible carry a net **$0.01M**, so
the numbers are unaffected, but the universe should be stated consistently (report both as 302-eligible,
or footnote that the $186.5M total includes the immaterial ineligible tail).

### m6 — The "SOC within [0, MaxSOC]" integrity claim is false at the population level. **[minor / verified / cosmetic]**

**What.** Notes §2 report "SOC within [0, MaxSOC] on 0/93,312 sampled rows." The full `fact_sced_esr.soc_mwh`
ranges **−703.6 to 983.04** — physically impossible negatives and implausible highs (telemetry glitches).
SOC is not used anywhere in the revenue reconstruction, so **no number changes**, but the stated integrity
check is overstated (the sample missed the glitches). Fix: report the true SOC range and note SOC is
diagnostic-only, or add a clamp/flag. Correct because an integrity claim should describe the population.

### p1 — Telemetered output is a proxy for SMNE settlement quantity. **[polish / suspected / neutral]**
Acknowledged (§8 item 4). The mean of 5-min telemetry ≠ the SMNE metered energy ERCOT actually settles.
I cannot quantify without `60d_SCED_SMNE_GEN_RES`. Worth naming the expected direction: telemetry
typically overstates delivered energy slightly vs meter, so RT revenue may be marginally optimistic.

---

## Resume / interview value (data-engineering lens)

**Raises the bar (keep / lead with these):**
- **Stream-and-discard ETL with manifest resume** over ~10 GB is exactly the "reproducible reconstruction
  of real market data" signal Base's Markets team asks for. That it reproduces to the dollar and has zero
  join fan-out is the strongest thing here — say so explicitly.
- **DST correctness** on the spring-forward day is the kind of edge case that separates a quant who tested
  their joins from one who didn't. Add one assertion/test that pins the Mar-8 HE↔15-min alignment and it
  becomes a talking point.
- **Honest external validation (C1).** "Validated to first order" against Modo's *actual* settled window
  ($1.08-$3.94/kW-mo) — with the stale-band correction shown — reads as someone who checks their own work
  against reality. Do not upgrade "to first order" to "validated"; the qualifier is the credibility.
- **The apples-to-apples capture check (m1)** is a strong interview story: "I suspected the DA/RT
  price-basis mismatch inflated the locate gap; I recomputed on the physical-@-RT basis and it moved only
  2pp, so the information-gap conclusion survives." That is exactly the adversarial self-check a desk wants.

**Lowers the bar (fix before showing):**
- The **silent May-1-5 scarcity-day price gap with no audit** (M2) is the one a data-savvy interviewer
  would find in five minutes and it undercuts the whole "trust the numbers" pitch. Running the promised
  gap audit + a per-node row-count assert is cheap insurance and itself a positive signal.
- **Capture >100% (m1)** and the **1.64-vs-1.70 duration mismatch (m4)** are small but look sloppy if a
  reviewer recomputes; fixing the basis and the number removes easy objections.
- The **stale cache (m3)** means the committed artifact and warehouse disagree; a fingerprint-checked
  cache turns "reproducible?" from a question into a demonstrated property — squarely the TDD/CI signal
  the role names.

## Priorities
1. **M1** ceiling window mismatch (systematic ~3% on every capture; trivial fix) — highest value.
2. **M2** run the gap audit + row-count assert, re-fetch May-1-5 nodes (trust).
3. **m1** report capture on the RT-physical basis (removes >100%, cleans the locate comparison).
4. **M3 / M4** align the DA/RT date windows; verify the ECRS column set.
5. **m3-m6** cache fingerprint, correct the duration & SOC & universe statements in the notes.
