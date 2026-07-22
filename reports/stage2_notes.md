# Stage 2 — MPC / first causal policy: build notes

**Status: COMPLETE.** Energy-arbitrage value-of-foresight ladder + reserve
co-optimisation + the causal psi_up + a persisted live decision log. This is the
first *causal* policy (a real operator who knows only the past + a forecast), and
the first measurement of the **value of foresight**.

## What was delivered

| module | what it is |
|---|---|
| `src/forecast.py` | causal price forecasters: persistence, seasonal-naive (same-slot one day/week ago — the Stage 2 default), and a `PerfectForecaster` **ceiling reference** (sees the future; not a real policy) |
| `src/policies.py` | `NaiveThresholdPolicy` (floor, a price-contingent **offer curve** from trailing quantiles); `MPCPolicy` (receding-horizon, commits the LP's planned first action) |
| `src/backtest.py` | walk-forward simulator; no-lookahead is **structural** (the policy only ever receives `prices[:t]`); emits the per-interval decision log (the live-log seed) |
| `src/stage2_run.py` | runs the ladder + the value-of-foresight decomposition |
| `tests/test_stage2.py` | 10 tests: offer/committed dispatch + clipping, forecaster causality, no-lookahead, SOC feasibility, terminal-value-prevents-drain, ceiling≥MPC≥floor, clairvoyant-MPC-recovers-ceiling |

Oracle gained a `terminal_value` parameter (values leftover charge S[T]) so a
finite MPC horizon does not drain the battery at the edge; default `None` leaves
Stage 0 unchanged (tested).

## Headline result — the first value of foresight (full window, 198 days, 2 h, energy-only)

| policy | profit $ | reading |
|---|---|---|
| ceiling (clairvoyant LP) | **13,206** | theoretical max, knows every future price |
| MPC, perfect forecast | **12,847** | **97% of ceiling** — causal execution is nearly lossless |
| MPC, same-hour-last-week | **−3,453** | the realistic causal operator |
| naive threshold floor | −5,267 | the dumb baseline |

**Value of foresight = ceiling − naive MPC = $16,660**, and it decomposes cleanly:

    execution/startup cost   $360    (2% — causal control + starting from empty)
    forecast-error cost      $16,300 (98% — a naive forecast on spiky prices)

(The 63-day demo gives the same picture at ~1/2.5 the magnitude: VoF $7,796 =
$194 execution + $7,602 forecast error. Cross-check: the energy-only ceiling here,
$13,206, matches Stage 0's perfect-foresight energy-only 2 h objective $13,207.)

## The finding, stated plainly

On real (spiky winter) ERCOT prices, a **same-hour-last-week forecast is not merely
suboptimal — committed to, it turns a ~$6,500 arbitrage opportunity into a ~$1,000
loss.** The battery buys and sells on a backward-looking pattern that the spikes
violate, and the $25/MWh degradation cost finishes the job. The clairvoyant MPC
proves this is *forecast error*, not a broken controller: with a perfect forecast
the same controller captures 97% of the ceiling. **Almost the entire value of
foresight here is the quality of the price forecast** — which is exactly what
Stage 3 (a calibrated probabilistic model) and Stage 4 (the optimal DP) exist to
capture. This is the motivating result for the rest of the project.

## A design decision worth recording

The plan's preferred execution is a **price-contingent offer curve** priced off the
LP's SOC-balance dual `mu[0]` (§IV.6/§VIII.2). We built and tested it — and it
captures only **~57% of the ceiling even with a perfect forecast**, because `mu[0]`
is degenerate at the SOC bounds, so the offer band chases the price and whipsaws.
The **certainty-equivalent** MPC (commit the LP's planned first action, value it at
the realised price) captures ~97%. Both are F_t-measurable / non-leaking; the
certainty-equivalent one is simply the robust choice at this stage. The
price-contingent offer-curve MPC needs a robust marginal water value — which is
exactly what the **Stage 4 DP value function** provides — so that refinement is
deferred there rather than faked with a fragile `mu[0]`. (The naive floor still
executes as a genuine offer curve, so the harness supports both models.)

## Reserve co-optimisation + the causal psi_up (full window, 198 days, 2 h)

The MPC also sells contingency reserves (RRS/ECRS/Non-Spin), co-optimised with
energy under the RTC+B headroom constraint. Every sold reserve MW is backed by
held charge — the backtest asserts $S_{t+1} \ge \tfrac{1}{\eta_d}\sum_k \tau_k u^k_t$
at every interval.

| component | $ |
|---|---|
| energy arbitrage (naive forecast) | −3,285 |
| reserve capacity | **+2,919** |
| **total (causal reserve MPC)** | **−366** |

**Reserves are the battery's safe carry.** They pay for *availability*, not energy
timing, so a battery that mostly holds charge and offers reserves earns steady
income regardless of forecast quality — here +$2,919, nearly cancelling the
energy-only −$3,453 loss to leave −$366. Arbitrage is the risky alpha; reserves
are the low-variance carry.

**Causal psi_up** (the real-operator Q2 number, Decision 19), from the dual on the
first headroom constraint of each MPC solve:

| | median | p90 | p99 | max | binds |
|---|---|---|---|---|---|
| causal (naive MPC) | $0.015 | $0.230 | $1.46 | **$141.0** | 7.8% |
| Stage 0 (perfect foresight) | $0.015 | — | $1.47 | $32.8 | 8.0% |

The median and p99 nearly match, but the causal **tail is ~4× fatter** ($141 vs $33
max): a real
operator, mispositioned by an imperfect forecast, cannot dodge the SOC-enforcement
rule the way a clairvoyant can, so on the worst intervals it pays a far larger
shadow price — exactly Decision 19. This number is *forecast-limited* (the naive
operator is erratic); the definitive causal psi_up comes from the Stage 4 DP, a
competent causal operator. The machinery to extract it now exists.

The live decision log (one row per interval: state, action, reserves, psi_up,
profit) is persisted to `data/raw/stage2_decision_log_*.parquet` — the forward,
no-lookahead record the plan's continuous track calls for.

## Deferred to later stages (not Stage 2)

- **Price-contingent offer-curve MPC** — needs a robust marginal water value;
  arrives with the Stage 4 DP value function.
- **Definitive causal psi_up** — from the Stage 4 DP (competent operator), not the
  naive-forecast MPC.

## How to run

```
python -m src.stage2_run          # 63-day demo (fast)
python -m src.stage2_run --full   # full post-launch window (~15 min)
python -m pytest                  # 48 tests
```
