# Stage 5 review — adversarial statistician / model-risk lens

**Reviewer mandate:** assume the numbers are wrong until reproduced; audit the CORRECTNESS of the
inference (formula, implementation, interpretation) and whether the honest headline is exactly as
strong/weak as the data support. No source or test files were modified.

## Bottom line

I reproduced **every** headline number in `stage5_notes.md` and `stage5_writeup.md` bit-for-bit
off the cache (sign counts 31/68 & 85/113, p=0.545 & 7.3e-8, MDE $3,746 = 53.7% of the $6,972
traded ceiling, bootstrap CIs, concentration 38%/114%, ψ_up max $40.96, mean-daily-max CI
[$0.68,$2.65]). The pure-stats module is **correct**: the exact two-sided binomial, the
Politis–Romano stationary bootstrap (geometric wrap-around blocks), the concentration
dual-denominator, and the jackknife are all implemented right and the 18 tests pin them against
known-answer synthetics. There are **no blockers** and nothing that manufactures or hides
significance. The honest "not statistically separable from zero" headline is real.

But there are **two interpretive findings that change the character of a conclusion** (not a
formula): (1) the sign test — the mandated headline — is the *least* powerful test against this
study's actual alternative (a few large-magnitude wins), so reporting "coin flip, p=0.55" as the
whole story **understates** the evidence; an exact magnitude-aware companion (paired sign-flip
permutation) gives one-sided p≈0.08. (2) The Q2 "key result" (causal ψ_up max $40.96 > clairvoyant
$32.75) is a max-vs-max of two single scarcity events with no CI, elevated to "the key result" in
the writeup while the notes hedge it correctly — an overclaim. Details, severities, and fixes below.

---

## Findings

### F1 — The sign test understates the evidence; add an exact magnitude-aware companion (MAJOR)

- **What.** The headline is the sign test: 31/68 = 46%, two-sided p=0.545, read in the abstract and
  §2 of the writeup as "a coin flip." That is a correct statement about *win frequency* — but it is
  presented as the verdict on whether the DP has an edge, and the sign test is **structurally blind
  to the exact thing that makes the DP valuable**: magnitude. The DP wins *less often* (46%) but by
  *more* (+$2,020 total, concentration top-5 = 114%). The sign test throws the magnitude away by
  construction, so p=0.55 is guaranteed to look like nothing here regardless of how real the edge is.
- **Where.** `src/stage5_stats.py:47` (sign_test); framed as headline in `reports/stage5_writeup.md:22`,
  `:84-86`, `:102-104` and `reports/stage5_notes.md:66-72`.
- **Why it's wrong/weak (reasoning).** §VIII.5 chose the sign test to avoid the fat-tail failure of
  *bootstrap coverage for the mean*. But that reasoning does **not** force the sign test — it forbids
  a **normal/bootstrap CI on the mean**. The paired **sign-flip randomization (permutation) test** is
  a third option that §VIII.5 never considered: it is EXACT (no normal approximation, so it is immune
  to the very fat-tail problem §VIII.5 cites), it is magnitude-aware, and it is the textbook exact test
  for a paired design (negate D_i ↔ swap which policy is "A" on day i — the sharp null of no per-day
  effect). I ran it on the 140 daily differences: **two-sided p = 0.147, one-sided p = 0.077**
  (20,000 sign-flips, seed 0). Cross-checks: Wilcoxon signed-rank p=0.91 (agrees the *ranks* are a
  coin flip — same magnitude-blindness as the sign test), t-test p=0.133 (agrees with the permutation
  two-sided, as it must asymptotically). So the honest picture is not "coin flip, indistinguishable"
  — it is "**win-frequency slightly favors the MPC (46%), but the magnitude edge favors the DP at a
  marginal one-sided p≈0.08**." Those two facts together ARE the finding (few big wins); reporting only
  p=0.55 tells half of it and invites the reader to conclude "no edge."
- **Fix + why correct.** Add the sign-flip permutation test as a companion to the sign test (keep
  both; they measure different things — frequency vs signed-magnitude). Report two-sided p=0.15 and
  one-sided p=0.08 explicitly, and reframe §2 as "the DP's value is magnitude not frequency, and even
  the magnitude edge is only marginal on this sample" rather than "a coin flip." This is the correct
  fix because the permutation test is exact under the same paired null, needs no distributional
  assumption, and — crucially — **does not manufacture significance** (two-sided still 0.15 > 0.05, so
  the "not separable at 5%" headline SURVIVES). It sharpens the honest story without breaking it.
  (Robustness: with the daily series only weakly dependent — the bootstrap block sweep barely moves —
  a daily sign-flip is adequate; a block-sign-flip is the belt-and-suspenders version.)
