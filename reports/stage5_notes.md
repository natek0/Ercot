# Stage 5 — statistical inference: results & method

> **Round-2 update (post three-agent adversarial review + synthesizer).** The Round-1 record below
> stands; a review pass (statistician / quant-hiring / staff-engineer lenses + synthesizer,
> reports `stage5_review_*.md`) returned **no correctness blockers** — every number reproduced
> bit-for-bit — and drove these applied changes:
> - **Magnitude-aware permutation test added** (`stage5_stats.permutation_test`). The sign test is
>   the *least* powerful test against this study's "wins by a few big days" alternative, so its
>   coin-flip p (0.55) *overstates* the ambiguity. The paired sign-flip permutation test gives
>   one-sided **p≈0.074**, two-sided **0.148** — marginal, still not separable at 5%, but not a
>   coin flip. Both are now reported; the sign test remains the distribution-free headline.
> - **ψ_up "$40.96 > $32.75" DEMOTED** from "key result" to directional context: it rests on **3
>   intervals of one day** (2026-03-23; 2nd-worst day $32.45, *below* the clairvoyant max), has no
>   CI, is ρ-dependent. The defensible Q2 headline is the bounded **mean-daily-max CI [$0.68,$2.63]**.
> - **Capture reported apples-to-apples: 34% of the traded ceiling** (comparators are matched) with
>   18% of the full ceiling kept visible; the option-edge ratio (29%) is named separately so the
>   three ratios aren't conflated.
> - **Option value led with the matched $2,020**, not the inflated un-matched $2,667.
> - **Ladder is now fully data-driven** — `build_cache` runs the clairvoyant MPC and stores every
>   full-window profit in the cache; the figure/writeup read them (no hardcoded `MPC_2H`).
> - **Bootstrap vectorised** (~30 s → <0.1 s), enabling n_boot=10000; CIs re-pinned (edge
>   [−$386,$5,115], V^DP level [−$321,$5,782], §V.26 gap [−$644,$1,356] — all still straddle zero).
> - **Tests: 103 green** (added permutation tests, a bootstrap coverage/calibration test, and a
>   `_traded_mask`/`_daily_pnl` leak-contract test). The prose writeup is `reports/stage5_writeup.md`.

**Status: the §VIII.5 inference suite is BUILT, TESTED, and RUN, and the findings-first writeup
(`reports/stage5_writeup.md`) + figures are DONE. Round 1 (below) recorded the raw numbers; Round 2
delivered the paper and applied the review fixes above.**

**Headline (the honest §VIII.5 result, as expected).** On the matched, leak-free, post-warm-up
traded window, **the DP's edge over the strong causal baseline (the learned-forecast MPC) is not
statistically separable from zero.** All three inference angles agree: the sign test is a coin
flip (46%, p=0.55), the bootstrap CI straddles zero at every block length, and the sample is too
thin to resolve an edge below ~54% of the traded ceiling while the observed edge is ~29%. The DP
*does* decisively beat the WEAK baseline (75% of days vs the naive MPC, p<0.001) — so the DP is
doing real work; the thin, tail-concentrated window just cannot certify its margin over a *good*
forecast. A CI that straddles zero is the correct answer here, not a failure (§VIII.5).

Everything below carries a bracket, an interval, and a concentration statistic (the §VIII.5 gate).

---

## What was built

| module | what it is |
|---|---|
| `src/stage5_stats.py` | PURE inference (numpy in, numbers out): sign test, stationary block bootstrap + CI, block-length sensitivity, concentration, leave-one-day-out jackknife, power statement. Seeded → reproducible. Unit-tested against synthetic inputs with known answers (`tests/test_stage5.py`, 17 tests). |
| `src/stage5_run.py` | the SLOW orchestration: runs every leak-free walk-forward backtest once, extracts the aligned per-day P&L series over the matched traded window, caches them (`data/raw/stage5_*`), and formats the full report. `--rebuild` re-runs the backtests. |

Discipline held: every fitted object (DP kernel, seasonal, bin edges, reserve prices, the MPC
forecaster) is re-fit **inside** each walk-forward fold; no future leaks. All comparisons are on
the **matched traded window** — the 140 days *after* the DP's 2-month warm-up — so nothing is
inflated by the DP's warm-up exemption (the Stage 4 review's key fix).

**Reproduce:** `python -m src.stage5_run --rebuild` (heavy, ~8 min: the learned and naive MPCs
solve an LP at each of ~18,900 intervals) then it prints the report; `python -m src.stage5_run`
re-uses the cache and prints instantly. `python -m pytest tests/test_stage5.py` for the logic.

