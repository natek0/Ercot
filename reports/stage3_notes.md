# Stage 3 — learned conditional price distribution: build notes

**Status: COMPLETE (at the Stage 3 gate), and hardened by a three-agent adversarial
review (see "Review & fixes applied" below).** A calibrated conditional price model that
beats both baselines on held-out CRPS, the hour-indexed transition matrices the Stage 4
DP consumes, and a leak-free measurement of how much a better forecast shrinks the Stage 2
forecast-error cost. Every fitted object is re-fit inside each walk-forward fold; the
fold-intersection and adaptedness assertions pass in code, and real-data causality is now
pinned by a test.

## What Stage 3 exists to do

Stage 2 measured the prize: committing to a same-hour-last-week forecast turned a
~$6,500 arbitrage opportunity into a ~$1,000 loss, and the clairvoyant-MPC proved
**98% of the $16,660 value-of-foresight gap is forecast error** ($16,300), not a broken
controller. Stage 3 attacks that $16,300 with a calibrated probabilistic price model —
and produces the object the Stage 4 Bellman equation structurally cannot run without:
`E[V_{h+1} | x_t]`, i.e. an hour-indexed transition kernel on the tabulated price state.

## What was delivered

| module | what it is |
|---|---|
| `src/features.py` | point-in-time feature builder; recomputes the warehouse `v_features` columns in numpy (verified row-for-row equal) so ONE causal feature path serves both training and the live MPC; gap-safe timestamp lags (price AND residual); strictly-past conditioning set (§VIII.1); per-fold **separable seasonal deseasonaliser `m = shape(qod,weekend) + level(month)`** with a persistence-extrapolated month level |
| `src/price_model.py` | the learned **QuantileGBT** (gradient-boosted trees per quantile, pinball loss, sort-rearranged so quantiles never cross) + two baselines to beat: **EmpiricalCond** (count-based transition matrix as a predictive CDF) and **MeanRevertJump** (AR(1) + 2-component Gaussian-mixture innovation); pinball / **full-range CRPS** / PIT scoring |
| `src/markov.py` | tail-refined (empirical-quantile) residual bins, hour-indexed transition matrices (count-based and model-integrated), row-sum + dual irreducibility checks — the Stage 4 input |
| `src/walkforward.py` | expanding-window fold harness; re-fits every object per fold; `assert_no_fold_leak` (§VIII.3) + `assert_pit_adapted` (§VIII.1 static invariant); pooled CRPS/pinball/PIT + PIT histogram/KS |
| `src/forecast.py` | `LearnedForecaster` behind the existing `.predict(history, horizon)` contract — median conditional path, online monthly refit (walk-forward), seasonal + AR(1)-decay path |
| `src/stage3_run.py` | (A) walk-forward model scoring + PIT + transition-matrix validity + empirical-baseline bin-count steelman; (B) the MPC value-of-foresight ladder with the learned forecast |
| `tests/test_stage3.py` | 18 tests: fold-intersection + adaptedness, scoring-rule properties, sort-rearrangement monotonicity, point-in-time features (base AND residual columns), `build_features == v_features`, forecaster causality (synthetic AND real-data), transition validity, learned-beats-baselines |

New dependency: `scikit-learn==1.7.2` (prebuilt wheel, needs only numpy/scipy — no
OpenMP/compilation, CI stays a plain `pip install`).

## Headline A — model quality (walk-forward, 5 folds, ~13,060 held-out intervals)

Held-out, expanding-window (train months 1..m, evaluate month m+1). **Lower is better.**

| model | CRPS | pinball | PIT-KS | reading |
|---|---|---|---|---|
| **learned_gbt** | **2.718** | **0.835** | **0.024** | **wins — provisionally adopted (§V.26)** |
| jump (parametric) | 2.928 | 1.138 | 0.051 | the AR(1)+jump baseline |
| empirical (count matrix) | 5.253 | 1.691 | 0.052 | the nonparametric baseline |

The learned model **wins on held-out CRPS against BOTH baselines** (and on 4 of 5 folds;
the parametric jump wins only fold 0, the thinnest-trained). CRPS is integrated over the
full [0,1] range (see the review section — a truncated grid would under-penalise the tail).
**Steelman:** the empirical baseline was swept over bin counts {8,12,16,24}; its best is
4.703 at 16 bins, and the learned model (2.718) still beats it comfortably, so the ranking
is not an artifact of the baseline's binning.

**§V.26 adoption is a TWO-pronged gate** — a held-out CRPS win *and* a better realised
capture rate. Only the CRPS prong is settled here; the capture-rate prong needs a policy
run on the transition kernel and is **evaluated in Stage 4**. So the learned model is
**provisionally adopted on CRPS**, not finally adopted. Honesty note: the GBT wins with
strictly richer conditioning (all 15 features) than the baselines (`EmpiricalCond` sees
hour + previous-residual bin; `MeanRevertJump` sees the previous residual) — that is the
intended best-in-class comparison per §V.24, but the win partly reflects the richer
conditioning a flexible model is built to exploit.

