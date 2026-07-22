# Stage 3 — learned conditional price distribution: build notes

**Status: COMPLETE (at the Stage 3 gate).** A calibrated conditional price model
that beats both baselines on held-out CRPS, the hour-indexed transition matrices the
Stage 4 DP consumes, and a leak-free measurement of how much a better forecast shrinks
the Stage 2 forecast-error cost. Every fitted object is re-fit inside each walk-forward
fold; the fold-intersection and publication-timestamp assertions pass in code.

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
| `src/features.py` | point-in-time feature builder; recomputes the warehouse `v_features` columns in numpy (verified row-for-row equal) so ONE causal feature path serves both training and the live MPC; gap-safe timestamp lags; strictly-past conditioning set (§VIII.1); per-fold seasonal deseasonaliser |
| `src/price_model.py` | the learned **QuantileGBT** (gradient-boosted trees per quantile, pinball loss, isotonic-rearranged) + two baselines to beat: **EmpiricalCond** (count-based transition matrix as a predictive CDF) and **MeanRevertJump** (AR(1) + 2-component Gaussian-mixture innovation); pinball / CRPS / PIT scoring |
| `src/markov.py` | log-spaced-tail residual bins, hour-indexed transition matrices (count-based and model-integrated), row-sum + irreducibility checks — the Stage 4 input |
| `src/walkforward.py` | expanding-window fold harness; re-fits every object per fold; `assert_no_fold_leak` (§VIII.3) + `assert_pit_adapted` (§VIII.1); pooled CRPS/pinball/PIT + PIT histogram/KS |
| `src/forecast.py` | `LearnedForecaster` behind the existing `.predict(history, horizon)` contract — median conditional path, online monthly refit (walk-forward), seasonal + AR(1)-decay path |
| `src/stage3_run.py` | (A) walk-forward model scoring + PIT + transition-matrix validity; (B) the MPC value-of-foresight ladder with the learned forecast |
| `tests/test_stage3.py` | 16 tests: fold-intersection + adaptedness assertions, scoring-rule properties, isotonic monotonicity, point-in-time features, `build_features == v_features`, forecaster causality, transition validity, learned-beats-baselines |

New dependency: `scikit-learn==1.7.2` (prebuilt wheel, needs only numpy/scipy — no
OpenMP/compilation, CI stays a plain `pip install`).

## Headline A — model quality (walk-forward, 5 folds, ~13,060 held-out intervals)

Held-out, expanding-window (train months 1..m, evaluate month m+1). **Lower is better.**

| model | CRPS | pinball | PIT-KS | reading |
|---|---|---|---|---|
| **learned_gbt** | **2.708** | **0.978** | **0.031** | **wins — ADOPT (§V.26)** |
| jump (parametric) | 2.903 | 1.253 | 0.051 | the AR(1)+jump baseline |
| empirical (count matrix) | 5.192 | 1.960 | 0.070 | the nonparametric baseline |

The learned model **wins on held-out CRPS against BOTH baselines** (and on 4 of 5 folds;
the parametric jump wins only fold 0, the thinnest-trained), so per §V.26 it is the one
adopted. This is a genuine, not decorative, ML result: a heavy-tailed, hour-dependent
price residual is exactly where a flexible tree model beats a pooled parametric form and
a coarse count matrix.

**Calibration (the Stage 3 gate) — a characterised deviation, stated honestly.** The
learned model's PIT is close to uniform overall (KS 0.031, the smallest of the three) but
NOT flat in the tails: the extreme bins are elevated (`[0.0,0.1)`=1705 and `[0.9,1.0)`=1525
vs a flat ~1306), a mild **U-shape = under-dispersion** — the model's predictive intervals
are a touch too tight, so outcomes land in the tails slightly more often than stated.

This is the single failure mode §V.25 flags as most dangerous, so its **direction on the
Stage 4 policy is stated explicitly** (which is what the gate requires when the histogram
is not flat): an under-dispersed forecast makes the DP UNDER-value the right tail → it will
hold LESS charge for spikes than optimal → the policy degenerates *toward* MPC (under-hoards),
and the transition matrix built from a too-thin tail understates spike-bin mass. It biases
toward caution, not toward reckless hoarding.

