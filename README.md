# Battery Dispatch under ERCOT's RTC+B Market Design

Sequential decision algorithms for grid-scale battery (ESR) dispatch in ERCOT
under the **Real-Time Co-optimization + Batteries (RTC+B)** market design that went
live **5 December 2025**, built entirely on post-launch public data with an
honest, reproducible evaluation protocol.

## The question

RTC+B enforces, for the first time, a **per-resource state-of-charge (SOC)
requirement**: a battery must physically hold enough stored energy to back the
reserve capacity it sells. This project measures two things that fall out of one
model:

- **Q2 — the cost of that SOC enforcement:** the shadow price `psi_up` on the
  "hold charge to back upward reserves" constraint.
- **Q3 — the marginal economic value of storage duration:** how much an extra hour
  of battery duration is worth under the new rules.

The organizing idea is the **value of foresight**. A perfect-foresight linear
program is a clairvoyant upper bound on profit; a causal policy (which knows only
the past and a forecast) is what a real operator achieves; the gap between them is
what better forecasting and optimization compete for. The project builds that
sequence — perfect-foresight LP ≥ dynamic program ≥ receding-horizon MPC ≥ naive
baseline — and reads the shadow prices off it.

## Status — core study complete (Stages 0–5)

All five core stages are done, verified, and adversarially reviewed. **The findings-first
writeup is [`reports/stage5_writeup.md`](reports/stage5_writeup.md)** — start there.

Headline findings on the full post-launch window (HB_NORTH, 2025-12-05 → 2026-06-20, 18,885
15-minute intervals, 2 h battery, walk-forward / no lookahead):

- **The value of foresight.** A clairvoyant controller captures 97% of the perfect-foresight
  ceiling, so execution is nearly free — the whole difficulty is the *forecast*. The optimal
  causal **dynamic program captures 34% of the matched-window ceiling ($2,364; 18% of the full
  ceiling)** and turns the certainty-equivalent MPC's *loss* into a profit; that matched swing
  (**+$2,020**) is the **option value of acting on the price *distribution* rather than a point
  forecast**.
- **Honest inference (§VIII.5).** On this thin, tail-concentrated window the DP's edge over a
  *good* forecast-driven MPC is **not statistically separable from zero** — but the sign test
  (46%, *p*=0.55) *understates* it, so a magnitude-aware permutation test is reported alongside
  (one-sided *p*≈0.07: marginal, not a coin flip); the bootstrap CI on the edge straddles zero at
  every block length, detectable only above ~54% of the ceiling vs an observed ~29%. It *does*
  beat a *naive* forecast on 75% of days (*p*<0.001), and its profit is spike-concentrated —
  **the top 5 of 140 days carry 114% of the net total**.
- **Q2 — cost of RTC+B's SOC rule** ($\psi_{up}$): a heavy-tailed scarcity price, ~$0 normally,
  with a bounded mean scarcity cost (**95% CI on the mean daily-max [$0.68, $2.63]/MWh**),
  concentrated in a handful of days. On the single worst event the causal $\psi_{up}$ rises above
  the clairvoyant bound (a real operator caught short pays more than one who saw it coming) — a
  directional illustration, not a headline. Cheap on average, expensive exactly when scarcity hits.
- **Q3 — marginal value of duration:** concave; causal capture rises from −3% (0.5 h) to a ~25%
  plateau (8 h) — **duration buys forgiveness for forecast error**.

Every headline carries a clairvoyant-ceiling/naive-floor bracket, a confidence interval, and a
concentration statistic. Full detail and figures: [`reports/stage5_writeup.md`](reports/stage5_writeup.md).

## Repository layout

```
src/
  ercot_api.py     ERCOT public-reports API client (auth + pagination)
  ingest.py        energy prices (NP6-905-CD) + real-time ancillary MCPC (NP6-796-ER)
  oracle.py        perfect-foresight LP oracle: dual extraction + boundary conditions
                   (s_init/s_final/cyclic) for a rolling MPC; verification suite
  warehouse.py     DuckDB warehouse over the price+MCPC panel; feature pipeline as
                   SQL views; integrity assertions + timestamp-gap audit
  step0_lp.py      Stage 0 compatibility shim re-exporting src.oracle
  step0_run.py     regenerates every Stage 0 number from cached raw data
  forecast.py      causal price forecasters (persistence, seasonal-naive, perfect, learned GBT)
  features.py      point-in-time feature pipeline; seasonal + residual construction
  price_model.py   Stage 3 gradient-boosted quantile-regression conditional price distribution
  markov.py        hour-indexed residual transition matrices (the DP kernel)
  policies.py      naive floor, receding-horizon MPC, and the walk-forward DP policy
  backtest.py      walk-forward simulator; no-lookahead by construction
  dp.py            Stage 4 periodic post-decision-state dynamic program + verification suite
  reserves.py      reserve LP, MCPC pricing, the psi_up dual + its finite-difference validation
  stage2_run.py    value-of-foresight ladder + reserves + causal psi_up
  stage3_run.py    learned price model: pinball/CRPS/PIT scoring vs baselines
  stage4_run.py    leak-free DP ladder, Q3 duration sweep, §V.26 prong, Q2 psi_up
  stage5_stats.py  §VIII.5 inference: sign test, block bootstrap, concentration, jackknife, power
  stage5_run.py    heavy leak-free orchestration → matched-window daily paired differences
  figures.py       regenerate all writeup figures from the cache
tests/             103-test pytest suite (oracle, warehouse, ingest, Stages 2–5)
                   — runs in CI with no ERCOT data
.github/workflows/ci.yml   GitHub Actions: install + oracle self-test + pytest
reports/
  step0_preregistration.md   parameters + kill condition, frozen before the run
  step0_results.md           Stage 0 diagnostics, gate verdict, verification checks
  stage1_notes.md … stage4_notes.md   per-stage build records + adversarial-review outcomes
  stage4_decisions.md        Stage 4 decisions, rationale, self-critique
  stage5_notes.md            Stage 5 statistical-inference detail
  stage5_writeup.md          THE findings-first writeup — start here
  figures/                   the six writeup figures (regenerable)
docs/
  ERCOT_Battery_Dispatch_Plan_v2.md   full plan: derivations, decisions, execution stages
  step0_spec.md                       Stage 0 build contract
  decision_C_reframing.html           reasoning + worked numbers for the Q2/Q3 reframing
```