---

## The window and the levels (2h, energy-only, walk-forward)

- Full window: 198 days / 18,885 intervals. **Traded (post 2-month warm-up): 140 days / 13,318
  intervals** — the matched window every comparison uses.
- Perfect-foresight ceiling: **full $13,206 | traded $6,972**.
- **V^DP (empirical kernel) = $2,364 = 34% of the traded ceiling, 18% of the full ceiling.**
  (Matches the Stage 4 review headline exactly — this suite is built on the same leak-free policy.)
- **Matched-window MPC recompute** (the Stage 4 review fix — MPC P&L summed over ONLY the traded
  days, so it no longer absorbs warm-up losses the DP skipped):

  | comparator | full-window (Stage 4) | **matched traded window (Stage 5)** |
  |---|---|---|
  | learned-forecast MPC | −$303 | **+$344** |
  | naive (same-hour-last-week) MPC | −$3,453 | **−$2,806** |
  | naive threshold floor | −$5,267 | **−$3,877** |

  The learned MPC's full-window loss was *concentrated in the warm-up months*; on the traded
  window it is slightly positive. Consequently the **matched option value
  V^DP − V^MPC(learned) = $2,020**, down from the inflated **+$2,667** Stage 4 reported on the
  unmatched window. $2,020 is the honest option-value number.

---

## (1) Sign test — the distribution-free HEADLINE (§VIII.5c)

Daily paired differences $D_i = V^{DP}_i - V^{MPC,learned}_i$ over the 140 traded days:

- **DP beats the learned MPC on 31/68 non-tied days = 46%** (two-sided exact binomial **p = 0.545**;
  72 tied days — on half the days neither policy trades, so $D_i=0$).
- Mean daily edge $14.4; total $2,020.
- **Reading:** 46% is indistinguishable from a coin flip. The DP's positive *total* comes from
  the *magnitude* of a few winning days, **not** from winning more days than it loses. Under this
  market's tail concentration the sign test is the right headline, and it says: no per-day edge
  over a good forecast.
- **Contrast — vs the naive MPC:** DP wins **85/113 = 75%, p < 0.001.** So the DP's
  distribution-awareness beats a *dumb* forecast decisively; it just is not separable from a
  *good* one on this window. This contrast is the real finding, not a flat null.

## (3) Stationary block-bootstrap CI + block-length sensitivity (§VIII.5b)

95% CI on the total paired edge $\sum_i D_i$ (point estimate $2,020), by expected block length:

| block mean (days) | 95% CI on the edge | straddles 0 |
|---|---|---|
| 1 | [−290, 4,895] | yes |
| 2 | [−347, 4,937] | yes |
| 5 | [−390, 5,110] | yes |
| 10 | [−454, 5,126] | yes |
| 20 | [−591, 5,049] | yes |
| 40 | [−482, 4,874] | yes |

**Every block length straddles zero**, and the interval is stable across block lengths (serial
dependence is not the thing hiding the signal — the sample size is). The CI on the **level**
$V^{DP}$ itself is **[−$309, $5,739]**, consistent with the Stage 4 figure [−$263, $5,666].

## (4) Concentration — the value IS spike-driven (§VIII.5d), now SHOWN not asserted

Per-day $V^{DP}$ over the 140 traded days (net total $2,364):

- **Top-1 day = $893 = 38% of the net total** (27% of gross up-day P&L).
- **Top-5 days = $2,705 = 114% of the net total** (83% of gross up-day P&L).

The top 5 days *more than account for the entire net profit* — the other 135 days net −$341
combined. This is the §VIII.5 tail concentration made explicit, and it is exactly why the mean is
untrustworthy and the sign test leads. It is a finding about the market, not an embarrassment.

## (5) Jackknife + power statement (§VIII.5e, §VIII.5f)

