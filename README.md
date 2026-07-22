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

## Status

**Stage 0 (viability) complete — verdict: qualified PROCEED. Stage 1 (data &
oracle foundation) complete.**

On the full post-launch window (HB_NORTH, 2025-12-05 → 2026-06-20, 18,885
15-minute intervals), the RTC+B SOC-enforcement constraint binds and its shadow
price is a **heavy-tailed scarcity price**: near zero in normal conditions (median
~$0.02/MWh), spiking to $10–33/MWh on genuine scarcity days. Because
perfect foresight positions the battery to dodge the constraint better than any
real operator can, this is a *lower bound* — and the summer scarcity season is not
yet in the data. Full numbers, verification checks, and caveats:
[`reports/step0_results.md`](reports/step0_results.md).

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
tests/             pytest verification suite (oracle checks, warehouse integrity,
                   ingest dedup) — runs in CI with no ERCOT data
.github/workflows/ci.yml   GitHub Actions: install + oracle self-test + pytest
reports/
  step0_preregistration.md   parameters + kill condition, frozen before the run
  step0_results.md           Stage 0 diagnostics, gate verdict, verification checks
  stage1_notes.md            Stage 1 build record (warehouse, oracle, tests, decisions)
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

## Roadmap (stages)

| Stage | Delivers |
|---|---|
| 0 — Viability | Perfect-foresight LP, gate, reframe ✅ |
| 1 — Data & oracle foundation | DuckDB/SQL warehouse, LP oracle w/ boundary conditions, tests + CI ✅ |
| 2 — MPC / first causal policy | Receding-horizon reoptimization + baseline → first value-of-foresight gap |
| 3 — Learned price model | Quantile-regression conditional distribution, calibration |
| 4 — Dynamic program | Optimal causal policy → Q2 (psi_up), Q3 (duration curves) |
| 5 — Statistics & writeup | Walk-forward protocol, sign test, power statement |

Stages 6–9 (residential-fleet chapter, fleet benchmark, risk/hedging, RL exhibit)
are optional add-ons.

## Method notes

- **15-minute resolution** throughout — the ERCOT settlement interval; hourly
  averaging would destroy the price spikes that carry the economics.
- **Perfect-foresight results are bounds, not forecasts.** Every performance
  number is bracketed between a clairvoyant ceiling and a naive floor.
- **Pre-registration.** Stage 0 parameters and the kill condition were committed
  before the first real run to prevent tuning-to-result.

Raw ERCOT data is not committed (it is regenerable via the code and may carry
redistribution terms); credentials live in a gitignored `.env`.