## Reproducing Stage 0

Requires Python 3.12 and an [ERCOT API](https://apiexplorer.ercot.com/) account
(free) with a Public API subscription key.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in your ERCOT credentials
python -m src.step0_run       # ingests, solves, prints every diagnostic
```

`src/oracle.py` also runs a self-test on synthetic prices with no ERCOT account
needed (`python -m src.oracle`), validating the solver and verification checks.

## Stage 1 — warehouse and tests

```bash
python -m src.warehouse   # build data/warehouse.duckdb + run integrity assertions
python -m pytest          # 38 tests: oracle verification suite, warehouse, ingest
```

The warehouse loads the price + MCPC panel into DuckDB and exposes the feature
pipeline (calendar features, point-in-time lags incl. same-hour-last-week,
rolling stats, scarcity flags) as SQL views, with integrity assertions and a
time-axis gap audit. The test suite is CI-gated and needs no ERCOT data — the
data-dependent tests skip automatically. Full build record:
[`reports/stage1_notes.md`](reports/stage1_notes.md).

## Stage 2 — MPC and the value of foresight

```bash
python -m src.stage2_run          # 63-day demo (fast)
python -m src.stage2_run --full   # full post-launch window (~15 min)
```

A receding-horizon MPC (re-optimising every 15 min against a forecast) is walked
forward with no lookahead against a perfect-foresight ceiling and a naive floor.
With a perfect forecast the controller captures 97% of the ceiling, but a naive
same-hour-last-week forecast turns the opportunity into a loss — the gap that
Stages 3–4 exist to close. Full detail: [`reports/stage2_notes.md`](reports/stage2_notes.md).

## Stages 3–5 — learned model, dynamic program, and the statistics

```bash
python -m src.stage3_run --full   # learned price distribution: pinball / CRPS / PIT vs baselines
python -m src.stage4_run --full   # leak-free DP ladder, Q3 duration sweep, §V.26 prong, Q2 psi_up
python -m src.stage5_run --rebuild # §VIII.5 inference (~12 min); then figures
python -m src.figures             # regenerate the six writeup figures from the cache
```

Stage 3 learns a gradient-boosted quantile-regression conditional price distribution
(it wins held-out CRPS but — a reported negative result — that does *not* translate into
separably better *decisions*). Stage 4 solves the periodic dynamic program that is the
project's centrepiece and reads off Q2/Q3. Stage 5 turns the point estimates into defensible
inference. **The synthesis is [`reports/stage5_writeup.md`](reports/stage5_writeup.md).**

## Roadmap (stages)

| Stage | Delivers | |
|---|---|---|
| 0 — Viability | Perfect-foresight LP, gate, reframe | ✅ |
| 1 — Data & oracle foundation | DuckDB/SQL warehouse, LP oracle w/ boundary conditions, tests + CI | ✅ |
| 2 — MPC / first causal policy | Receding-horizon MPC + reserves → first value-of-foresight gap | ✅ |
| 3 — Learned price model | Quantile-regression conditional distribution, calibration | ✅ |
| 4 — Dynamic program | Optimal causal policy → Q2 (psi_up), Q3 (duration curves) | ✅ |
| 5 — Statistics & writeup | Walk-forward protocol, sign test, power statement, findings-first writeup | ✅ |

**Stages 0–5 constitute the complete, defensible study.** Stages 6–9 (residential-fleet
chapter, ~300-asset fleet benchmark, risk/hedging, RL exhibit) are optional add-ons.

## Method notes

- **15-minute resolution** throughout — the ERCOT settlement interval; hourly
  averaging would destroy the price spikes that carry the economics.
- **Perfect-foresight results are bounds, not forecasts.** Every performance
  number is bracketed between a clairvoyant ceiling and a naive floor.
- **Pre-registration.** Stage 0 parameters and the kill condition were committed
  before the first real run to prevent tuning-to-result.

Raw ERCOT data is not committed (it is regenerable via the code and may carry
redistribution terms); credentials live in a gitignored `.env`.
