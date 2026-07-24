# Stage 7 review — SYNTHESIS (reconciling the three adversarial reviews)

Synthesizer role: fourth reviewer. I read all three reports in full (recon / quant / method), the Stage-7
source + record, and ran my own computations against `data/warehouse_fleet.duckdb` to resolve the one
conflict the three could not settle among themselves. Every number below labelled "I computed" is
reproduced this session; the fair-locate re-run and the C1 monthly table are mine, not carried from a
reviewer.

**One-line bottom line.** The reconstruction is SOUND and reproduces to the dollar (all three agree, recon
verified it line-by-line). Two *comparative* headlines are confounded/overstated and must be restated —
the "our DP ranks 14th percentile" locate and the "C1 validated" band. I adjudicated the locate conflict
by direct computation: **on a fair gross-vs-gross, matched-window, traded-day-ceiling basis the DP median
capture is ~32% vs realized ~40%, ranking ~30th percentile — the "information-limited / below median"
punchline SURVIVES, but the shipped "14th percentile" was inflated ~2× by confounds.** Nothing here
reverses the honest framing; every fix de-confounds.

---

## 1. Deduplicated finding map (who raised what; convergence = strong signal)

Convergence key: ●●● all three, ●● two, ● one. "Converged" findings are the load-bearing ones.

