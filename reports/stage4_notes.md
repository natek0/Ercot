# Stage 4 — periodic dynamic program: build notes

**Status: COMPLETE (energy DP + reserve co-optimisation + Q2/Q3), leak-free.** After a
critical-review pass, the two integrity gaps in the first cut were fixed: (Q1) the kernel
is now re-fit walk-forward per fold (was a full-window in-sample kernel that inflated V^DP
~2.4×), and (Q2) `psi_up` now comes from the fully reserve-CO-OPTIMISED DP (was a post-hoc
proxy), validated by the §IV.11-style C1 identity. **The corrected headline numbers are
materially lower and more honest than the first cut — see below.**

## The two fixes and why they mattered

1. **Walk-forward kernel (Q1 / §VIII.3).** The DP's transition kernel, seasonal, bin
   edges, reserve prices and the DP solve are ALL re-fit online by calendar month on
   strictly-prior data (`src/policies.WalkForwardDPPolicy`), exactly like the Stage 3
   LearnedForecaster. Effect at 2 h: **V^DP fell from $5,346 (40% capture) to $2,195
   (17%)** — the in-sample kernel had baked the eval period's (rising, summer-ward) spike
   frequency into the policy. A test pins the leak-free property (scrambled future → same
   decisions).
2. **Reserve co-optimisation (Q2 / A2·B2·C1).** The DP now HOLDS charge *for* reserves —
   the reserve value is folded into the reward (`src/reserves` + `solve_dp(reserve_tables=…)`),
   so the policy trades off arbitrage against reserve income, and `psi_up` is the reserve
   LP's dual on the energy-headroom (EH-up) constraint at the co-optimised SOC. The first
   cut instead read `psi_up` off an energy-only trajectory (wrong operating point).

## Headline results (full window, 198 days, 2 h, energy-only, WALK-FORWARD)

**The leak-free value-of-foresight ladder (§IV.13):**

| policy | $ | % of ceiling |
|---|---|---|
| ceiling (perfect foresight) | 13,206 | 100% |
| clairvoyant MPC | 12,847 | 97% |
| **DP — optimal causal (walk-forward)** | **2,195** | **17%** |
| learned MPC (Stage 3) | −303 | −2% |
| naive MPC / floor | −3,453 / −5,267 | — |

- **value of information (ceiling − V^DP) = $11,011** — the future is worth a lot, and a
  causal DP on a price-only kernel recovers ~17% of it.
- **option value (V^DP − learned MPC) = +$2,498** — the DP's distribution-awareness still
  turns the certainty-equivalent MPC's loss into a (small) profit, but the honest gap is
  ~$2,500, not the $5,650 the in-sample cut reported.

**Honest reading of 17%.** This is at the low end of the "50–80% typical" band (§VIII.4).
It is *not* a bug (DP↔LP agreement, μ-monotonicity, the causality test and the reserve C1
identity all pass) — it reflects genuinely limited information: a **price-only** kernel (no
exogenous NWP load/wind/solar features — never ingested), on a **short, mostly-winter/spring**
window, evaluated **walk-forward**. Richer features and more data (esp. summer) would raise it.

**Q3 — duration-value curves (walk-forward):**

| E(h) | V_PF $ | V_DP $ | capture | ΔV_DP/ΔE |
|---|---|---|---|---|
| 0.5 | 5,064 | −230 | −5% | — |
| 1 | 8,588 | 356 | 4% | 1,171 |
| 2 | 13,206 | 2,195 | 17% | 1,839 |
| 4 | 18,709 | 4,164 | 22% | 893 |
| 8 | 22,921 | 5,101 | 22% | 99 |

Both curves concave; **capture rises with duration (negative at 0.5 h → ~22% plateau)** — a
short battery must time spikes precisely and a causal policy cannot, so it captures almost
nothing (even loses money at 0.5 h); a longer battery has slack. The realised marginal value
of duration ΔV_DP/ΔE is positive and decreasing.

