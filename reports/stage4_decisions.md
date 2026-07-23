# Stage 4 — decisions, rationale, and self-critique (durable record)

The complete record of what was built for Stage 4 (the periodic dynamic program), why,
and the known problems — written so a fresh reviewer (or a future session) has full
context. Companion to `reports/stage4_notes.md` (results) and the plan §IV / Part XIV.

## Decisions of record (Stage 4), with rationale

1. **Periodic average-reward DP, post-decision state, grid-aligned actions** (§IV.2/8b/9).
   Rationale: eliminates the terminal-value problem (self-consistent across the day
   boundary), exact on the SOC grid (no interpolation → concavity/μ-monotonicity hold),
   ~2 orders of magnitude cheaper than a finite-horizon pass. Solved by **backward
   Gauss-Seidel day-sweep** (converges in ~2–11 sweeps; naive synchronous VI did not
   converge in thousands — the deterministic cyclic price mixes too slowly).

2. **State = (h, b): time-of-day × deseasonalised-residual bin** (decision 3C: start (h,b),
   test (h,b,z)). The kernel is the Stage-3 hour-indexed empirical count matrix on the
   residual. Reward reconstructs price = seasonal(h) + residual-bin-centre.
   Rationale: parsimony + sample size (raw-count support is already thin); §VIII.7 test to
   decide whether z (a scarcity regime) earns its place. In-model probe showed +10% for z,
   but on the in-sample kernel — a walk-forward confirmation is an open refinement.

3. **Q1 — WALK-FORWARD kernel (the integrity fix).** The kernel/seasonal/edges/reserve
   prices/DP solve are ALL re-fit online per calendar month on strictly-prior data
   (`WalkForwardDPPolicy`), like the Stage-3 LearnedForecaster. Rationale: §VIII.3 forbids
   estimation-sample leakage; the first cut used a full-window IN-SAMPLE kernel that
   inflated V^DP ~2.4× (V^DP 40%→17% at 2h once fixed). Warm-up (first 2 months): the DP
   HOLDS (no model yet) — conservative and, since the naive-seasonal MPC warm-up mostly
   lost money, not an unfair handicap.

4. **Q2 — reserve CO-OPTIMISATION, options A2/B2/C1.**
   - *A2*: the reserve value is a function of BOTH post-decision charge S⁺ (energy budget,
     via EH-up) AND the power budget p̄−(d−c) (which the energy action sets). Rationale:
     the honest power accounting; A1 (S⁺-only) over-states reserve value when also
     dispatching energy. **Known cost:** the sub-problem is precomputed-and-added per action
     (not solved fully jointly), which breaks the §IV.7 joint concavity slightly → a small
     μ-monotonicity violation (~1% of μ). Fully-joint concavity is a named refinement.
   - *B2*: reserves priced at the hour-EXPECTED MCPC; deployment charged as c_deg·ρ_k·τ_k
     with ρ_k a CONSTANT swept as a sensitivity. Rationale: the full state-dependent
     deployment/forgone-energy term needs dispatch telemetry (out of scope, Decision 17).
     **Known cost:** hour-mean MCPC smooths scarcity spikes → the ψ_up TAIL is understated
     (max <$1.2 vs Stage 0 $32.75). Interval MCPC is a named refinement.
   - *C1*: ψ_up = the reserve LP's DUAL on the EH-up (energy) constraint at the co-optimised
     SOC. Rationale: matches the (AS) derivation (§IV.10). **Validated**: ψ_up equals the
     finite-difference of the reserve value (the §IV.11-style multiplier check), 5/5 points.

5. **The DP is co-optimised for reserves but V^DP is reported ENERGY-ONLY** for ladder
   comparability with the energy-only ceiling/MPC. Reserves change the POLICY (it holds
   more charge); the reserve revenue is not added to V^DP. ψ_up is the separate Q2 output.

6. **Adopt the EMPIRICAL kernel** (§V.26 capture-rate prong): empirical 17% > learned 15%
   realised walk-forward capture. Rationale: the learned model's Stage-3 CRPS win did not
   translate to better decisions; the nonparametric matrix preserves the decision-relevant
   spike transitions. This conclusion SURVIVED the walk-forward correction.

