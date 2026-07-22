# Stage 1 — Data & Oracle Foundation: build notes

**Status: complete, at the Stage 1 gate — awaiting review before Stage 2.**

Stage 1 hardens the Stage 0 artifacts into a reusable foundation every later
policy consumes: a governed SQL warehouse, the perfect-foresight LP as a clean
oracle module, and the verification suite as CI-enforced tests. Nothing here
changes any Stage 0 number — `python -m src.step0_run` still reproduces
`reports/step0_results.md` byte-for-byte (the ingest change below is opt-in).

## What was delivered

**1. DuckDB/SQL warehouse — `src/warehouse.py`, `data/warehouse.duckdb`.**
One base table + three feature views over the price + MCPC panel:

| object | what it is |
|---|---|
| `price_mcpc` | base fact, one row per (settlement point, 15-min interval): energy price + the five AS MCPCs |
| `v_calendar` | + hour-of-day, quarter-of-day (0–95), day-of-week, weekend flag, month; and the reserve-price aggregates `mcpc_up_contingency` (RRS+ECRS+NSPIN), `mcpc_up_all`, `mcpc_dn` |
| `v_features` | + point-in-time lags (15-min, 1-day, **1-week = Stage 2's "same-hour-last-week" forecast**), trailing-day rolling mean/std, a z-score, and a `is_scarcity` (>$100/MWh) flag |
| `v_daily` | per-day rollup: price min/mean/median/max/range, scarcity-interval count, mean up-reserve MCPC — for the exploratory analysis |

Lags are computed by an **exact timestamp self-join** (`ts − INTERVAL 7 DAY`),
not a row offset, so they stay correct across the real data gaps rather than
silently pointing N rows back into a gap.

Run `python -m src.warehouse` to (re)build and print the assertion summary.

**2. Oracle module — `src/oracle.py`.** The Stage 0 LP generalised. The load-
bearing new capability is **boundary conditions** (`solve(..., s_init=, s_final=,
cyclic=)`): Stage 0 runs the full window with a cyclic SOC (default, unchanged);
Stage 2's MPC will solve a short rolling window from the battery's *current*
charge via `s_init=<SOC>, cyclic=False`, take `result.first_action()`, and carry
`S_next` into the next solve. Returns a typed `OracleResult`, not a bare dict.
`src/step0_lp.py` is now a thin re-export shim, so `step0_run.py` is untouched.

**3. Tests + CI — `tests/`, `.github/workflows/ci.yml`, `pyproject.toml`.**
38 tests, all green. The four required verification checks (docs/step0_spec.md §7)
are now pytest, plus boundary/rolling-reuse coverage, the timestamp-gap audit, and
an analytical instance:

- **u=0 recursion / sign check (Correction 2):** on a strictly-rising-price
  instance where both SOC bounds bind with *nonzero* duals, the three-term
  stationarity `mu[k−1] = mu[k] − lam_hi[k] + lam_lo[k]` holds to 1e−7 — this
  pins the HiGHS dual sign, verified empirically to match Correction 2.
- **Complementary slackness** on *every* extracted constraint (not just the SOC
  ceiling as before).
- **No dumping** `min(c,d)=0`, all product sets and durations.
- **Duration identity:** `sum(lam_hi + psi_dn)` brackets between the one-sided
  finite differences (never a central average — the LP is kinked).
- **Analytical:** buy 1 MWh @ $1, sell @ $100, unit efficiency → profit exactly $99.

CI runs on push/PR with **no ERCOT data**; the data-dependent tests skip via
`skipif`, everything else uses synthetic in-memory instances.

## Data-quality finding + fix (Option A, decided)

The joined panel contained **6 exact-duplicate `(date,hour,interval)` rows** (the
energy query API repeats a row across a page boundary) — verified identical
across all value columns, so benign. The warehouse's uniqueness assertion caught
them.

- **Fix:** `src/ingest.dedup_panel()` drops them, *asserting they are identical
  first* so a future *conflicting* duplicate raises instead of being silently
  discarded. **`build_panel` now dedups by default** (Option A).
- **Stage 0 regenerated on the deduped panel.** This is a data-hygiene fix, not a
  parameter change, so it is consistent with the frozen pre-registration (which
  freezes the modelling *parameters*, not the raw pull). Effect: T 18,891 →
  **18,885**; headline contingency-2 h binding fraction 7.98% → **8.00%**; psi_up
  max **$32.75 unchanged**; **verdict unchanged** (qualified PROCEED). Full
  changelog at the top of `reports/step0_results.md`. Pre-dedup numbers reproduce
  with `build_panel(..., dedup=False)`.

## Timestamp-gap audit (added)

`warehouse.audit_gaps()` lists every jump in the time axis larger than one
interval, and `assert_warehouse` HARD-fails on any *sub*-interval step (a
compressed axis = misalignment). On the real panel: 22 gaps totalling exactly
123 missing intervals (= the "short by 123" figure). The **DST spring-forward
(Mar 8) shows as a clean 75-min forward jump** `01:45 → 03:00` (the missing 2 AM
hour), confirming the axis jumps forward rather than double-counting — the
DST-misalignment risk is closed. The rest are the early-May ERCOT outage.

## Warehouse coverage note (a deliberate scope call)

This warehouse covers the **two series Stage 0 used** (energy price NP6-905-CD,
RT MCPC NP6-796-ER) at one settlement point. The plan's full §IX.3 star schema —
awards, dispatch, forecasts, day-ahead — is **deferred to the stages that consume
those tables (Stage 2/3)**. Building empty fact tables now would be decoration,
not the "genuine evidence" §IX.4 asks for. The schema is shaped so those tables
slot in later by joining on `ts` + `settlement_point`. Flagging this as a
narrowing of the plan's Stage 1 "What", made because the consuming code doesn't
exist yet and several of those series need endpoints/keys not yet wired.

## Gate check (plan Stage 1 gate)

- ✅ LP passes the complementarity assertion `min(c,d)=0` and the analytical
  small-instance tests (pytest, green).
- ✅ The oracle computes the ceiling for every duration in the Q3 sweep
  {1,2,4} h (real-data test asserts optimal + finite + the energy-only ≤
  +contingency ≤ +all-products ordering).
- ✅ Warehouse integrity assertions pass on the whole panel (uniqueness, no
  nulls, price bounds, monotone timestamps, no sub-interval step, no >96-interval
  day; short days and time-axis gaps from DST/outages reported, not fatal).
- ⚠️ Publication-timestamp assertions (§VIII.1): **N/A for this panel** — these
  are settlement prices with no meaningful per-row publication lag. The
  point-in-time discipline they enforce becomes load-bearing at Stage 2/3 (the
  walk-forward no-lookahead backtest and forecasts), and is deferred there with
  the fact tables that carry publication timestamps.

## How to run

```
source .venv/bin/activate
python -m src.warehouse     # build data/warehouse.duckdb + assertions
python -m pytest            # 35 tests
python -m src.step0_run     # regenerate Stage 0 (unchanged)
```

## Next: Stage 2 — MPC / first causal policy

Wrap `oracle.solve(..., s_init=, cyclic=False)` in a receding-horizon loop over a
simple forecast (start with `v_features.price_lag_1w`), backtest walk-forward
against the perfect-foresight ceiling and a naive floor, and report the first
**value-of-foresight gap** (Decision 19). The live decision log begins there.
