# Stage 4 — periodic dynamic program: build notes

**Status: DP CORE COMPLETE and verified (energy-only). The headline deliverables
(Q2 ψ_up, Q3 duration curves, realised V^DP, capture-rate prong) are the next steps.**
This is the first gate of the headline stage — the optimal causal policy's value
function, solved to the 24-periodic average-reward fixed point and validated against
the perfect-foresight LP.

## What was delivered

| module | what it is |
|---|---|
| `src/dp.py` | the periodic DP: post-decision-state value function (§IV.2), grid-aligned actions (§IV.8b), relative value iteration via a **backward Gauss-Seidel day-sweep** to the 24-periodic fixed point (§IV.9), μ extraction, and the verification suite (DP↔LP, μ-monotonicity) |
| `src/stage4_run.py` | solves the DP on the real Stage 3 residual kernel + a representative-weekday seasonal profile; reports in-model $/day + the gate |
| `tests/test_dp.py` | 6 tests: DP↔LP agreement, Bellman convergence, μ-monotonicity, grid convergence, flat-price no-sustainable-profit, spread-is-profitable |

## The gate — PASSED (energy-only, deterministic validation)

- **DP↔LP agreement (the core correctness test, §IV.9 pt 3 / §IV.12):** on a deterministic
  price the DP's average reward per day matches the perfect-foresight LP's cyclic per-day
  objective to **<0.3% at 1–2 h** (2.0% at 4 h, shrinking with the grid).
- **Bellman residual ~0** (the fixed-point span converged; the average-reward equation
  D(V₀)−V₀ = ρ_day·1 holds).
- **μ monotone non-increasing in S⁺** (violation ~1e-11 = machine precision) — the offer
  curve is monotone, exactly as §IV.7 requires; this is the check that fails if the §IV.8
  interpolation rule is violated, and it passes.
- **Grid convergence** (§IV.8): rel-diff vs LP shrinks monotonically 9.8e-3 → 2.0e-3 as
  N_S 50→400, converging as ΔS→0.

**Implementation note worth recording.** Naïve synchronous value iteration propagated only
one interval of look-ahead per sweep and did not converge in thousands of iterations (the
deterministic cyclic price mixes slowly). A **backward Gauss-Seidel day-sweep** — updating
V[h] from the freshly-updated V[h+1] within one pass — propagates a full day of look-ahead
per sweep and converges in **~2–11 sweeps**. Same fixed point, ~1000× fewer iterations.

## First Stage 4 number (in-model expected value, real kernel, energy-only)

Solved on the full-window empirical residual kernel (12 bins × 24 hours) with a
representative-weekday seasonal profile, `BatteryParams` default (c_deg = 25 $/MWh):

| duration | DP $/day (in-model) | ×198 days | vs perfect-foresight ceiling |
|---|---|---|---|
| 1 h | 26.59 | 5,264 | — |
| **2 h** | **46.56** | **9,220** | **~70% of the $13,206 ceiling** |
| 4 h | 72.96 | 14,447 | — |

The ~70%-of-ceiling in-model value sits squarely in the §VIII.4 "50–80% is credible" range —
encouraging that the DP is behaving like a competent operator, not a leaking/over-optimistic one.

**IMPORTANT — what this is and is NOT.** ρ_day is the DP's **in-model expected** profit for a
representative weekday under the LEARNED kernel. It is **not** the realised out-of-sample
V^DP of §IV.13 — that requires simulating the DP's offer-curve policy forward on the real
price path (walk-forward, no lookahead), the next step and the number that enters the
value-of-information ladder alongside the Stage 0 ceiling ($13,206), the Stage 3 MPC (−$303),
and the naive floor (−$5,267).

## New finding that sharpens the plan — arbitrage here is SPIKE-driven, not diurnal-driven

The DP on the **smooth diurnal seasonal alone** earns **$0/day**: the representative-weekday
spread (~$23, min $19.6 / max $43.0) is far below the round-trip breakeven (~$85.56 at these
parameters, §IV.4). **All** of the DP's $46/day comes from the **residual (spike) dynamics** in
the kernel. Consequence: **the tail of the kernel is the headline.** This elevates the
tail-recalibration (already Stage 4's step 0) from housekeeping to the single most important
determinant of the result — Stage 3's mild under-dispersion (+22% end-bin excess) biases the
DP to under-value spikes, so **$46/day is very likely an under-estimate** pending the tail fix.
No change to the plan's ordering, but a strong confirmation of it.

## Data note

The planned data refresh to ~228 days was a **no-op**: `build_panel` re-filters the CACHED
ancillary MCPC bundle (NP6-796-ER), which stops at 2026-06-20, and the inner join caps the
panel there. Extending into summer needs **re-downloading ERCOT's MCPC archive** (a data-plumbing
task), not merely elapsed time — so the summer top-up (Decision B2) is gated on that fetch. We
proceed on the 198-day Dec–Jun window; summer can only raise the headline.

## Next Stage 4 steps (in order)

1. **Tail-recalibrate the kernel** (the load-bearing step, per the finding above); re-check with a non-clamping PIT.
2. **Realised V^DP** — wire the DP offer curve (§IV.6) into the walk-forward backtest; slot into the §IV.13 ladder.
3. **Reserves / (AS) co-optimisation** (option 2A) → **Q2 ψ_up** distributions + the §IV.11 FD-vs-multiplier identity.
4. **Duration sweep** → **Q3** (two curves + capture-rate curve); the pre-vs-post-RTC+B natural experiment.
5. **§V.26 capture-rate prong** — DP on the learned vs empirical kernel; finalise adoption.
6. **State-augmentation test** (§VIII.7) — (h,b) vs (h,b,z); **grid-convergence** headline table.

## How to run

```
python -m src.dp                 # DP self-test (DP<->LP, grid convergence), no data
python -m src.stage4_run --full  # DP on the real kernel + the gate
python -m pytest                 # 72 tests (66 prior + 6 Stage 4)
```