| # | Finding | recon (A) | quant (B) | method (C) | Conv | My verdict |
|---|---|---|---|---|---|---|
| F1 | **Locate net-vs-gross numerator** (DP profit is net of c_deg=25; realized & ceiling gross) | — | M1 | M1(ii) | ●● | CONFIRMED, ~2× |
| F2 | **Locate warm-up denominator** (DP earns \$0 Dec+Jan; ceiling is full-window; ~40% of value in warm-up) | — | M2 | M1(i) | ●● | CONFIRMED (ceiling match/full = 0.56) |
| F3 | **Locate interpretation confounded** ("info-limited" overreach) — *the key conflict* | m1 (survives ~33%) | M3 (may NOT survive, ~25-30%) | M1 (survives ~18-20%) | ●●● | **RESOLVED → survives at ~30th pct, capture ~32%** |
| F4 | **Ceiling over ~10 NON-TRADED days** (161 SCED vs 171 price days) | M1 (~3%) | (in M2/m7) | m1 (commissioning) | ●●● | CONFIRMED ~3-4% |
| F5 | **Capture basis mismatch** (RT-only ceiling vs DA+RT realized → capture>1, PALACIOS 1.21) | m1 (2pp) | M4 | — | ●● | CONFIRMED |
| F6 | **DA/RT/ceiling date windows not matched** (161/168/171) | M3 | m7 | m1 | ●●● | CONFIRMED |
| F7 | **C1 band too wide + monthly check skipped + ~20-28% level shortfall** | — | M5 | M2 | ●● | CONFIRMED (I ran it) |
| F8 | **Node-price INNER join silent drops** (2.15%; 96% is May 1-5 scarcity block, no audit) | M2 | m8 | m4 | ●●● | CONFIRMED (10-day gap reproduced) |
| F9 | **AS share 29% under-determined** (mixed net/gross denom; could be 25-40%+) | (M4 adj) | m6 | (M3) | ●● | plausible; report as range |
| F10 | **Energy+AS JOINT ceiling not delivered** (pre-registered; machinery exists) | — | — | M3 | ● | CONFIRMED missing |
| F11 | **No CIs / distribution figure / uncertainty** (vs Stage-5's own bar) | — | — | M4 | ● | valid |
| F12 | **ECRSMD column possibly dropped** (parser reads only `ECRSSD Awarded`) | M4 (suspected) | — | — | ● | UNVERIFIED (see §3) |
| F13 | **SMNE vs telemetry proxy** (RT energy uses telem, not settled SMNE) | p1 | m9 | (impl.) | ●● | acknowledged; bound it |
| F14 | **Duration 1.64 (notes) vs 1.705 (warehouse)** | m4 | polish | (calls 1.64 solid) | ●● | CONFIRMED mismatch |
| F15 | **Stale cross-section cache vs warehouse** (0.03%, no fingerprint) | m3 | — | — | ● | cosmetic-\$ / process |
| F16 | **Negative-capture AS/solar assets drag median** (energy ceiling meaningless for them) | m2 | — | — | ● | segment |
| F17 | **AS-award sign/meaning unasserted** (linchpin of the whole AS number) | — | m10 | — | ● | add assertion |
| F18 | **Unpaired percentile estimator** (median-vs-CDF discards pairing) | — | — | m3 | ● | minor |
| F19 | **Q3 duration-placement not delivered** (pre-registered) | — | — | m5 | ● | optional exhibit |
| F20 | **DST spring-forward join** | verified CORRECT | — | m2 (suspected) | — | NON-ISSUE (A reproduced Mar-8) |
| F21 | Universe 327 (total) vs 302 (capture) stated inconsistently | m5 | — | — | ● | footnote |
| F22 | SOC-integrity claim false at population (−703..983) — SOC unused | m6 | — | — | ● | correct the claim |
| F23 | Suppressed numpy overflow warning at import | — | polish | — | ● | trace it |

Note on F20: C flagged DST as *suspected*; A *verified it is handled correctly* (Mar-8 HE↔15-min mapping
aligns, unmatched rate normal). A's reproduction wins — **do not spend effort here.**

---

## 2. RESOLVED: does the "information-limited / our-DP-ranks-low" punchline survive a FAIR comparison?

This is the one place the three genuinely disagreed, so I computed it rather than averaged them.

**What I ran** (`--locate`-style, 40-asset random sample, `random_state=0`; sample is representative —
uncorrected sample medians 9.6% DP / 31.8% realized vs the full-fleet cache 9.7% / 34.7%). For each
asset I applied ALL of the fair-comparison corrections the reviewers asked for, together:
- **Gross-vs-gross:** DP numerator = `gross_revenue_from_dispatch` (drop the −c_deg term), same basis as
  the ceiling and realized (fixes F1).
- **Matched post-warm-up window:** numerator, ceiling AND realized all restricted to ts ≥ 2026-02-01
  (drops the Dec+Jan warm-up the DP earns \$0 on; ceiling match/full ratio median = **0.561**, matching
  C's 57.5%) (fixes F2).
- **Traded-day ceiling:** ceiling solved only over the asset's SCED-covered dates (fixes F4).
- Realized reported on **both** the two-settlement basis and the RT-physical basis (telem·RT_LMP), the
  latter sharing the RT-only basis of the ceiling and DP (addresses F5).

**Result (n=40 fair-comparison locate):**

| quantity | as-shipped | FAIR (my recompute) |
|---|---|---|
| DP median energy capture | 9.7% (net, full-window) | **31.9%** (gross, matched, traded-day ceiling) |
| realized median (two-settle) | 34.7% | 39.6% |
| realized median (phys@RT) | — | 43.0% |
| **DP percentile in fleet** | **~14th** | **~30th** |

**The call.** The punchline **SURVIVES qualitatively but not quantitatively as shipped.** The DP sits at
~30th percentile — *below the fleet median* (50th), consistent with "our price-only DP is
information-limited, not optimizer-limited." But the honest number is **~30th percentile, capture ~32%**,
not "14th percentile / 10%." The shipped headline was depressed ~2× by two mechanical confounds
(degradation basis + warm-up window) that have nothing to do with information.

**Who was right:** B was directionally right that the DP roughly doubles toward ~30% — but WRONG that it
reaches "near the median"; at 30th percentile it is still clearly below median, so B's "may NOT survive"
overshot. A and C were right that it *survives below median*, but their magnitudes (A ~33% via basis only;
C 18.6% via ceiling-rescale only) each applied a *subset* of the corrections — A didn't rescale the
window, C didn't convert the numerator to gross. Applying **all** corrections together lands at ~32%
capture / 30th percentile, between B's ceiling and C's floor. The single-sentence honest restatement:

> *"On a like-for-like basis (gross, matched traded window, traded-day ceiling), our price-only DP
> captures ~32% of the per-asset perfect-foresight ceiling vs the fleet's ~40%, ranking ~30th percentile.
> It sits below the median — consistent with an exogenous-information limit — but is not near the bottom;
> the residual gap is what NWP/load/co-located-gen signal would buy."*

**Residual uncertainty (state it):**
- n=40 sample, not the full 302 (sample medians match the fleet, so the ~30th pct is stable, but a full
  re-run is the deliverable).
- N_S=100 here vs Stage-4's 200; finer grids *raise* the DP slightly → 30th pct is if anything a mild
  *lower* bound on the DP's rank.
- The percentile is against the FULL fleet, which includes several zero/negative-capture AS/solar units
  (BATCAVE, GRIZZLY, PAD2, SAH, SOLC in my sample) that the DP "beats" trivially. **Segmented to genuine
  energy-arbitrageurs (F16), the DP would rank somewhat LOWER than 30th** — the info-limit story is
  *stronger*, not weaker, on that cut.
- Realized energy capture still carries the joint-AS confound (F10): operators' energy capture is
  depressed by AS opportunity cost, so a pure-energy ceiling flatters the DP's *relative* rank; the
  energy+AS joint ceiling would move both sides and is the clean denominator.

Net: **the finding holds, the magnitude was over-stated, and the corrected number is both more defensible
and more interesting.** No result was manufactured — the humbling conclusion is intact.

---

## 3. Cheap verifications requested

- **A's M1 (~3% ceiling inflation): CONFIRMED.** `prices_node` has 171 distinct dates, `fact_sced_esr`
  161; the 10 extra dates are exactly A's list (Dec 6,7,25; Mar 3,4,5,7,14,29; Apr 21). Re-solving the
  ceiling over traded-days-only vs full-window: LON_ESR1 +4.02%, JAR_ESR1 +3.91% (A's ADL_RN isn't in the
  eligible set; same direction/magnitude). Systematic, same 10 days for every asset.
- **C1 per-month level shortfall (~20-28%): CONFIRMED.** I ran the pre-registered monthly cap-weighted
  reconstruction vs Modo:

  | month | reconstructed (cap-wt \$/kW-mo) | Modo | ratio |
  |---|---|---|---|
  | 2026-01 | 2.82 | 3.94 | **0.72** (28% low — outside pre-reg ±20%) |
  | 2026-02 | 0.98 | 1.08 | 0.91 |
  | 2026-04 | 2.63 | 3.12 | 0.84 |

  Shape matches almost perfectly (Jan ≫ Apr > Feb); level systematically 9-28% light, worst in Jan. This
  reproduces B's and C's tables independently. The `$1-4` window band cannot fail (Feb 1.08 to Jan 3.94
  nearly span it) and was widened from `$3-6` post-hoc — the "validated to first order" claim rests on it.
- **A's M4 (ECRSMD column): UNVERIFIED.** The DAM parser (`src/disclosure_ingest.py:94`) reads only
  `df["ECRSSD Awarded"]`; the RRS legs by contrast sum three sub-columns (PFR/FFR/UFR), showing the file
  *does* carry granular AS sub-columns. I could not open a raw NP3-966 `60d_DAM_ESR_Data` file this
  session (no cached CSV in `data/raw/`; would need an authenticated re-download). Strong prior that an
  `ECRSMD Awarded` column exists in the ERCOT DAM ESR disclosure (SD = self-deployed/governed, MD =
  manually-dispatched), but batteries overwhelmingly clear ECRS-SD, so the likely miss is small. **Flag as
  unverified — resolve by printing the raw DAM header once and asserting the ECRS award column set.**

---

## 4. Single prioritized action list

Ranked by (correctness severity) × (Base interview leverage). Effort S/M/L. "Framing risk" = does it
threaten the honest null? (All are No — every fix de-confounds; that is the discipline.)

### BUCKET A — MUST-FIX (a wrong number or an overstated claim; keep this list small)

**A1. Restate the locate headline to the fair gross-vs-gross, matched-window, traded-day-ceiling number
(F1+F2+F3+F4 together).** Ships as ~32% capture / ~30th percentile, replacing 10% / 14th.
*Why:* it is the one Stage-7 result that ties back to the entire project thesis, and as shipped it is a
wrong number a desk dismantles in one question ("was your DP switched off during the richest month?").
*Raised by:* A, B, C (the conflict). *Effort:* M (I already have the code; run it full-fleet at N_S=100+,
plus a segmented-to-arbitrageurs cut). *Framing risk:* No — the humbling conclusion survives; it just
becomes defensible.

**A2. Replace the C1 `$1-4` band with the pre-registered monthly ±20% + shape test, and report the
~20% (Jan 28%) level shortfall as a diagnosed finding (F7).** Do NOT keep "validated to first order" on a
4×-wide, post-hoc-widened band.
*Why:* revising an acceptance band after seeing the statistic and then saying "validated" is a
researcher-degree-of-freedom a rigorous reviewer flags immediately; the monthly test is stronger AND
already computable (I ran it in one query). *Raised by:* B, C. *Effort:* S. *Framing risk:* No — it
*exposes* an approximation honestly.

**A3. Stop reporting capture > 1.0; report the RT-physical basis (telem·RT_LMP) as the primary capture
and flag/cap the two-settlement > 1 cases (F5).**
*Why:* a realized capture above a correct ceiling is impossible; PALACIOS 1.21 is a visible defect from
pricing a DA+RT numerator against an RT-only ceiling. The median only moves ~2pp (35→33, A verified), so
this is cheap honesty, not a result change. *Raised by:* A, B. *Effort:* S. *Framing risk:* No.

### BUCKET B — HIGH-VALUE UPGRADES (raise the bar; not "wrong" but materially strengthen the artifact)

**B1. Deliver the pre-registered energy+AS JOINT ceiling and capture (F10).** The Stage-4
reserve-co-optimized oracle already exists; energy-only capture conflates "arbitrage skill" with "chose
to sell AS." *Raised by:* C. *Effort:* M. *Interview leverage: high* (a silently-missing pre-registered
deliverable is what a rigorous reviewer checks first).

**B2. Bootstrap CIs on the fleet capture median and the DP percentile, and publish the capture
DISTRIBUTION figure (ECDF/histogram) + a per-duration capture curve (F11).** *Why:* Stage 5's own
headline was "not separable from zero" with a bootstrap CI; a 302-asset heavy-tailed cross-section with a
bare point median is the same sin Stage 5 corrected. I showed the percentile moves 8+ points under a
defensible window choice → it needs error bars. *Raised by:* C. *Effort:* M. *Leverage: high* (matches
the project's own rigor bar; a distribution figure is the single best visual exhibit Stage 7 can produce).

**B3. Node-price gap audit + per-node row-count assertion; re-fetch the May 1-5 block (F8).** *Why:* 96%
of the silent inner-join drops land on the highest-value scarcity days (May-2 \$2,046; May-5 \$5,474), a
promised mitigation (plan §9) that was never executed. Small measured \$ impact but real tail risk and a
trust defect a data-savvy interviewer finds in five minutes. *Raised by:* A, B, C. *Effort:* S (assert) +
M (re-fetch). *Leverage: high* (turns a silent omission into a loud, fixed one — itself a positive TDD
signal).

**B4. Match the DA/RT/ceiling date windows to a common date set fleet-wide (F4+F6).** Restrict the ceiling
to traded days (removes the ~3-4% systematic inflation on *every* capture) and intersect the DA/RT legs.
*Raised by:* A, B, C. *Effort:* S. *Leverage: medium* (clean consistency a desk audits).

**B5. AS share as a RANGE with a caveat, not "29%, regime confirmed" (F9).** Bracket by the DA-only (25%)
and RT-total (32%) assumptions; note the ~20% C1 shortfall could raise it. Keep the real "AS collapsed in
2025-26" narrative as *argued*. *Raised by:* B (+A/C indirect). *Effort:* S. *Leverage: medium.*

### BUCKET C — OPTIONAL / POLISH (cheap credibility; do in a batch)

- **C1.** Verify the ECRSMD column: print the raw DAM header once, assert the ECRS award set, sum ECRSMD
  into `da_ecrs_mw` if present (F12, A). *Effort S; do it — it's the only unverified suspected-material item.*
- **C2.** Bound the SMNE-vs-telemetry proxy on a sample of assets/days, or state expected sign/size (F13).
- **C3.** Cache fingerprint (row counts + max(ts) per table) so `--phase-b`/`--locate` are provably a
  function of the warehouse (F15). Rebuild the cache after every ingest.
- **C4.** Correct the notes: duration 1.64 → **1.705** (label the population) (F14); true SOC range and
  "diagnostic-only" (F22); state the \$186.5M universe as 327-with-\$0.01M-ineligible-tail vs 302-eligible
  for capture (F21).
- **C5.** Add the AS-award data-dictionary note + a sanity assertion (on a no-DAM-AS day, RT award =
  total assigned AS) (F17). Cheap insurance on a load-bearing assumption.
- **C6.** Lead the locate with the PAIRED (our − realized) distribution, not median-vs-CDF (F18, C).
- **C7.** Deliver the Q3 duration-placement scatter (real capture vs duration on the Stage-4 Q3 curve) —
  an external test of Headline B (F19, C). *Genuinely interesting; optional only for time.*
- **C8.** Segment the cross-section into energy-participating vs AS/solar-only; report energy capture on
  the arbitraging subset (F16). *Note this makes the DP look relatively WORSE — include it anyway.*
- **C9.** Trace the suppressed numpy overflow rather than muting it globally (F23).

---

## 5. Strategic call: is Stage 7 net-positive for the Base application?

**Net-positive — CONDITIONAL on Bucket A (the two must-fixes A1, A2). Do NOT scope it down.**

Reasoning:
- The **reproducible fleet-scale reconstruction + honest external validation** is the single strongest
  artifact in the whole project for this role. "Validating an economic model against observed behaviour
  at fleet scale" is a *named* responsibility (Decision 17). A 302-asset reconstruction from raw 60-day
  disclosure that reproduces to the dollar, with zero join fan-out (recon verified), differentiates this
  candidate from a single-asset toy. That is real and must be led with.
- **As-is it carries avoidable interview RISK on exactly the two comparative claims a desk probes first:**
  the 14th-percentile locate (dismantled in one question) and the "validated" 4×-wide band. Left
  unfixed, these convert the project's best asset into its most attackable surface.
- **With A1+A2 it becomes clearly net-positive:** the corrected ~30th-percentile locate is *more*
  impressive than the confounded 14th because it demonstrates the candidate reflexively controls for
  basis/degradation/warm-up — the core skill the role screens for; and the monthly-C1-with-owned-shortfall
  is a "reconstruction skill + external validation + honest error analysis in one sentence" showcase.
- **Scope-down counter-view (rejected):** Stage 7 is optional and derivative (Modo/Ascend sell it), so a
  minimal case would keep ETL + totals + monthly-C1 + matched-locate and cut the rest. I reject full
  scope-down because the fixes are cheap (I've already run both headline recomputes) and the artifact is
  the project's best hiring signal. But DO cut low-value polishing — do not sink time into AS
  two-settlement refinement beyond localizing the C1 residual (diminishing return on a derivative
  benchmark).

---

## 6. The two closing single-change picks

**Most increases CORRECTNESS/credibility:** the **fair gross-vs-gross, matched-window, traded-day-ceiling
locate re-run (A1).** It fixes the one *wrong headline number* that ties Stage 7 to the entire project
thesis, taking it from an unfairly-low 14th percentile to an honest ~30th — without reversing the
information-limited conclusion. I computed it: ~32% DP capture, ~30th percentile.

**Most increases VALUE to a Base interviewer:** the **monthly C1 shape table with the honestly-owned
~20% level shortfall, localized to a stream (A2).** "Reconstructed monthly fleet revenue tracks Modo's
published *shape* to within ~20%, with a diagnosed systematic level bias I localize to the AS
two-settlement / SMNE proxy" is a single sentence that shows reconstruction skill, external validation,
AND honest error analysis — the named job responsibility, done to a real bar.

**Do they conflict?** No — they are complementary, independent, and both already computed this session.
Do both. If hard-time-boxed, A1 first (it is a *wrong number*, a correctness defect), A2 second (it is a
*credibility showcase*, a strong-but-not-wrong claim). Together they convert Stage 7's two most
attackable claims into its two most defensible ones.

---
*Synthesizer note: no fix in this document manufactures a better-looking number. A1 keeps the DP below
median; A2 exposes a shortfall the band hid; A3 lowers capture ~2pp. The point of every fix is to
de-confound, letting each number land where it honestly lands.*