**Calibration (the Stage 3 gate) — characterised, and its two components separated.** The
learned PIT is close to uniform (KS 0.024) but its extreme bins are elevated
(`[0.0,0.1)`=1576, `[0.9,1.0)`=1621 vs a flat ~1306 — **+22% end-bin excess**). The
adversarial review resolved *what* this is:

- It is **NOT** a finite-grid clamping artifact. (An earlier draft of these notes claimed
  it partly was; a reviewer disproved that by simulation — at 10 histogram bins whose edges
  coincide with the 0.1/0.9 quantile knots, clamping piles mass at exactly 0/1 but never
  moves it across a bin boundary, so a calibrated model shows no elevation. Caveat deleted.)
- Part of the *asymmetry* was a **seasonal level bias**: the original deseasonaliser dropped
  the `month` term §V.26 specifies, so the "residual" drifted up over the warming Dec→Jun
  window (per-fold mean-PIT ran 0.455→0.518). **Fixed** by adding a persistence-extrapolated
  month level; the tails are now symmetric (1576 vs 1621, was 1705 vs 1525) and KS fell
  0.031→0.024.
- What **remains** after the fix is a **genuine mild under-dispersion** (~+22% end-bin
  excess): the predictive intervals are a touch too tight, so outcomes land in the tails
  slightly more often than stated.

**Direction on the Stage 4 policy** (what the gate requires when the PIT is not flat): a
mildly under-dispersed forecast makes the DP UNDER-value the tail → hold *less* charge for
spikes than optimal → the policy degenerates *toward* MPC (under-hoards), and the transition
kernel built from a too-thin tail understates spike-bin mass. It biases toward caution, not
reckless hoarding. **Remaining mitigation (a Stage 4 action):** the extreme tail levels
(0.005/0.995) are now included, but a light tail/variance inflation + a non-clamping PIT
re-check should precede *freezing* the kernel, so any below-optimal Stage 4 capture rate is
attributable to this known, bounded bias. Gate status: **MET** (deviation characterised into
its two components, both the applied fix and the residual direction stated).

**Transition matrices (Stage 4 input).** Hour-indexed (24 matrices), tail-refined
empirical-quantile bins on the deseasonalised residual, built count-based and
model-integrated. Every row sums to one (err ~1e-16). Irreducibility is now reported as two
things: the **matrix** the DP consumes is irreducible (guaranteed by a small 0.01 count
prior); the **raw observed process** is NOT irreducible on the full window
(`counts_irreducible=False`) — some hour/bin cells are never observed, so the prior is
load-bearing on thin hours. Stage 4 should read thin-hour transitions with that in mind.

## Headline B — dollar value: shrinking the forecast-error gap (full window, 198 days, 2 h, energy-only)

Swap the learned forecast into the SAME certainty-equivalent MPC and re-run Stage 2's
ladder. Measured leak-free: the forecaster refits online by month (walk-forward), so every
prediction is out-of-sample (a reviewer independently verified real-data causality — a
scrambled future leaves the forecast byte-identical).

| policy | profit $ | reading |
|---|---|---|
| ceiling (clairvoyant LP) | **13,206** | theoretical max |
| MPC, perfect forecast | 12,847 | 97% of ceiling — causal execution is near-lossless |
| **MPC, LEARNED forecast** | **−303** | the Stage 3 causal operator |
| MPC, same-hour-last-week (Stage 2) | −3,453 | the Stage 2 causal operator |
| naive threshold floor | −5,267 | the dumb baseline |

- forecast-error cost, **naive** (clair − naive) = **$16,300**
- forecast-error cost, **learned** (clair − learned) = **$13,150**
- **>>> the learned forecast recovers $3,150 — 19% of the forecast-error gap — lifting MPC
  profit from −$3,453 to −$303.**

**What this is and is not.** $3,150 is the value of a *better conditional mean*: a robust,
month/weekend/hour-aware seasonal profile plus a reactive residual, instead of a single
noisy same-slot-last-week draw that propagates one-off spikes. Three honest bounds a
reviewer pressed on:
- **Conservative:** the learned forecaster falls back to seasonal-naive for the 2-month
  warm-up, so it and the naive MPC differ only over months 3–6.
- **Broadly based, not a spike artifact:** across days the learned MPC beats the naive on
  85 days vs 23; the top-5 days are only 27% of the net gain; its single *worst* day is the
  Mar-23 $950 spike (the median under-reacts to a spike — exactly the under-dispersion
  story). Formal uncertainty quantification (bootstrap / sign test) is Stage 5.