- **Leave-one-day-out jackknife** on the paired edge (full $2,020): range **[$1,222, $2,390]**,
  **sign not fragile** — removing any single day leaves the edge positive. (The point estimate is
  robust to no single day; it just isn't *significant*.)
- **Power:** with observed daily sd $D_i$ = **$113/day** over **n = 140** days, this design
  detects (α = 0.05, 80% power, two-sided) a total edge of at least **$3,747 = 54% of the traded
  ceiling**. The observed edge ($2,020 ≈ 29% of the traded ceiling) is **below** this threshold —
  **it is not resolvable with this sample.** This is the single most credibility-enhancing
  sentence in the study: the design is honest about what it can and cannot see.
  - Normal-approx caveat: under the fat tail the true MDE is somewhat *larger*, so 54% is an
    optimistic floor — which only strengthens the "not separable" conclusion.

## (6a) §V.26 — empirical-vs-learned kernel gap, with a CI

Daily $V^{DP}_{empirical} - V^{DP}_{learned}$ at n_bins = 12 (both walk-forward):

- empirical total $2,364 vs learned $2,089; **gap $275**.
- Sign test: empirical wins **30/63 days = 48%, p = 0.801**; 95% CI on the gap **[−$642, $1,382]**,
  straddles zero.
- **Reading:** within noise — consistent with the sign flip at n_bins = 10 the Stage 4 review
  found. "Empirical ≈ learned"; the CRPS win (Stage 3) does **not** translate into a *separable*
  decision-value win. The publishable negative result stands, now with an interval on it.

## (6b) Reserve shadow price ψ_up — CIs (Q2)

ψ_up from the realised **interval MCPC at the executed post-decision SOC** (ρ = 0.05) — the
tail-restoring method (the hour-mean MCPC of the co-optimised DP smooths the tail away):

- Binds (ψ_up > $0.228, the 1%-of-median-price tolerance) in **6.0% of intervals, on 70/140 days**.
- Median over binding intervals **$0.593**; p99 **$1.307**; **max $40.96** — a single-event
  extreme that **exceeds Stage 0's clairvoyant max $32.75, confirming Decision 19** (a causal
  operator caught short in a real spike faces a higher ψ_up than a clairvoyant who positioned SOC
  to dodge it).
- **Bootstrap 95% CI on the mean daily-max ψ_up: [$0.676, $2.649]** — a small but bounded-away
  -from-zero average scarcity cost.
- Concentration: top-1 day = 19%, top-5 = 68% of the summed daily-max → **ψ_up is a scarcity
  -EVENT price**, not a constant accounting term.
- Caveat on the effective sample (§VIII.5a): the 70/140 "binding" days are at the *loose*
  noise-level tolerance; the economically material ψ_up is concentrated in the top handful of days
  (top-5 = 68% of the mass), so the *effective* sample for the tail is closer to §VIII.5a's ~15
  than to 70. The median-exceeds-Stage-0-floor "validation" (Decision 19 in the median) remains
  razor-thin and ρ = 0-dependent; **the tail (max $40.96 > $32.75) is the load-bearing result.**

---

## Honest overall reading (for the Round-2 writeup, pending owner review)

1. **The DP is not statistically separable from a good point-forecast MPC on this window.** Sign
   test 46% (p=0.55), edge CI straddles zero at every block length, observed edge (~29% of
   ceiling) below the ~54% detection floor. This is the §VIII.5 point and must be the headline
   framing — not the $2,364 point estimate.
2. **But the DP is doing real work:** it beats the naive MPC on 75% of days (p<0.001), and its
   value is genuinely spike-concentrated (top-5 days = 114% of net). The story is "distribution
   -awareness beats a dumb forecast decisively and a good forecast un-separably on a thin,
   tail-dominated sample" — an inference-limits story, honestly told.
3. **§V.26 empirical ≈ learned** is confirmed with an interval (gap CI [−642, 1,382]).
4. **Q2 ψ_up** is a bounded, scarcity-concentrated price: mean daily-max CI [$0.68, $2.65], tail
   max $40.96 > Stage 0 (Decision 19 confirmed in the tail).
5. **What would change it (§VIII.5a, all named, all out of Round-1 scope):** more days (esp.
   summer scarcity — needs the ERCOT MCPC archive re-download); the cross-section of settlement
   points and durations; the 60-day disclosure fleet (~300 assets on the *same* scarcity days —
   the strongest answer to the thin-sample problem, Stage 7). None reverse the honest framing;
   they would raise power.

## Tests

`tests/test_stage5.py` — 17 tests pinning the inference logic against synthetic inputs with known
answers (sign-test counts/ties/significance, bootstrap determinism + coverage + zero-straddle,
concentration ratios, jackknife range + sign-fragility, power-statement formula + √n scaling).
**Full suite: 95 passed** (78 prior + 17 Stage 5). CI stays green (the heavy `stage5_run`
backtests are not in CI — they need the cached real panel, like the Stage 4 real-data tests).

## STOP — Round-1 gate

Per the plan's Stage 5 gate and the owner's instruction: the statistics are delivered; the
**prose/findings-first writeup is NOT started.** Await owner review of these numbers and
confirmation of the "not statistically separable from zero" framing before narrativizing.