**§V.26 capture-rate prong (walk-forward) — adoption CONFIRMED:** empirical kernel **17%** >
learned kernel **15%** realised capture → **adopt the empirical kernel.** The Stage 3/4
conclusion (the learned model's CRPS win did not translate to better decisions) **survives
the walk-forward correction** — it was not an in-sample artifact.

**Q2 — causal `psi_up` (co-optimised reserve DP, walk-forward, ρ_k sweep):**

| ρ_k | median | p99 | max | binds% |
|---|---|---|---|---|
| 0.00 | **0.020** | 0.662 | 0.72 | 4.8% |
| 0.05 | 0.000 | 0.365 | 1.17 | 1.1% |
| 0.15 | 0.000 | 0.000 | 0.58 | 0.1% |

**C1 validation: 5/5 points pass** (ψ_up equals the finite-difference of the reserve value —
the §IV.11-style multiplier check). Reading: a competent reserve-aware operator mostly HOLDS
charge to comply, so the SOC rule rarely binds; at the most reserve-aggressive setting (ρ=0)
the **median ψ_up $0.020 EXCEEDS the Stage 0 perfect-foresight floor $0.015 — validating
Decision 19** (a causal operator cannot dodge the constraint as well as a clairvoyant). As the
deployment cost ρ_k rises, reserves become less attractive, the operator holds less, and
ψ_up → 0. **Named 2A/B2 caveat (clearly visible): the hour-mean MCPC smooths scarcity spikes,
so the ψ_up tail (max <$1.2) is far below Stage 0's $32.75 — interval MCPC would restore it.**

This is the Decision-18 reframe made precise: RTC+B's SOC enforcement is **cheap for a
well-run battery** (it holds charge to comply) — a small regulatory cost consistent with a
profitable fleet, not a large one.

## The DP core gate — PASSED

- **DP↔LP agreement** on a deterministic price: <0.3% at 1–2 h (the core correctness test).
- **Bellman residual ~0**; **μ monotone** in S⁺ for the energy DP (≈1e-11). With reserves the
  A2 power-coupling introduces a small μ-monotonicity violation (~0.4, ~1% of μ scale) because
  the reserve sub-problem is precomputed-and-added rather than solved fully jointly — a named
  approximation; the load-bearing Q2 check is the C1 identity, which passes exactly.
- **Grid convergence** (deterministic) 9.8e-3 → 2.0e-3 as N_S 50→400.
- Relative value iteration via a **backward Gauss-Seidel day-sweep** converges in ~2–11 sweeps.

## What was delivered

| module | what it is |
|---|---|
| `src/dp.py` | periodic post-decision-state DP (§IV.2), grid-aligned actions (§IV.8b), Gauss-Seidel RVI to the 24-periodic fixed point (§IV.9), μ extraction, reserve co-optimisation, verification suite |
| `src/reserves.py` | the reserve LP (A2 value fn of (S⁺, power budget); C1 ψ_up = energy-constraint dual), hour-mean MCPC (B2), ρ_k, and the C1 validation |
| `src/policies.py` | `WalkForwardDPPolicy` (leak-free, per-fold refit, reserve co-opt, ψ_up logging) + `DPCurve` offer-curve execution (§IV.6) |
| `src/stage4_run.py` | leak-free ladder, Q3 duration sweep, §V.26 capture-rate prong, Q2 ψ_up + ρ_k sweep + C1 validation |
| `tests/test_dp.py` | 11 tests: DP↔LP, Bellman, μ-monotone, grid convergence, offer-curve dispatch, DP-policy causality, reserve C1 identity, reserve ψ_up sign, co-opt raises value |

## Remaining refinements (named; not blocking)

1. **Interval MCPC for the ψ_up tail** — B2 hour-mean MCPC understates the scarcity tail
   (the economically important part). The realised interval MCPC would restore it.
2. **Fully-joint reserve concavity** — the A2 precompute-and-add breaks μ-monotonicity
   slightly; a jointly-convex reserve step would restore the §IV.7 guarantee.
3. **State (h,b,z) in the walk-forward policy** — the in-model probe showed +10% for a
   scarcity-regime z, but that was on the in-sample kernel; confirm it walk-forward.
4. **Richer features (NWP) + summer data** — the 17% capture is information-limited; both
   would raise it. Summer needs the ERCOT MCPC archive re-download.
5. **c_deg ∈ [0,60] sensitivity** (§VIII.7) and the pre/post-RTC+B duration natural experiment.

## Key finding that stands — arbitrage is SPIKE-driven

The DP on the smooth diurnal seasonal alone earns $0/day (spread ~$23 ≪ $85 breakeven, §IV.4):
all the value is in the residual/spike dynamics of the kernel, so the kernel tail is the
headline. This explains both why the empirical kernel wins §V.26 (it preserves spike
transitions) and why the walk-forward capture is modest (out-of-sample spike prediction is hard).

## How to run

```
python -m src.dp                 # DP self-test (DP<->LP, grid convergence), no data
python -m src.stage4_run --full  # leak-free ladder + Q3 + §V.26 prong + Q2 ψ_up
python -m pytest                 # 77 tests (66 prior + 11 Stage 4)
```