- **Low season, and reactive:** the window MISSES ERCOT's summer scarcity (Jul–Sep), where
  BESS earns; the residual is highly persistent (AR φ≈0.96) so the median *rides* an ongoing
  spike but cannot *anticipate* one. A certainty-equivalent median controller is expected to
  hover near break-even here; −$303 is not a bug, but it is not evidence of profit either.
  The summer top-up (Decision B2) is a *gating* input for any economic claim, not cosmetic.
- **Not the whole prize by design:** the CE MPC consumes only the learned MEDIAN. The
  remaining ~$13,150 is what a *distribution-aware* policy competes for — the Stage 4 DP that
  holds charge against the calibrated right tail. Stage 3 built and validated that tail (the
  transition matrices); Stage 4 spends it.

## The discipline (why these numbers are believable)

- **No fold leakage (§VIII.3).** Seasonal mean, bin edges, quantile models, jump parameters
  and transition matrices are ALL re-fit on the train slice inside each fold.
  `assert_no_fold_leak` checks train/eval indices are disjoint AND every train timestamp
  precedes every eval timestamp; a test fires it on a deliberately-overlapping fold.
- **Adaptedness / publication timestamp (§VIII.1).** The conditioning feature set is
  strictly-past by construction (`features.CONDITIONING` excludes the interval's own
  not-yet-cleared price, its z-score and its scarcity flag). `assert_pit_adapted` is a
  *static invariant* on that constant (honestly documented as such — it is not a per-row
  data guard). The real data-level guarantees are the tests: `test_features_are_point_in_time`
  and `test_residual_conditioning_features_are_point_in_time` reconstruct every conditioning
  column (base AND residual) from a truncated prefix, and `test_learned_forecaster_is_causal`
  / `..._on_real_data` perturb the future and assert the forecast is invariant.
- **One feature path, verified.** `build_features` reproduces the warehouse `v_features`
  columns exactly (a real-data test asserts row-for-row equality including NaN placement in
  the DST/outage gaps), so the model trains on the same features the live MPC computes from a
  bare price array — no train/inference skew.

## Review & fixes applied (three-agent adversarial review)

Stage 3 was reviewed by three independent adversarial agents — a mathematician/programmer
(formal correctness), a quantitative trader (economic validity), and a model-risk validator
(causality/reproducibility) — plus a synthesizer. All three returned **Yes-with-fixes, no
blockers**; the model-risk agent reproduced every headline number bit-for-bit and could not
break causality on real data. Fixes applied in response:

- **Deseasonaliser now includes a month level** (§V.26), *persistence-extrapolated* rather
  than a `groupby(month)` — the synthesizer showed the naive grouping would be *worse* under
  expanding folds (the eval month is never trained, so every cell would fall back to the
  global median). Strict improvement: CRPS 2.708→2.718 (with the CRPS fix below), PIT-KS
  0.031→0.024, per-fold mean-PIT drift compressed.
- **CRPS integrates the full [0,1]** (pads α=0/α=1 with the extreme quantiles) instead of
  truncating at [0.01,0.99], which under-penalised the heavy tails; **extreme tail levels
  0.005/0.995 added**.
- **Adoption softened** to "provisional on the CRPS prong" (the §V.26 capture-rate prong is
  Stage 4); **calibration narrative corrected** (deleted the false grid-artifact caveat;
  separated the level-bias and genuine-under-dispersion components); **empirical baseline
  steelmanned** across bin counts.
- **Gap-safe residual lags** (built from the timestamp-joined price lag) so cross-gap pairs
  no longer contaminate the transition counts; **`rearrange` → sort** (the operator the cited
  no-worse-pinball theorem actually covers); **transition smoothing 1.0→0.01** with a **dual
  irreducibility report** (matrix vs raw counts); **`assert_pit_adapted` documented honestly**
  as a static invariant with the real guarantees moved into tests; **new real-data causality
  test** and **residual-column point-in-time test**.

**Deferred (by design):** the capture-rate prong + tail inflation + non-clamping PIT re-check
→ Stage 4 (they need the DP); bootstrap/sign-test uncertainty on $3,150 → Stage 5; exogenous
NWP features (§V.23, never ingested) → whenever the warehouse gains them.

## Honest scope / deferrals

- **Exogenous NWP features are absent.** The plan's f_t (§V.23) names load / wind / solar
  forecasts and their vintages; Stage 1 ingested only the two price series, so the feature
  set is calendar + price lags + rolling stats + residual signal. Named deferral, not a
  silent omission — and it makes the CRPS win a floor: real NWP conditioning can only help.
- **The MPC consumes only the median.** Headline B understates the model's value; the
  distribution's tail — the actual prize — is realised by the Stage 4 DP, not a point-forecast
  controller. This is the through-line into Stage 4.

## How to run

```
python -m src.stage3_run          # demo window: model scoring only (fast)
python -m src.stage3_run --full   # full window: scoring + steelman + the MPC ladder (~15 min)
python -m pytest                  # 66 tests (48 prior + 18 Stage 3)
```