7. **Data window = 198 days (Dec–Jun)**; the refresh to ~228 days was a no-op (cached MCPC
   bundle caps at Jun-20; extending needs re-downloading ERCOT's NP6-796-ER archive). Summer
   top-up (Decision B2) is gated on that fetch.

## Corrected leak-free headline (2h, energy-only)

Ladder: ceiling $13,206 ≥ clair MPC $12,847 (97%) ≥ **V^DP $2,195 (17%)** ≥ learned MPC
−$303 ≥ naive −$3,453 ≥ floor −$5,267. Option value (V^DP − learned MPC) = **+$2,498**;
value of information = $11,011. Q3 capture −5%(0.5h)→~22% plateau(≥2h), concave. Q2: ρ=0
median ψ_up $0.020 > Stage 0 floor $0.015 (Decision 19), →0 as ρ rises.

## Self-critique — known problems (independent of any agent review)

Recorded so the agents' findings can be cross-checked, and nothing is hidden:

- **17% capture is at the low end** of the "50–80% typical" band (§VIII.4). Not a bug (all
  gates pass) — information-limited: price-only kernel (no NWP), thin winter/spring window,
  walk-forward. But 17% is close to the "~20% = check for a bug/misconfigured cost" warning,
  so it deserves an independent bug hunt.
- **μ-monotonicity violated ~1%** with reserves (A2 precompute-and-add; not solved jointly).
- **ψ_up tail understated** by B2 hour-mean MCPC (max <$1.2 vs Stage 0 $32.75).
- **Representative-weekday/rep-month seasonal** in the DP solve vs actual all-days prices in
  execution — a mismatch argued benign (arbitrage is spike-driven) but not quantified.
- **Solve/execute state-convention**: the DP is solved with b = current-interval residual;
  execution uses b = last-observed bin for the continuation ("certainty-equivalent-style").
  Not proven optimal under the mismatch.
- **SOC grid snapping** in execution (round(soc/ΔS)) — unquantified discretisation error.
- **z-augmentation (+10%)** judged in-model on the in-sample kernel — not confirmed
  walk-forward on the realised metric (more states mechanically raise in-model value).
- **No confidence intervals / statistics** on V^DP or ψ_up (that is Stage 5).
- **DP↔LP agreement degrades to ~2% at 4h** (grid discretisation grows with duration).
- **§IV.11 duration identity** is validated for the RESERVE LP ψ_up (C1), but the full DP-level
  dV/dE_max = Σ(λ̄+ψ_dn) identity is not separately run (the oracle validates the energy-side).

## Three-agent review — verdict and resolutions (applied)

A three-agent adversarial review + synthesizer returned **GO WITH FIXES, no blockers** (the
2h leak-free headline is trustworthy; DP core formally correct — reserve dual sign/units right,
no factor-of-4; leak-free confirmed by an independent scramble test). Fixes APPLIED:
Q3 grid-scaling (ΔS-constant); dual-denominator capture (18% full / 34% matched) + a bootstrap
95% CI that **straddles zero** ($[-263, 5666]$ → edge not separable from 0, the honest framing);
§V.26 downgraded to "empirical ≈ learned" (sign flips at n_bins=10); Q2 **interval-MCPC tail at
the executed SOC** (max \$40.96 > Stage 0 \$32.75 → Decision 19 confirmed in the tail); pooled
seasonal; K-step over-persistence fix; reserve E-grid refined near 0; do-nothing floor row;
WalkForwardDPPolicy scramble test; z walk-forward test (only +\$120 realised, not the +10%
in-model → $(h,b)$ stands). Statistical items (sign test, matched-window MPC, concentration
decomposition, block-length sensitivity) recorded in the plan's Stage 5 section.

**Cross-check (my self-critique vs the agents):** the agents caught two I got wrong — the
warm-up *direction* (I noted it but concluded backwards) and the §V.26 fragility (I wrote
"survives"). I caught two they missed — the rep-weekday seasonal (now fixed: pooled) and the
z-augmentation being in-sample (now tested walk-forward). No item went unaddressed.

## Refinements (still open, named, non-blocking)

Interval MCPC for the ψ_up tail; fully-joint reserve concavity; (h,b,z) walk-forward; NWP
features + summer data; c_deg∈[0,60] sensitivity; pre/post-RTC+B duration natural experiment;
statistics/CIs (Stage 5).