- **Severity:** major. **Confidence:** verified (reproduced). **Interview value:** raises-bar — an
  exact permutation test that refines rather than inflates is precisely the model-risk maturity the
  role rewards.

### F2 — The Q2 "key result" (ψ_up max $40.96 > $32.75) is over-elevated (MAJOR)

- **What.** The writeup §3 makes "the causal-operator tail max ($40.96) *exceeds* the Stage 0
  perfect-foresight max ($32.75)" **"The key result"** and puts it in the abstract.
- **Where.** `reports/stage5_writeup.md:16-18`, `:139-143`; notes `reports/stage5_notes.md:138-147`.
- **Why it's weak (reasoning).** I checked the tail composition: only **3 intervals** in the entire
  140-day window exceed $32.75, and they are all in **one scarcity event (2026-03-23**, the $950
  energy day). The second-highest *day* peaks at $32.45 — below the clairvoyant max. So the
  strict-inequality claim rests on a **single day / single event**, has **no CI** (correctly — a max
  has no sampling distribution), and is **ρ-dependent** (ρ=0.05 is a fixed deployment-factor
  assumption; the notes elsewhere show the median validation is ρ-dependent). Comparing two point
  extrema from the same event as a headline is exactly the model-risk pattern the sign-test protocol
  exists to avoid. The notes hedge this correctly ("single-event extreme... reported as such"; §VIII.5a
  effective-sample caveat) — but the **writeup drops the hedge and elevates it to "the key result."**
- **Fix + why correct.** Lead the Q2 headline with the **defensible bounded statistic** — the
  bootstrap 95% CI on the mean daily-max ψ_up, **[$0.68, $2.65]** (a genuine sampling-based interval)
  — and present the $40.96 tail max as a **single-event illustration** of the mechanism (causal caught
  short pays more than a clairvoyant), explicitly flagged as one event and ρ=0.05-dependent. The
  mechanism argument is economically sound and worth keeping; only its billing as "the key result" is
  the overclaim. This aligns the writeup with the (correct) notes.
- **Severity:** major (it is the Q2 headline). **Confidence:** verified. **Interview value:**
  raises-bar (honesty about a fragile extreme is a positive signal, not a negative).

### F3 — Power statement: "normal approx is optimistic" is asserted, and it powers the wrong test (MINOR)

- **What.** `power_statement` reports MDE = $3,746 = 54% of traded ceiling via the normal formula
  $(z_{a/2}+z_{pow}) sd/\sqrt n$, with a docstring claim that under the fat tail "the true MDE is
  somewhat *larger*, so this is an OPTIMISTIC bound."
- **Where.** `src/stage5_stats.py:173-194` (claim at `:182-184`); writeup `:95-99`, notes `:110-116`.
- **Why it's weak (reasoning).** Two issues. (a) The directional claim ("optimistic / true MDE
  larger") is **asserted, not shown**, and under extreme right-skew with effective sample ~5–15 the
  direction is genuinely ambiguous — the normal approximation to the mean-test statistic can distort
  *size* in either direction, so "optimistic" is plausible but unverified. (b) More importantly, this
  is a power calc for the **mean test**, while the **headline is the sign test** — the reader is handed
  a detectability threshold for a test that is not the one being reported (and, per F1, the sign test's
  power against a magnitude alternative is even lower). Also note sd(D)=$113 is computed over all 140
  days *including the 72 exact-zero tie days*, which shrinks sd and makes the MDE smaller (more
  optimistic) — defensible (they are real days) but interacting with the unverified "optimistic" claim.
- **Fix + why correct.** Replace the hand-wave with a **simulation-based power curve for the exact
  test actually used**: shift the observed daily-difference distribution by a candidate effect δ,
  resample days (stationary bootstrap to preserve dependence), run the permutation/sign-flip test, and
  report the smallest δ rejected at 80% power. This gives a defensible number for the real test instead
  of a normal approximation to a different test, and it settles the direction empirically rather than
  by assertion. (Expressing MDE as % of ceiling is itself fine — it is the natural scale-free unit.)
- **Severity:** minor. **Confidence:** verified (the coherence gap); the "optimistic" direction is
  **suspected**. **Interview value:** raises-bar (simulation-based power for the actual test statistic).

