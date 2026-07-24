# Stage 7 review — research-methodologist & portfolio lens

Reviewer lens: cross-sectional method, comparison fairness, and whether Stage 7 RAISES or RISKS the
Base Markets candidacy. I read the record, the pre-registration, all four Stage-7 source modules, the
tests, and the DP/backtest internals; I re-ran the tests and Phase B, inspected both cached parquets,
and did three independent recomputations against `data/warehouse_fleet.duckdb` (matched-window
locate, monthly C1 shape, coverage/commissioning). Numbers below are reproduced unless labelled
"suspected."

**Bottom line.** The reconstruction pipeline is solid and honestly framed; the two-settlement joins
are correct and unit-tested; the fleet totals reproduce. But the two *comparative* headlines — "our
DP ranks 14th percentile → information-limited" and "C1 validated to first order" — are each weaker
than presented. The locate-our-policy comparison is unfair in **two same-direction ways** that
together understate our DP by roughly 2×, and the C1 gate as executed is far weaker than what was
pre-registered while the one rigorous pre-registered check (monthly shape) — which I ran and which
*passes on shape but reveals a systematic ~20-28% level shortfall* — was skipped. Neither reverses
the honest qualitative story, but both need restating to survive a battery-desk quant's scrutiny.

---

## MAJOR findings

### M1. Locate-our-policy is unfair in two same-direction ways; the headline "10% vs 35% / 14th percentile" overstates the DP's deficit by ~2×
- **What.** Our-DP capture is computed as `run_backtest(...).profit / row.ceiling_gross`
  (`src/stage7_run.py:300`). Two mismatches, both depressing our number:
  (i) **Warm-up denominator mismatch.** `WalkForwardDPPolicy.decide` returns
  `CommittedDispatch(0.0, 0.0)` for the first `min_train_months=2` (`src/policies.py:285-286`), i.e.
  it earns **$0 across Dec + Jan**, but `ceiling_gross` is the **full-window** ceiling and
  `realized_capture` is the operators' **full-window** revenue over the same denominator. (ii)
  **Net-vs-gross numerator mismatch.** `run_backtest`'s `profit` subtracts degradation
  (`e_step = prices[t]*(dt_-ct)*dt - c_deg*(ct+dt_)*dt`, `src/backtest.py:64`, c_deg=25), so the
  our-DP numerator is **net of degradation**, while `realized_energy_rev` and `ceiling_gross` are
  both **gross**.
- **Where.** `src/stage7_run.py:293-300`; `src/policies.py:285-286`; `src/backtest.py:64,90-91`.
- **Why it's wrong (reasoning, quantified).** The window's value is heavily front-loaded: Dec+Jan
  hold **39% of total daily price spread** and January alone is the richest month by far (mean LMP
  \$48, p99 \$443, 31,849 intervals >\$200, avg daily spread \$185 vs \$74-104 elsewhere — verified
  from `prices_node`). So the DP is switched off for the single most valuable period while the ceiling
  and operators bank it. I recomputed a **matched Feb-1→May-24 window** on a 30-asset sample (oracle
  ceiling re-solved on Feb-May node prices; realized re-summed over Feb-May; our-DP numerator carried
  over since warm-up earns ≈$0): the Feb-May ceiling is **57.5%** of the full ceiling, so matching the
  window **nearly doubles our-DP capture: median 10.6% → 18.6%**, while realized moves only 35.3% →
  38.6%. On top of that, the clairvoyant's degradation drag is `ceiling_net/ceiling_gross` median
  **0.66**, so a gross-consistent our-DP numerator would be materially higher again (upper bound
  +51%; less for the DP since it cycles less than the clairvoyant). Net: the fair our-DP capture is
  ~18-22%, not 10%, and the honest rank is ~**20-25th** percentile, not 14th.
