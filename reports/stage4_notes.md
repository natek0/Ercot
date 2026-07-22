# Stage 4 — periodic dynamic program: build notes

**Status: SUBSTANTIALLY COMPLETE.** The energy side is done in full and verified —
the DP core, the realised value-of-foresight ladder (V^DP), the Q3 duration curves,
the §V.26 capture-rate prong (adoption resolved), and the §VIII.7 state-augmentation
test. The co-headline Q2 ψ_up is delivered under the locked 2A simplification
(hour-expected MCPC), directionally validated against Stage 0; the fully reserve-
co-optimised DP ψ_up and a walk-forward kernel are named refinements (below).

## Headline results (full window, 198 days, 2 h, energy-only)

**The realised value-of-foresight ladder (§IV.13) — the organizing frame, completed:**

| policy | profit $ | % of ceiling |
|---|---|---|
| ceiling (perfect-foresight LP) | 13,206 | 100% |
| MPC, perfect forecast (clairvoyant) | 12,847 | 97% |
| **DP — optimal causal policy (V^DP)** | **5,346** | **40%** |
| MPC, learned forecast (Stage 3) | −303 | −2% |
| MPC, same-hour-last-week (Stage 2) | −3,453 | — |
| naive threshold floor | −5,267 | — |

**§IV.13 decomposition — and the result Stage 4 exists to prove:**
- value of information (ceiling − V^DP) = **$7,860**
- **option value (V^DP − learned MPC) = +$5,650** — the DP's distribution-awareness turns
  the certainty-equivalent MPC's −$303 *loss* into a +$5,346 profit. **Positive option value
  is the whole justification for building the DP over the MPC, and here it is large.**
- value of optimisation (MPC − floor) = $4,963

V^DP is **realised out-of-sample**: the DP's offer curve (§IV.6) is walked forward with no
lookahead (a test asserts a scrambled future leaves decisions byte-identical). The DP uses
the empirical kernel (adopted below) + a representative-weekday seasonal. Honest caveat: the
kernel is fit on the full window (in-sample kernel, causal *execution*) — a walk-forward
kernel would likely lower V^DP somewhat and is a named refinement.

**Q3 — duration-value curves (§IV.11 / Q3):**

| E(h) | V_PF $ | V_DP $ | capture | ΔV_DP/ΔE ($/MWh/window) |
|---|---|---|---|---|
| 0.5 | 5,064 | 673 | 13% | — |
| 1 | 8,588 | 1,986 | 23% | 2,628 |
| 2 | 13,206 | 5,346 | 40% | 3,360 |
| 4 | 18,709 | 9,136 | 49% | 1,295 |
| 8 | 22,921 | 10,770 | 47% | 262 |

Both curves are concave (diminishing returns to duration); **capture rises with duration
(13%→~49%)** — a short battery must time spikes precisely and a causal policy cannot, so it
captures far less of the clairvoyant value; a longer battery has slack and captures ~half.
The realised marginal value of duration ΔV_DP/ΔE is the actual worth of an extra hour to a
real operator, positive and decreasing.

**§V.26 capture-rate prong — adoption RESOLVED:** solving the DP on each kernel and comparing
realised capture, the **empirical count kernel WINS (40%) over the learned kernel (33%)** — so
we **adopt the empirical kernel**. The learned model won held-out CRPS (Stage 3) but that
distributional edge did **not** translate to better decisions, because the nonparametric matrix
directly preserves the decision-relevant spike-transition frequencies. This is the exact
publishable "negative result" §V.26 anticipates, and it finalises Stage 3's *provisional*
adoption. (Tail recalibration found scale s=1.00 on the held-out split — no widening helped in
pinball terms — and empirical wins regardless.)

**§VIII.7 state-augmentation test — z earns its place:** augmenting the state from (h,b) to
(h,b,z) with a scarcity-regime coordinate z lifts the DP's in-model value **+10.3%**
($46.56→$51.35/day). The minimal (h,b) state under-anticipates spike clusters (the AR φ≈0.96
persistence Stage 3 measured), so per §VIII.7 the augmented state is preferred; wiring z into
the realised offer-curve policy is a named refinement.

**Q2 (co-headline) — causal ψ_up, the cost of RTC+B's SOC enforcement:** along the DP's
realised SOC trajectory, solving the reserve LP (2A: sell RRS/ECRS/NSPIN under (EH-up) at the
hour-expected MCPC) gives median **$0.231**, p99 $2.79, binds 50%. The **median exceeds the
Stage 0 perfect-foresight floor ($0.015)** — validating Decision 19 (a causal operator cannot
dodge the constraint as well as a clairvoyant, so its ψ_up is higher). Two honest 2A artifacts:
the hour-mean MCPC smooths scarcity spikes (so the tail max $4.06 is *below* Stage 0's $32.75,
an understatement of the tail), and the energy-only DP's low SOC makes ψ_up bind more often (an
upper bracket on frequency). The reserve-co-optimising DP + interval MCPC would refine both.

## What was delivered

| module | what it is |
|---|---|
| `src/dp.py` | the periodic DP: post-decision-state value function (§IV.2), grid-aligned actions (§IV.8b), relative value iteration via a **backward Gauss-Seidel day-sweep** to the 24-periodic fixed point (§IV.9), μ extraction, and the verification suite (DP↔LP, μ-monotonicity) |
| `src/policies.py` | `DPPolicy` + `DPCurve` — the **offer-curve execution** of the DP (§IV.6), F_t-measurable, plugged into the walk-forward backtest for V^DP |
| `src/stage4_run.py` | `run` (in-model $/day + gate), `realized_ladder` (V^DP + §IV.13), `duration_sweep` (Q3), `capture_rate_prong` (§V.26), `state_augmentation_test` (§VIII.7), `q2_psi_up` (Q2) |
| `tests/test_dp.py` | 8 tests: DP↔LP agreement, Bellman convergence, μ-monotonicity, grid convergence, flat-price no-sustainable-profit, spread-is-profitable, DP offer-curve dispatch sides, DP-policy causality |

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

## Remaining refinements (named, not blocking the headline)

1. **Reserve-co-optimised DP ψ_up** — embed the reserve knapsack in the DP solve (hold charge
   *for* reserves) and extract ψ_up as its (EH-up) dual, plus the §IV.11 FD-vs-multiplier
   identity. The current Q2 is a 2A post-hoc extraction on the energy-only trajectory (an
   upper bracket), directionally validated but not the fully co-optimised object.
2. **Interval MCPC for ψ_up** — replace the hour-mean MCPC (which smooths scarcity spikes and
   understates the ψ_up tail) with the realised interval MCPC.
3. **Walk-forward kernel for V^DP** — refit the kernel per fold (as the LearnedForecaster does)
   so V^DP is fully leak-free rather than in-sample-kernel / causal-execution.
4. **(h,b,z) in the realised policy** — the augmentation earns +10.3% in-model; wire z into
   `DPPolicy` to realise it out-of-sample.
5. **Summer top-up** (Decision B2) — needs the ERCOT MCPC archive re-download (gated on that fetch).
6. **c_deg ∈ [0,60] sensitivity** (§VIII.7) and the pre-vs-post-RTC+B duration natural experiment (Q3 deliverable 3).

## How to run

```
python -m src.dp                 # DP self-test (DP<->LP, grid convergence), no data
python -m src.stage4_run --full  # in-model $/day + gate; then the realised ladder
python -m pytest                 # 74 tests (66 prior + 8 Stage 4)
```