### F4 — `report_psi` has dead code and a docstring that misdescribes it (MINOR)

- **What.** `report_psi` computes `med_ci = st.bootstrap_ci(..., np.median)` but **never prints it**;
  the printed median line uses `np.median(...)` directly. The docstring claims the function reports
  "(i) a day-clustered bootstrap CI on the MEDIAN of the binding intervals."
- **Where.** `src/stage5_run.py:286` (computed, unused); docstring `:269-274`; printed at `:287-292`.
- **Why it's wrong (reasoning).** The median of a series that is >90% zeros (ψ_up binds in 6.0% of
  intervals) is exactly 0, and its bootstrap CI is degenerate/[0,0] — so omitting it is the *right*
  call, but then the docstring's promise (i) is false. Separately, had `med_ci` been used it bootstraps
  the **per-interval** series with `block_mean=5` (= 5 intervals = 75 min), which does **not** respect
  the **daily** clustering of scarcity that the same function correctly uses for the mean-daily-max CI
  (`dm_ci`, day-level). So the dead path is also methodologically inconsistent with the live path.
- **Fix + why correct.** Delete `med_ci` and correct the docstring to describe what is actually
  reported (the median as a point statistic; the CI is on the mean daily-max, day-clustered). A
  central-tendency of a mostly-zero heavy-tailed series is not a meaningful target anyway; the
  mean-daily-max is the right day-level object and is already CI'd. Removes a false claim and a
  compute-but-discard.
- **Severity:** minor. **Confidence:** verified. **Interview value:** neutral (cleanliness).

### F5 — Matched-window SOC asymmetry: checked, and it is CONSERVATIVE (MINOR / affirmation)

- **What (mandate Q7).** The DP enters the traded window at SOC 0 (it holds through the 2-month
  warm-up, `s_init=0`, no fitted model), while the MPC has been trading in warm-up and carries its
  SOC across the boundary into day 1 of the matched window.