- **Fix + why correct.** Compute the locate comparison on a **matched traded window** (drop the
  warm-up months from BOTH numerator and denominator, for our-DP, the ceiling, AND the operators'
  realized), and use a **gross** our-DP numerator (`gross_revenue_from_dispatch` on the backtest's
  c/d arrays, which already exists at `src/stage7_run.py:52`) so all three quantities are gross.
  This removes both mechanical biases without touching the honest residual. Reasoning: capture is a
  ratio; a ratio is only interpretable when numerator and denominator cover the same intervals and the
  same revenue convention — the current code violates both. The fix is de-confounding, not
  result-manufacturing: the DP still lands below the fleet median, so the "information-limited"
  conclusion survives — but now on a number a reviewer can't dismantle in one question.
- **Severity: major.** **Confidence: verified** (matched-window recomputation reproduced;
  warm-up and net-profit code paths read directly). **Resume-value: raises-bar** (the punchline that
  ties Stage 7 to the whole project thesis currently rests on an unfair 2× haircut).

### M2. C1 as executed is a much weaker test than pre-registered, the reference band was revised post-hoc, and the rigorous monthly check was skipped — I ran it: shape passes, level is systematically ~20-28% low
- **What.** The plan §8 pre-registered gate is "monthly fleet-average within **~20%** and the **same
  month-to-month shape**." What shipped is a **window-mean $1.74 inside a $1-4 band**
  (`src/stage7_run.py:233,267-273`), and that band was **revised from $3-6 to $1-4 after seeing the
  result** (`stage7_notes.md §5`). A ±$1-to-$4 band is a 4× interval that almost any plausible number
  clears; it is not the pre-registered ±20% test, and the monthly-shape prong was deferred as "the
  refinement" even though the monthly Modo figures are already hardcoded
  (`C1_MODO_MONTHLY`, `src/stage7_run.py:234`).
- **Where.** `src/stage7_run.py:227-234,267-273`; `stage7_notes.md §5`; plan §8.
- **Why it's weak (reasoning).** Revising the acceptance band after observing the statistic is a
  researcher-degree-of-freedom; even if the 2025-26 correction is legitimate, "validated" then means
  "cleared a band I widened after looking." More importantly, the wide band **hides** structure. I ran
  the pre-registered monthly comparison (capacity-weighted $/kW-month, eligible assets, per-month
  day-count normalization) against Modo's three settled months:

  | month | reconstructed (cap-wt) | Modo | ratio |
  |---|---|---|---|
  | Jan-26 | 2.85 | 3.94 | 0.72 |
  | Feb-26 | 0.98 | 1.08 | 0.91 |
  | Apr-26 | 2.63 | 3.12 | 0.84 |

  The **shape matches almost perfectly** (Jan ≫ Apr > … > Feb, low month correct) — a genuinely
  strong external validation — but the **level is systematically low in all three months (~16-28%)**,
  with the miss largest in Jan (28%, i.e. *fails* the pre-registered ±20% there). A uniform low bias
  across an energy-led month (Jan) and a low month (Feb) argues the shortfall is **not** purely the AS
  approximation (self-critique #1) — it also implicates the telemetry-vs-SMNE energy proxy (#4) or the
  equal/cap-weighting. This is exactly the localization the pre-registered test is *for*.
- **Fix + why correct.** Replace the window-band check with the **pre-registered monthly shape +
  ±20% test** (the table above), report the ~20% systematic shortfall as a **known, diagnosed level
  bias**, and lock the Modo reference from a dated source *before* the comparison (cite the specific
  Modo monthly figures with retrieval dates). Reasoning: the whole stated value of Stage 7 is "open
  and externally checkable"; the monthly shape check is the strongest such check available, it is
  already computable from data in hand (I did it in one query), and reporting "shape validated,
  level ~20% low, residual localizes to AS/energy-proxy" is far more credible than "inside a $1-4
  band." This does not hide an approximation — it exposes and bounds one.
- **Severity: major.** **Confidence: verified** (monthly table reproduced from the warehouse).
  **Resume-value: raises-bar** (converts a soft sanity band into a real, quantified validation with a
  named residual — the single most portfolio-defining upgrade available).

### M3. The energy+AS (reserve-co-optimized) ceiling and capture cross-section were pre-registered but not delivered; "capture" is energy-only against joint-strategy operators
- **What.** Plan §6/§7 pre-register the ceiling "energy-only **and energy+AS** (the
  reserve-co-optimised oracle from Stage 4)" and "publish the distribution of κ_i … energy-only **and
  energy+AS**." Only the **energy-only** ceiling ships: `asset_energy_ceiling` calls
  `solve(prices, {}, maxsoc, params, ENERGY_ONLY)` (`src/stage7_run.py:64-66`); no CONTINGENCY/joint
  solve exists in the module (verified by grep).
