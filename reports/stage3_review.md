# Stage 3 — adversarial review record

A permanent record of the three-agent adversarial review of Stage 3 (the learned
conditional price model), run before starting Stage 4. Kept so the findings and their
resolution are on the record rather than only in ephemeral agent transcripts.

## Setup

Four agents, each starting from the same documentation (CLAUDE.md, the plan §V.24–26 /
§VIII.1/§VIII.3, `reports/stage3_notes.md`, all Stage 3 code + its Stage 0–2 dependencies),
all instructed to be adversarial and READ-ONLY:

- **A — mathematician / programmer:** formal correctness of the math and stats.
- **B — quantitative trader:** economic and strategic validity.
- **C — model risk / validation:** causality, evaluation integrity, reproducibility (this
  one independently re-ran the full pipeline).
- **D — synthesizer / chief reviewer:** reconciled the three, resolved the one real
  dispute by experiment, delivered the go/no-go.

## Verdict: GO WITH FIXES — no blockers

All three independently returned "Yes-with-fixes." C reproduced every headline number
bit-for-bit and could not break causality on real data (scrambling the future left the
forecast byte-identical; no month-boundary off-by-one). The object Stage 4 structurally
needs — the hour-indexed, row-stochastic, irreducible transition kernel — is correct,
leak-free, and reproducible. What was defective was the calibration *narrative* and
*scoring rigor*, plus one real seasonal level bias.

## Consolidated findings (severity, who raised it, adjudication)

| Sev | Finding | Raised | Adjudication / fix |
|---|---|---|---|
| Major | Deseasonaliser dropped the §V.26 `month` term → residual keeps a winter→summer level drift | A,B,C | **Confirmed.** Added a persistence-extrapolated month level (NOT groupby-month, which is worse under expanding folds). Fixed. |
| Major | CRPS integrated only over [0.01,0.99], under-penalising heavy tails | A,B,C | **Confirmed.** Now integrates full [0,1]; added 0.005/0.995 levels. Fixed. |
| Major | "ADOPT (§V.26)" declared on the CRPS half of a two-pronged gate | B,C | **Confirmed.** Softened to provisional-on-CRPS; capture-rate prong → Stage 4. |
| Major | Notes' calibration story wrong: unfounded "grid artifact" caveat + level bias mislabelled as symmetric under-dispersion | A,B | **Confirmed.** Caveat deleted; components separated. |
| Minor | Residual/AR lags used row-shift, not the gap-safe timestamp join; cross-gap pairs entered transition counts | A,B | **Confirmed.** Now built from the gap-safe price lag. Fixed. |
| Minor | `assert_pit_adapted` is a static name-set lint dressed as a per-row data guard | A,C | **Confirmed.** Docstring made honest; real teeth added as tests. |
| Minor | Laplace smoothing 1.0 made the empirical irreducibility check vacuous and handicapped the baseline | A | **Confirmed.** Smoothing 1.0→0.01; irreducibility now read off raw counts. Fixed. |
| Minor | Empirical baseline scored at a non-optimal bin count | B | **Confirmed.** Steelmanned across {8,12,16,24}; learned still wins at the best (4.703). |
| Minor | Point-in-time test omitted the residual conditioning columns; real-data causality never in the suite | A,C | **Confirmed.** Both tests added. |
| Minor | PIT hard-clamps exceedances to {0,1}; KS slightly optimistic | A,B,C | Disclosed; tail levels push the clamp out; a non-clamping re-check is a Stage 4 action. |
| Minor | Headline measured on Dec–Jun (misses summer scarcity); median CE controller can't anticipate spikes | B | Confirmed, not a bug; already Decision B2 (summer top-up gates the economic claim). |
| Minor | §VIII.1's literal per-row publication-timestamp mechanism not implemented (structural discipline instead) | C | Defensible deferral; load-bearing only if vintaged NWP features are added. |
| Nit | `rearrange` used PAVA, not the sort the cited theorem covers; "log-spaced" misnomer; no UQ on $3,150; learned wins with richer conditioning | A,C | Fixed (sort; wording; disclosure); UQ → Stage 5. |

## The one real dispute, resolved by experiment (synthesizer)

A said the PIT tail elevation is genuine under-dispersion; B said it is largely a
superposition of opposite-signed per-fold seasonal level biases. The synthesizer re-fit the
seasonal with a month term and recomputed the PIT:

| variant | CRPS | PIT-KS | end bins | per-fold mean-PIT drift |
|---|---|---|---|---|
| baseline (qod, weekend) | 2.708 | 0.031 | 13.1% / 11.7% | 0.455 → … → 0.518 |
| month-aware | ~2.70 | 0.023 | 12.0% / 12.3% | compressed toward 0.5 |

**Both partly right; A wins the substance.** The month term removes the level bias (tails
become symmetric) but the elevation does NOT collapse — a genuine mild under-dispersion
(~+22% end-bin excess) remains. So the fix is: add the month term (done) AND recalibrate the
tail (a Stage 4 action). Final numbers after the full fix set: CRPS 2.718, PIT-KS 0.024.

## The standout insight (all three reviewers missed it)

The obvious way to "add month" — extending `fit_seasonal`'s groupby — makes things *worse*,
because expanding-window folds never train on the eval month, so every cell falls back to
the global median and discards the intra-day shape. The fix must be a month-*level*
extrapolation (persistence of the last training month's offset). This was implemented.

## What was fixed vs deferred

- **Fixed now** (see commit "Stage 3 review fixes …"): all four Major findings and every
  applicable Minor/Nit — month deseasonaliser, full-[0,1] CRPS + tail levels, provisional
  adoption + steelman, corrected calibration narrative, gap-safe residual lags, sort
  rearrangement, smoothing + honest dual irreducibility, honest `assert_pit_adapted`, and
  the two new tests.
- **Deferred to Stage 4** (need the DP): the §V.26 capture-rate prong; tail inflation +
  non-clamping-PIT re-check before freezing the kernel.
- **Deferred to Stage 5** (need the stats machinery): bootstrap / sign-test uncertainty on
  the $3,150 recovery.
- **Deferred until the data exists:** exogenous NWP features (§V.23, never ingested); the
  summer-scarcity top-up of the economic claim (Decision B2).