- **Where.** `src/stage5_run.py:91-99` (dp/mpc both `s_init=0.0`, but the DP's held path keeps SOC≈0
  while the MPC's does not), warm-up definition `:59-65`.
- **Why it does NOT bias the headline (reasoning).** The asymmetry affects only the **first ~1 day** of
  the 140-day matched window: an empty DP cannot discharge into an early-morning spike on boundary day
  1, whereas the MPC might. The direction is therefore **against the DP** — it makes V^DP and the
  option value slightly **conservative (understated)**, not inflated. Over 140 days one boundary day is
  negligible, and it errs in the honest direction. This is the correct residual after the Stage 4
  review's warm-up fix; there is nothing to repair.
- **Fix.** None needed. Add one sentence to the writeup method note stating the boundary condition was
  checked and is conservative — turns a potential reviewer "gotcha" into a credibility point.
- **Severity:** polish. **Confidence:** verified. **Interview value:** neutral (but worth stating).

### F6 — Writeup §1 leads with the inflated +$2,667 option value (MINOR)

- **What.** §1 prose states "That **+$2,667 swing** ... is the **option value of distribution-awareness**"
  and only corrects to the matched-window **$2,020** in the "deflation" paragraph below.
- **Where.** `reports/stage5_writeup.md:58-60` vs `:67-70`; Stage 4 already declared $2,020 THE honest
  number (`reports/stage4_decisions.md:63`, plan §VIII.5 item (ii)).
- **Why it's weak.** A skimming reader takes the bolded $2,667 as the answer; the honest, matched
  figure ($2,020) is the one the Stage-4 review mandated. Leading with the un-matched number
  re-introduces exactly the inflation the matched-window fix removed.
- **Fix.** Lead with $2,020 (matched); mention $2,667 only as the un-matched figure and why it is
  higher. One-line edit; changes emphasis, not substance.
- **Severity:** minor. **Confidence:** verified. **Interview value:** neutral.

### F7 — No automatic block-length rule, though §VIII.5b asks for one (MINOR)

- **What.** §VIII.5b (plan `:932`) specifies "expected block length chosen by an **automatic rule**,
  and plot the CI as a function of block length." The code does the **plot/sweep** (grid 1..40) but the
  block length is **hand-set** (`block_mean=5.0` default; grid literal) with no automatic selector.
- **Where.** `src/stage5_stats.py:71` (default 5.0), `:116` (literal grid).
- **Why it matters (reasoning).** It is a named deliverable that is partially unmet, and an interviewer
  who knows the stationary bootstrap will look for it. It does **not** change any conclusion here — the
  CI straddles zero at every block length 1..40, so the auto-selected length lands inside a stable
  regime — but "we implemented the sweep, and the Politis–White (2004) automatic length selects ~X days,
  inside the stable regime" is strictly stronger than a hand grid.
- **Fix + why correct.** Add Politis–White (2004) automatic block-length selection (available in the
  `arch` package's `optimal_block_length`, or ~15 lines) and report the selected value as the primary,
  with the sweep as the sensitivity. Correct because it replaces an arbitrary constant with the
  literature-standard data-driven choice the plan asked for.
- **Severity:** minor. **Confidence:** verified. **Interview value:** raises-bar (named technique).

---

## Points I checked and found CORRECT (credit where due — not padding)

- **Exact two-sided binomial** (`sign_test`): matches `scipy.stats.binomtest` on the non-tied count;
  p=0.545 / 7.3e-8 / 0.801 all reproduce. Correct.
- **Dropping the 72 tied days** is standard and **unbiased**: the ties are genuine D=0 (both policies
  idle), carry no directional information, and the exact binomial correctly conditions on n_eff=68.
  The cost is power (halved n), which is disclosed. No tie-definition bias — tol=1e-6 only removes
  sub-cent numerical noise, not economically real small wins.
- **Stationary bootstrap** (`stationary_bootstrap_samples`): geometric block lengths with
  `p=1/block_mean`, wrap-around modulo N, correct total length N — a faithful Politis–Romano (1994)
  implementation. Seeded determinism is unit-tested (`test_bootstrap_is_seeded_deterministic`).
- **Concentration dual denominator** (mandate Q5): the "top-5 = 114% of net" figure is **not**
  misleading because the module and notes always report the **gross** companion (83% of up-day P&L)
  and the net total alongside. The 114% is mathematically valid (net < gross when down-days exist) and
  correctly flagged as the reason the mean is untrustworthy. Handled well; no change needed.
- **Multiple comparisons** (mandate Q6): **no** multiplicity control is required for the headline. The
  additional tests (DP-vs-naive, §V.26 kernel gap, ψ_up) are **distinct pre-registered questions**, not
  a fishing family on one hypothesis; and the 6-row block sweep is one statistic under six nuisance
  settings (a **sensitivity**, not six tests). Applying Bonferroni here would be a category error.
- **Effective-sample honesty** (mandate Q4): the "70 binding days at the loose tolerance, but effective
  sample ~15 because top-5 = 68% of the mass" caveat (`notes:145-147`) is statistically honest and
  matches §VIII.5a. The mean-daily-max CI [$0.68,$2.65] is the meaningful ψ_up interval; the all-interval
  median (=0) is correctly reported as ~0, not spun.
- **Jackknife** sign-fragility logic and range [$1,222,$2,390] reproduce; "sign not fragile" is correct.

---

## Highest-value upgrade (single)

**Add the exact paired sign-flip permutation test as the magnitude-aware companion to the sign test
(F1).** It is the one change that both (a) makes the inference *more correct* — it is the exact paired
test that §VIII.5's own fat-tail logic actually points to, superior to the normal-approx power calc and
to a percentile-bootstrap mean CI — and (b) *sharpens the honest headline without inflating it*: the DP
edge moves from "coin flip p=0.55" to "marginal, one-sided p≈0.08, two-sided 0.15 — still not separable
at 5%." For a Base Power Markets interviewer, choosing the **right exact test for a magnitude-concentrated
alternative**, and using it to *refine down* rather than star-hunt, is a stronger signal than any point
estimate: it demonstrates you understand *why* the sign test is low-power here and fixed it without
cheating. Secondary rigor upgrades, in order: F3 (simulation-based power for the actual test), F7
(Politis–White automatic block length), and — if a level/edge CI is wanted with better small-sample
coverage than the percentile interval under this skew — a **BCa** bootstrap CI (bias-corrected
accelerated); note BCa will shift but still straddle zero, so it does not change the conclusion.

## What NOT to do (guarding the honest headline)

Do not replace the sign test, drop the tied days differently to raise the win rate, switch to a
one-sided-only headline, or swap in any interval that no longer straddles zero. The straddle-zero CI and
the ~46% sign frequency are the **correct** §VIII.5 results; every proposed fix above either affirms
them or refines their *interpretation*. None manufactures significance.