- **Where.** `src/stage7_run.py:58-67`; pre-registration §6, §7.
- **Why it matters (reasoning).** The realized "energy capture" median 35% is an operator's energy
  revenue, but that revenue is a **by-product of a joint energy+AS strategy** — an operator holding
  SOC to back reserve commitments *cannot* arbitrage that energy, so its energy-only capture is
  mechanically depressed by AS opportunity cost, not by arbitrage skill. Comparing it to a pure-energy
  ceiling therefore conflates "skill" with "chose to sell AS instead." Since AS is 29% of fleet
  revenue, this is first-order. The pre-registered energy+AS ceiling would give the clean total-value
  capture and is the correct denominator for a fleet that co-optimizes.
- **Fix + why correct.** Deliver the pre-registered **energy+AS capture** using the Stage-4
  reserve-co-optimized oracle (already built) on total realized revenue, and report both alongside the
  energy-only cut. Reasoning: it is a promised deliverable, the machinery exists, and it removes a
  first-order confound in the flagship statistic. If it is deliberately descoped, that descope must be
  declared in the notes (the current notes present energy-only capture as *the* capture without noting
  the joint ceiling was dropped).
- **Severity: major.** **Confidence: verified.** **Resume-value: raises-bar** (a pre-registered
  deliverable silently missing is exactly what a rigorous reviewer checks first).

### M4. No uncertainty on any Stage-7 statistic — inconsistent with the project's own Stage-5 standard
- **What.** Capture median 35%, our-DP 14th percentile, C1 mean $1.74 are all reported as bare point
  estimates. No bootstrap CI, no distribution plot, no per-duration/per-node breakdown.
- **Where.** `_print_cross_section`, `_print_fleet`, `locate_our_policy` (`src/stage7_run.py:207-273,
  314-333`).
- **Why it's wrong (reasoning).** Stage 5's *entire headline* was "the edge is not statistically
  separable from zero on a thin, tail-concentrated window," reported with a bootstrap CI straddling
  zero. Stage 7 is a **cross-section of 302** where the value is again heavy-tailed and
  concentration-driven; reporting a single median with no dispersion is the same sin Stage 5
  corrected. The 14th-percentile punchline in particular is a function of one median vs one empirical
  CDF (`pct = (realized < our_median).mean()`, `src/stage7_run.py:325`) with zero error bars, and I've
  shown (M1) it moves 8 points under a defensible window choice — it is not a stable point.
- **Fix + why correct.** Bootstrap the fleet capture median and the our-DP percentile over assets
  (and, given concentration, a value-weighted variant), and publish the capture **distribution** (a
  histogram/ECDF), a **per-duration** capture curve, and a note on whether the median is stable to
  c_deg∈[0,60] and N_S∈{100,200}. Reasoning: cross-sectional medians on heavy-tailed panels are
  unstable; the project has already committed to reporting that instability elsewhere, so consistency
  demands it here. A distribution plot also pre-empts the "is the median hiding bimodality?" question
  (I checked: skew 0.12, 7% negative, 9% >0.6 — not strongly bimodal, so the median is defensible, but
  that should be *shown*, not asserted).
- **Severity: major.** **Confidence: verified** (distribution shape computed; percentile instability
  demonstrated in M1). **Resume-value: raises-bar** (matches the study's own rigor bar; a quant
  reviewer will expect CIs on a 302-asset cross-section).

---

## MINOR findings