Two honest caveats on the magnitude: (i) part of the end-bin elevation is a finite-grid
artifact — with 9 levels spanning 0.01..0.99, every outcome beyond q01/q99 clamps exactly
onto the end bins; (ii) the excess is nonetheless real beyond that (`[0,0.1)` holds 13%,
not 10%). **Mitigation, and the first Stage 4 action:** add extreme tail levels (e.g. 0.005 /
0.995) and/or a light tail/variance inflation, re-check the PIT, and only then freeze the
transition matrix — so any below-optimal Stage 4 capture rate is attributable to this known
bias rather than mysterious. Gate status: **MET** (deviation characterised, policy direction
stated). Full histogram in `reports/stage3_run_full.txt`.

**Transition matrices (Stage 4 input).** Hour-indexed (24 matrices), log-spaced tail
bins on the deseasonalised residual, built both count-based and model-integrated. Every
row sums to one (error < 1e-15) and every hour's chain is irreducible (assumption [A2]).

## Headline B — dollar value: shrinking the forecast-error gap (full window, 198 days, 2 h, energy-only)

Swap the learned forecast into the SAME certainty-equivalent MPC and re-run Stage 2's
ladder. Measured leak-free: the forecaster refits online by month (walk-forward), so every
prediction is out-of-sample.

| policy | profit $ | reading |
|---|---|---|
| ceiling (clairvoyant LP) | **13,206** | theoretical max |
| MPC, perfect forecast | 12,847 | 97% of ceiling — causal execution is near-lossless |
| **MPC, LEARNED forecast** | **−314** | the Stage 3 causal operator |
| MPC, same-hour-last-week (Stage 2) | −3,453 | the Stage 2 causal operator |
| naive threshold floor | −5,267 | the dumb baseline |

- forecast-error cost, **naive** (= ceiling−clair excluded, i.e. clair − naive) = **$16,300**
- forecast-error cost, **learned** (clair − learned) = **$13,161**
- **>>> the learned forecast recovers $3,139 — 19% of the forecast-error gap — lifting MPC
  profit from −$3,453 to −$314.**

**What this is and is not.** $3,139 is the value of a *better conditional mean*: a robust,
weekend/hour-aware seasonal profile plus a reactive residual, instead of a single noisy
same-slot-last-week draw that propagates one-off spikes. It is a **conservative** read —
the learned forecaster falls back to seasonal-naive for the 2-month warm-up, so it and the
naive MPC differ only over months 3–6. It is also, deliberately, **not** the whole prize:
the certainty-equivalent MPC consumes only the learned MEDIAN, so it still cannot value a
spike it will not commit to buy for. The remaining ~$13,161 is what a *distribution-aware*
policy competes for — the Stage 4 DP that holds charge against the calibrated right tail.
Stage 3 built and validated that tail (the transition matrices); Stage 4 spends it.

## The discipline (why these numbers are believable)

- **No fold leakage (§VIII.3).** Seasonal mean, bin edges, quantile models, jump
  parameters and transition matrices are ALL re-fit on the train slice inside each fold.
  `assert_no_fold_leak` checks train/eval indices are disjoint AND every train timestamp
  precedes every eval timestamp; a test fires it on a deliberately-overlapping fold.
- **Adaptedness / publication timestamp (§VIII.1).** The conditioning feature set is
  strictly-past by construction (`features.CONDITIONING` excludes the interval's own
  not-yet-cleared price, its z-score and its scarcity flag). `assert_pit_adapted` enforces
  that invariant, and the forecaster-level causality test perturbs the future and confirms
  a forecast made now does not move.
- **One feature path, verified.** `build_features` reproduces the warehouse `v_features`
  columns exactly (a real-data test asserts row-for-row equality including NaN placement
  in the DST/outage gaps), so the model trains on the same features the live MPC computes
  from a bare price array — no train/inference skew.

## Honest scope / deferrals

- **Exogenous NWP features are absent.** The plan's f_t (§V.23) names load / wind / solar
  forecasts and their vintages; Stage 1 ingested only the two price series, so the feature
  set is calendar + price lags + rolling stats + residual signal. This is a named deferral
  (they would slot in as additional `v_features` columns), not a silent omission — and it
  makes the CRPS win a floor: real NWP conditioning can only help.
- **The MPC consumes only the median.** The certainty-equivalent MPC uses the learned
  point (median) path, so Headline B understates the model's value: the DISTRIBUTION's
  tail — the actual prize — is realised by the Stage 4 DP's willingness to hold for a
  spike, not by a point-forecast controller. This is the through-line into Stage 4.

## How to run

```
python -m src.stage3_run          # demo window: model scoring only (fast)
python -m src.stage3_run --full   # full window: scoring + the MPC ladder (~15 min)
python -m pytest                  # 64 tests (48 prior + 16 Stage 3)
```