### m1. Commissioning/coverage bias is present but uncharacterized
- **What/where.** 9 eligible assets are first-seen after Jan-31 and 4 after Mar-1 (verified from
  `fact_sced_esr`); they receive a **full-window** ceiling (`prices_node` for their node over all
  intervals, `src/stage7_run.py:190-192`) but only **partial-window** realized revenue → understated
  capture. The excluded/never-settled population (the 25 dropped + any registered-but-never-awarded)
  is not described.
- **Why/fix.** Reasoning: a capture ratio with a full-window denominator and a part-window numerator
  is biased low; 9/302 (~3%) is modest but it drags the low tail and our-DP too. Fix: restrict each
  asset's ceiling to its own active interval span, or flag/exclude partial-coverage assets, and add one
  paragraph characterizing the excluded set so the distribution is explicitly "conditional on an
  active, near-full-window operator." **Severity: minor. Confidence: verified. Resume-value: neutral.**

### m2. DST hour-ending join edge case (spring-forward, Mar 8 2026)
- **What/where.** The two-settlement join maps `d.hour_ending = extract(hour FROM s.ts_15min) + 1`
  (`src/stage7_run.py:87-88`, `133-138`). ERCOT DAM "Hour Ending" is Central Prevailing Time with
  special 23/25-hour DST days; the window contains the Mar-8 spring-forward (a 23-hour day).
- **Why/fix.** Reasoning: on that one day the DAM hour numbering and a naive `extract(hour)+1` can
  misalign, mis-pricing one day's RT deviation. Impact is ~1/161 of the RT-deviation term only —
  negligible on totals but a correctness gap. Fix: verify SCED and DAM timestamps share a timezone and
  add a DST-aware hour map (or assert row counts of 23/25 on the transition days). **Severity: minor.
  Confidence: suspected** (not reproduced; flagged from the join logic + calendar). **Resume-value:
  cosmetic** unless it surfaces a broader TZ misalignment.

### m3. The percentile estimator is unusual and unpaired
- **What/where.** `pct = (realized_capture < our_dp_capture.median()).mean()`
  (`src/stage7_run.py:325`) ranks *our median* against the realized CDF, discarding the natural
  pairing (each asset has both numbers on the same node). The paired win-rate (`wins`=13%,
  `:324`) is the cleaner statistic.
- **Why/fix.** Reasoning: a paired comparison controls for node/duration heterogeneity that the
  unpaired median-vs-CDF does not; and neither carries a CI (see M4). Fix: lead with the **paired**
  distribution of (our − realized) capture and bootstrap it. **Severity: minor. Confidence: verified.
  Resume-value: neutral.**

### m4. AS RT MCPC uses an INNER JOIN; node-price join gap understates RT terms
- **What/where.** `JOIN prices_mcpc_rt mc ON mc.ts_15min = s.ts_15min` (`src/stage7_run.py:133`) and
  `JOIN prices_node p …` (`:84`) are inner joins: SCED intervals with no matching price/MCPC row are
  silently dropped from the RT deviation/AS sums. Self-critique #8 notes the node gap; the MCPC gap is
  not noted.
- **Why/fix.** Reasoning: dropped intervals understate RT energy and RT AS (small terms — RT AS incr
  is only $6.9M — but the direction is systematic and adds to the ~20% C1 shortfall). Fix: report the
  join coverage fraction per asset and treat missing-price intervals explicitly (e.g. LEFT JOIN +
  coverage flag) rather than silently. **Severity: minor. Confidence: verified. Resume-value:
  neutral.**

### m5. Q3 duration-curve placement (plan §7) not delivered
- **What/where.** Plan §7 pre-registers "place each real asset on our Stage-4 Q3 duration curve"; no
  such output appears in the notes or `stage7_run`. **Fix:** either deliver the scatter of realized
  capture vs duration against the Stage-4 Q3 curve (cheap, and genuinely interesting — it externally
  tests the duration-value finding) or declare the descope. **Severity: minor. Confidence: verified.
  Resume-value: raises-bar** (an external test of Q3, the project's Headline B).

---

## POLISH
- `C1_MODO_BAND` is a hardcoded 4×-wide constant while `C1_MODO_MONTHLY` sits unused in the gate
  (`src/stage7_run.py:233-234`) — wire the monthly dict into the check (M2). **cosmetic.**
- Test file emits pandas/numpy deprecation warnings (`Timedelta(minutes=int(...))`,
  `groupby.apply` on grouping cols) — harmless now, will break on a future pandas. **cosmetic.**

---

## What is genuinely solid (stated plainly)
- **Stream-and-discard ETL** is real, resume-safe (manifest + `is_done`), and the pure/IO split is
  clean and tested. The `append`-by-column-**name** regression test (`test_stage7.py:97`) shows good
  engineering instincts.
- **Both two-settlement SQL joins are correct** and unit-tested on hand-computed examples
  (`test_realized_energy_two_settlement_sql`, `test_as_revenue_two_settlement_sql`) — I reproduced the
  fleet totals ($132.4M energy, $54.2M AS, $186.5M total) and the 14 tests pass.
- **Duration median 1.64h vs ERCOT's 1.65h** is a real independent validation of the physical-param
  extraction.
- **The honest framing is correct and must be kept**: "reproduces commercial work" is the
  pre-registered stance, the low DP rank is a real finding, and the AS-share/energy-led story is
  labelled "argued, not proven." Do **not** let any fix above turn into result-polishing — every fix I
  propose *de-confounds* (M1), *strengthens the test* (M2), *delivers a promised cut* (M3), or *adds
  honesty* (M4). The qualitative conclusions survive all of them.

---

## Resume / interview-value assessment (Base Markets lens)

**Net call: Stage 7 RAISES the candidacy — but only if M1 and M2 are fixed; as-is it carries an
avoidable risk.** Reasoning per point:

1. **Fleet-scale + externally-checkable is the strongest signal in the whole project.** "Validating
   an economic model against observed behaviour at fleet scale" is a *named* role responsibility
   (Decision 17). A 302-asset reconstruction from raw 60-day disclosure, cross-checked against Modo,
   is exactly the artifact that differentiates this candidate from someone with a single-asset toy.
   **Signal: strong-positive.**
2. **The honest-null positioning is an asset, not a liability — if framed as de-confounded.** A
   battery-desk quant respects "my price-only DP ranks ~20th percentile; the residual is exogenous
   information (NWP/load/co-located gen)" *far* more than an inflated capture. But it must be the
   **fair** ~20th percentile (M1), not the unfair 14th, or the first question in the interview
   ("did you match the windows?") sinks it. **Signal: positive *conditional on M1*; risk if left
   as-is.**
3. **The single framing/addition that makes Stage 7 clearly net-positive: the monthly C1 shape table
   (M2).** "Reconstructed monthly fleet revenue tracks Modo's published shape to within ~20%, with a
   diagnosed systematic level bias I localize to the AS two-settlement / SMNE proxy" is a *money*
   sentence — it demonstrates reconstruction skill, external validation, AND honest error analysis in
   one line. It is already computable (I computed it). This is the highest-leverage upgrade.
4. **Scope-down case (honest counter-view):** Stage 7 is optional (Stages 0-5 are the ship bar) and it
   is derivative by construction (Modo/Ascend sell it). If time is short, the *minimal* net-positive
   version is: keep the ETL + fleet totals + the **monthly C1 shape table** + the **matched-window
   locate**; **cut** the effort on prettifying the energy-only capture median and instead spend it on
   the energy+AS capture (M3). Do **not** invest in the AS two-settlement refinement beyond localizing
   the C1 residual — it is a rabbit hole with diminishing portfolio return. The reproducibility and
   the honest external check are the signal; more decimal places on a derivative benchmark are not.

**Single highest-value fix:** the **matched-window + gross-consistent locate-our-policy comparison
(M1)** — it de-confounds the one Stage-7 result that ties back to the entire project's thesis, turning
a number a reviewer can dismantle in one question ("your DP was switched off during the richest
month") into a defensible ~20th-percentile finding. Runner-up and cheapest big win: the monthly C1
shape table (M2).
