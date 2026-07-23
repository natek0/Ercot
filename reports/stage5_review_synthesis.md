# Stage 5 review — SYNTHESIS (4th reviewer)

**Role:** reconcile the three Stage 5 reviews (A = adversarial statistician / model-risk;
B = battery-desk quant / hiring-signal; C = staff engineer / TDD-CI) into one prioritized,
deduplicated action list, resolving every genuine conflict explicitly.

**Reproduction stance.** I re-ran the load-bearing numbers off the cache rather than trusting the
reports. All three reviewers independently reproduced the headline numbers bit-for-bit; I confirmed
the *contested* ones myself (below). **There are no correctness blockers and nothing in Stage 5
manufactures or hides significance.** The "not statistically separable from zero" headline is the
correct §VIII.5 result. Every fix below either affirms that headline or sharpens its
*interpretation*; I reject anything that would star-hunt.

## What I verified myself (not just trusted)

| claim | reviewer(s) | my check | verdict |
|---|---|---|---|
| paired sign-flip permutation test: two-sided p≈0.15, one-sided p≈0.077 | A F1 | ran 20k sign-flips, seed 0: **two-sided 0.150, one-sided 0.077**; t-test 0.133; Wilcoxon 0.908 | **confirmed** |
| ψ_up $40.96 rests on ONE event | A F2, B MAJOR 3 | **only 3 intervals in 140 days exceed $32.75, all on 2026-03-23**; 2nd-highest *day* peaks at **$32.45 (< $32.75)** | **confirmed** |
| cached report is ~30 s, not "instant" | C F2 | timed: **30.19 s** wall off cache | **confirmed** |
| ladder comparator bars are hardcoded constants | C F1 | `MPC_2H = {ceiling:13206, clair:12847, learned:-303, naive:-3453, floor:-5267}` imported into `fig_ladder`; `build_cache` computes `r_ml/r_mn/r_fl.profit` and discards them | **confirmed** |
| test-count drift | C F7 | suite = **96 passed**, `tests/test_stage5.py` = **18**; writeup/notes say **95 / 17** | **confirmed** |
| figures untracked | C F3 | `git ls-files reports/figures/` empty; `git status` shows `?? reports/figures/`; not gitignored | **confirmed** |

Everything the three agents claimed and I spot-checked held. Nothing is "unverified."

---

## 1. Deduplicated finding clusters (who raised what)

| # | cluster | A | B | C | severity (synth) |
|---|---|---|---|---|---|
| C1 | ψ_up "$40.96 > $32.75" over-elevated (single event, cross-window, cross-method) | F2 | MAJOR 3 | — | **must-fix (wording)** |
| C2 | option value: inflated $2,667 vs matched $2,020 (table + §1 prose) | F6 | MAJOR 1 | (F1 related) | **must-fix (wording)** |
| C3 | DP capture 18%-full vs 34%-traded — inconsistent with matched comparators | — | MAJOR 2 | — | **must-fix (consistency)** — *the brief's explicit conflict* |
| C4 | power statement is a mean t-test MDE; headline is the sign test; sd over 72 ties; "optimistic" asserted | F3 | MINOR 4 | — | high-value |
| C5 | dead `med_ci` + docstring describes output not produced | F4 | — | F6 | **must-fix (trivial)** |
| C6 | `fig_ladder` hardcoded constants; full-window profits computed-and-discarded | — | (MAJOR 1) | F1 | **must-fix (repro)** |
| C7 | figures untracked → broken images on a fresh clone / GitHub | — | — | F3 | **must-fix (repro)** |
| C8 | bootstrap CI never tested for *coverage* (test asserts only `lo>0`) | — | — | F4 | high-value |
| C9 | `_traded_mask`/`_daily_pnl` (the leak-free/matched contract) untested | — | — | F5 | high-value |
| C10 | pure-Python triple-loop bootstrap → 30 s; vectorize + re-pin golden | — | — | F2 | high-value |
| C11 | no automatic block-length rule (§VIII.5b asks for one) | F7 | — | — | high-value |
| C12 | add exact magnitude-aware permutation (sign-flip) companion to the sign test | F1 | — | — | high-value |
| C13 | value-attribution paragraph: 97%-free + DP>MPC + CRPS-didn't-translate ⇒ bottleneck is *exogenous* NWP signal | — | Upgrade A, MINOR 5 | — | high-value |
| C14 | test-count drift 95→96 / 17→18; tautological block-shape test | — | — | F7 | **must-fix (count)** + high-value (AR(1) test) |
| C15 | §2 leads with the null; reorder to lead with what's established | — | MINOR 6 | — | optional |
| C16 | concentration denominator (114% net vs 83% gross) consistency in body+figure | — | POLISH 7 | — | optional |
| C17 | abstract lacks a one-line operator "so what" | — | POLISH 7 | — | optional |
| C18 | headless backend not forced; `bootstrap_ci` NaN on empty | — | — | F8 | optional |
| C19 | magic numbers (ρ=0.05, tol, 32.75) → named constants w/ provenance | — | — | F9 | optional |
| C20 | 60-second verbal walkthrough box | — | Upgrade B | — | optional |
| C21 | limitations → roadmap-with-expected-direction | — | Upgrade C | — | optional |
| C22 | SOC boundary asymmetry checked, is conservative — add one sentence | F5 | — | — | optional |
| C23 | wire the heavy `build_cache→report` path into CI via a synthetic panel | — | — | eng-upgrade 4 | high-value |

---

## 2. Conflicts adjudicated explicitly

### CONFLICT 1 — DP capture: lead with 34% of the *traded* ceiling (B MAJOR 2) or hold the honest 18% of the *full* ceiling (A's lens)? *(the brief's named conflict)*

**B's position.** Every *comparator* is recomputed on the matched traded window (learned MPC
−$303→+$344). The DP's capture denominator is *not*: 18% uses the full-window ceiling ($2,364/$13,206),
which includes ~2 months of arbitrage the DP could not have done (it had no fitted model yet). Applying
one warm-up convention to numerator and denominator gives **34%** ($2,364/$6,972). Using the pessimistic
denominator for the DP while giving comparators the optimistic matched treatment is inconsistent and
undersells the operating-window efficiency ~2×.

**A's (implicit) position.** A's whole lens is that the honest read is "18% of full, low end of the
50–80% band, and the edge is not separable" — i.e. do not let a denominator choice flatter the number.

**My call: report BOTH, traded-first, and never drop the 18%.** B is *correct on internal consistency*
— it is genuinely inconsistent to recompute the MPC on the matched window and then charge the DP against
the full-window ceiling; the numerator and denominator must share one warm-up convention, and against
the matched comparators the traded ceiling is the right denominator. **But 34% presented *alone* is
mildly self-flattering**, because the traded window is exactly where the DP's value lives (every scarcity
spike is Feb–Jun) and it excludes the warm-up the DP sat out by fiat. The honest resolution is the one
`stage5_run` *already prints* — "**34% of the traded ceiling (the window it operates on), 18% of the full
ceiling (including the 2-month cold start)**" — surfaced in the abstract and the ladder table, not just
stdout. That is strictly *more* honest than the current writeup (which shows only 18%) and than B's
proposal (which leads 34%): both numbers stay visible, and the pessimist's number is never hidden.
**This does not manufacture a better result — it adds the pessimistic context, so it passes the
honest-framing test.**

**Synthesizer-originated caveat (mark as mine):** three ratios are floating and an interviewer *will*
conflate them — DP capture-of-traded **34%**, capture-of-full **18%**, and the option-value *edge*
$2,020/$6,972 = **29%** (the number the abstract's power sentence compares to 54%). The writeup must
disambiguate "capture" (DP level vs ceiling) from "edge" (DP − MPC vs ceiling) in one sentence, or the
34/29/18 spread reads as an error.

### CONFLICT 2 — ψ_up fix: demote to the bounded CI (A) or window/method-matched re-extraction (B)? *(known convergence #1)*

Not actually opposed — **complementary, and both correct.** A wants the *billing* fixed now: lead Q2 with
the defensible bounded statistic (bootstrap CI on mean daily-max ψ_up, **[$0.68, $2.65]**), present
$40.96 as a single-event illustration, and drop "the key result." B wants the *comparison* fixed:
$40.96 (causal, 140-day traded, reserve-LP dual at executed SOC, ρ=0.05) vs $32.75 (clairvoyant,
198-day full, perfect-foresight energy+contingency LP dual) crosses window *and* method *and* sample, so
recompute the clairvoyant ψ_up on the same 140 days through the same `reserve_lp` call.

**My call:** do A's demotion as a **must-fix** (it is the Q2 *headline* and is currently an overclaim the
notes themselves hedge — I verified the strict inequality rests on 3 intervals of one day, with the
2nd-highest day *below* $32.75). Do B's matched re-extraction as a **high-value upgrade** — it is the
genuinely stronger result and cheap (feed the perfect-foresight SOC path through the identical
`reserves.reserve_lp`). **Critical honesty note:** even after a window+method-matched re-extraction the
inequality still rests on *one event*, so the writeup may state a *directional* "the causal tail reaches
~$41/MWh, at or above the window/method-matched clairvoyant on the one Mar-23 scarcity event" — never a
clean ">$32.75" law. The *mechanism* (a causal operator caught short pays more than a clairvoyant who
dodged) is economically sound and stays; only its billing as "the key result" and the un-matched
comparison are the errors.

### CONFLICT 3 — power statement: simulation-based for the actual test (A) or analytic sign-test power / relabel (B)? *(known convergence #3)*

Both flag the same incoherence: the reported MDE is for the **mean t-test**, the headline is the **sign
test**. A wants a simulation-based power curve for the actual test; B offers a cheaper analytic
sign-test power or an explicit "secondary" label. **My call: replace the normal-approx MDE with a
simulation-based power curve, targeting the PERMUTATION test** (the magnitude-aware companion from C12),
keeping the mean-MDE as a labelled *secondary*. Reasoning: the study's real alternative is "a few
large-magnitude wins," so the sign test's own power against it is *even lower* (A) and a sign-test power
statement would be misleadingly pessimistic about the wrong estimand; the permutation test is the one
whose alternative matches the design, so its power is the honest detectability number. Simulation also
**settles the asserted "optimistic direction" empirically** instead of by hand-wave, and fixes A's
sub-point that sd(D) is taken over the 72 tie-days (defensible — they are real $0 days — but state it).
No p-value changes; honest framing intact.

### CONFLICT 4 — option-value table fix: A (prose) vs B (table)? *(known convergence #2)*

No disagreement on substance; they patch different surfaces. A: §1 prose leads with the inflated
**+$2,667** and only corrects to **$2,020** two paragraphs down. B: the hero *table* stacks DP $2,364
directly above learned MPC −$303, inviting the $2,667 read, while the matched +$344 / $2,020 are exiled
to prose and a caption. **Canonical fix = do both:** add a "matched traded window" column to the §1 table
(learned MPC −$303 full / **+$344** matched; put **$2,020** option value *in the table*) **and** lead the
§1 prose with $2,020, mentioning $2,667 only as the un-matched figure and why it is higher. This folds
into C6 (make the table data-driven so the numbers can't drift).

**No genuine conflict exists on the statistics themselves** — all three agents agree the pure-stats layer
is correct, the CI-straddles-zero is the right answer, and there are no blockers. The disagreements are
purely about *which honest number leads* and *how far to push the ψ_up/power fixes*.

---

## 3. Prioritized action list

Ranked by (correctness/repro severity) × (interview leverage for the Base Power Markets role). Each item:
what, why, who raised it, effort (S/M/L), and honest-framing risk.

### BUCKET A — MUST-FIX (correctness / reproducibility / broken-on-clone / overclaim the notes disown)

**A1 — Make `fig_ladder` and the §1 table data-driven; stop importing hardcoded `MPC_2H`.** *(C F1; folds
B MAJOR 1/Upgrade D)* `build_cache` already computes `r_ml/r_mn/r_fl.profit` and throws them away, while
the figure re-imports a frozen dict from `stage4_run`. The writeup's "one command regenerates every
number and figure" is *literally false* for the ladder's comparator bars — a `--rebuild` on shifted data
leaves them stale and silent. Stash the full-window profits into the meta parquet and read them in
`fig_ladder`; label the clairvoyant-MPC $12,847 as the one genuine cited Stage-4 constant (no clairvoyant
backtest runs in Stage 5). **Effort: S. Risk: none** (removes hidden constants — pure credibility gain).

**A2 — Commit the six figure PNGs.** *(C F3)* They are the deliverable an interviewer sees; the writeup
hard-links all six and they are untracked and not gitignored, so a fresh clone renders broken images
until someone re-ingests from the API (~8 min + credentials). Commit the rendered artifact, keep
`data/raw/` gitignored — the standard split. **Effort: S. Risk: none.**

**A3 — Demote the ψ_up "$40.96 > $32.75 = the key result" claim.** *(A F2 + B MAJOR 3)* Verified: the
strict inequality rests on **3 intervals of one day (2026-03-23)**; the 2nd-highest day is **$32.45,
below the clairvoyant max**. Lead Q2 with the bounded, sampling-based statistic — bootstrap CI on mean
daily-max ψ_up **[$0.68, $2.65]** — and present $40.96 as a **single-event, ρ=0.05-dependent
illustration** of the mechanism, with the window/method caveat on Fig 6. Keep the economic mechanism.
**Effort: S. Risk: none — removes an unsupported inequality from the headline (the notes already hedge
it; this aligns the writeup to the notes).**

**A4 — Lead the option value with the matched $2,020, not $2,667; put the matched numbers in the §1
table.** *(A F6 + B MAJOR 1)* Reintroducing the un-matched $2,667 as the bolded headline re-inflates
exactly what the Stage 4 review corrected. Add a "matched traded window" column (learned −$303 full /
+$344 matched; option value $2,020 in the table). **Effort: S. Risk: none.**

**A5 — Report DP capture as "34% of traded / 18% of full," both visible, traded-first.** *(B MAJOR 2;
adjudicated Conflict 1)* One warm-up convention for numerator and denominator, matching the comparators;
the pessimistic 18% stays visible; disambiguate capture-vs-edge (my synthesizer caveat). **Effort: S.
Risk: none — adds the pessimistic context rather than hiding it.**

**A6 — Delete dead `med_ci`; fix the `report_psi` docstring to describe what it actually reports.**
*(A F4 + C F6)* The docstring promises "(i) a day-clustered bootstrap CI on the median," which is never
printed and, had it been, would be interval-level (not day-clustered) on a ~94%-zero series (median 0).
Dead code that also runs a wasted 5,000-resample bootstrap each report. **Effort: S. Risk: none.**

**A7 — Fix the test-count drift 95→96 and 17→18 in writeup + notes.** *(C F7)* A factual error in the
reproducibility section of a paper whose pitch is "every number is checked." **Effort: S. Risk: none.**

*(A is deliberately small — 7 items, all S, none touching the statistics kernel or manufacturing
significance.)*

### BUCKET B — HIGH-VALUE UPGRADES (raise the interview/statistical bar)

**B1 — Add the exact paired sign-flip permutation test as the magnitude-aware companion to the sign
test.** *(A F1)* **Top statistical-credibility upgrade.** Verified: two-sided p=0.150, one-sided
p=0.077. It is the exact paired test §VIII.5's own fat-tail logic points to (immune to the normal-approx
problem it cites), and it *sharpens the honest story*: the DP's edge is **magnitude not frequency**
(wins 46% of days but by more), marginal at one-sided p≈0.08, **still not separable at 5%** (two-sided
0.15). Keep the sign test *and* Wilcoxon (I confirmed Wilcoxon 0.91 — it agrees the *ranks* are a coin
flip, which is *why* you need the magnitude-aware test, not the rank-based one). **Effort: S. Risk:
none — refines down, does not inflate.**

**B2 — The value-attribution / exogenous-signal paragraph.** *(B Upgrade A + MINOR 5)* **Top
interview-leverage upgrade.** Synthesize three results the study already has: (i) clairvoyant MPC = 97%
⇒ execution is free; (ii) DP > learned MPC ⇒ distribution-awareness pays; (iii) §V.26 learned ≈
empirical ⇒ a *sharper price distribution does not help*. Conclusion: **the binding constraint is
exogenous information (weather/load/wind/solar), not execution, not forecast sharpness, not the
optimizer** — which *prescribes the next dollar* (NWP features) with evidence. This also resolves the
mild §1↔§5 tension (MINOR 5: say "information," specifically *exogenous*, not "the forecast"). Converts
an honest null into a demonstration of senior judgment. **No new computation. Effort: S. Risk: none.**

**B3 — Vectorize the stationary bootstrap; re-pin the seeded golden output in a test.** *(C F2)* Turns a
30 s interpreted triple-loop into a sub-second NumPy kernel (build the `n_boot×N` index matrix from
geometric block-breaks + cumsum offset). This is the role's exact triad — optimization + statistics +
TDD — in one change, and re-pinning the seeded output *is* the correctness proof. **Note:** vectorizing
changes the RNG draw order, so the exact CI endpoints shift (conclusions do not — the CI still straddles
zero at every block length); re-pin golden values and state the seed-semantics change. **Effort: M.
Risk: none — endpoints move within noise, straddle-zero survives.**

**B4 — Add a Monte-Carlo *coverage* test for the bootstrap CI.** *(C F4)* The current
`test_bootstrap_ci_covers_mean_of_known_normal` asserts only `lo>0` — a direction check, not coverage.
Draw M≈300 datasets from a known DGP (i.i.d. Normal *and* an AR(1) for dependence), build the 95% CI
each time, assert empirical coverage in a binomial band [0.90, 0.985]. This validates the one property
the entire paper rests on. **Effort: M. Risk: none.**

**B5 — Unit-test the leak-free/matched contract: `_traded_mask` + `_daily_pnl`.** *(C F5)* Every headline
flows through these two untested functions, and they *are* the Stage-4 matched-window fix. Synthetic
4-month panel + fake log: assert the mask drops exactly the first two months, `_daily_pnl` returns one
row per traded day with the right sum, and a short/reordered log is caught; add `assert len(log) ==
mask.size`. Testing the leak boundary — not just the pure kernel — is what "leak-free walk-forward,
tested" actually means. **Effort: M. Risk: none.**

**B6 — Simulation-based power curve for the permutation test; demote the mean-MDE to secondary.**
*(A F3 + B MINOR 4; adjudicated Conflict 3)* Shift the observed daily-difference distribution by δ,
resample days (stationary bootstrap to preserve dependence), run the permutation test, report the
smallest δ rejected at 80% power. Gives detectability for the test that *leads* and settles the
"optimistic direction" empirically. **Effort: M. Risk: none.**

**B7 — Window+method-matched clairvoyant ψ_up re-extraction.** *(B MAJOR 3a)* Feed the perfect-foresight
SOC path through the identical `reserve_lp` on the same 140 days, so the causal-vs-clairvoyant ψ_up
comparison is method- and window-matched. Makes the directional claim as airtight as a one-event result
can be. **Effort: M. Risk: none — but keep the claim *directional* (still one event, per A3).**

**B8 — Politis–White (2004) automatic block-length selection.** *(A F7)* §VIII.5b names it; the code does
the sweep but hand-sets `block_mean=5`. Report the auto-selected length as primary, sweep as sensitivity
("selects ~X days, inside the stable regime where the CI straddles zero at every length"). `arch`'s
`optimal_block_length` or ~15 lines. **Effort: S. Risk: none.**

**B9 — Strengthen the tautological block-shape test into an AR(1) width-monotonicity test + wire a
synthetic heavy-path CI smoke.** *(C F7 + eng-upgrade 4)* Assert the 20-day-block CI is wider than the
1-day CI on an AR(1) series — the entire justification for the stationary bootstrap. Add a tiny
`build_cache(synthetic_panel)→report` end-to-end run to CI (the integration seam currently has zero
coverage because it needs the real panel). **Effort: M. Risk: none.**

### BUCKET C — OPTIONAL / POLISH

- **C-a.** Reorder §2 to lead with the established claim (beats naive 3:1, p<0.001; spike-concentrated)
  then bound it, so a skimmer doesn't retain "not separable = doesn't work." *(B MINOR 6)* — S.
- **C-b.** Make the concentration denominator consistent in body + figure (114% net vs 83% gross
  side-by-side, not one in each). *(B POLISH 7)* — S.
- **C-c.** Add a one-line operator "so what" to the abstract. *(B POLISH 7)* — S.
- **C-d.** Force `mpl.use("Agg")` in `figures`; guard `bootstrap_ci` for empty input. *(C F8)* — S.
- **C-e.** Promote ρ=0.05, the 1%-of-median tolerance, and 32.75 to named constants citing their
  decision of record. *(C F9)* — S.
- **C-f.** 60-second verbal walkthrough box. *(B Upgrade B)* — S.
- **C-g.** Reframe limitations as a roadmap with expected direction (NWP↑, summer ψ_up↑, fleet fixes
  the thin-sample power). *(B Upgrade C)* — S.
- **C-h.** One sentence noting the SOC boundary asymmetry was checked and is *conservative* (against the
  DP). *(A F5)* — S. Turns a reviewer gotcha into a credibility point.

---

## 4. Guardrails — what NOT to do (all three agents agree)

Do not replace the sign test, drop tied days differently to lift the win rate, switch to a one-sided-only
headline, or swap in any interval that no longer straddles zero. The straddle-zero CI, the ~46% sign
frequency, and the 114%/net concentration are the **correct** §VIII.5 results. Every fix above affirms or
refines them; none manufactures significance. The permutation companion (B1) and the matched capture
(A5) *look* like they might flatter — they do not: B1 stays > 0.05 two-sided, and A5 keeps the pessimistic
18% in full view.

---

## 5. The two closing single-change picks

**The ONE change that most increases value to an interviewer: B2 — the value-attribution /
exogenous-signal paragraph.** It costs no computation, and it converts the study's honest null into its
single most hireable sentence: *"execution is free (97%), distribution-awareness pays (DP > MPC), but a
sharper price model doesn't help (§V.26), so the binding constraint is exogenous NWP signal — and that's
where the next dollar goes."* A candidate who can look at a stack of results and name precisely which
lever moves the P&L is exactly the "sequential-decision + simulation-validation + judgment" signal the
Base Power Markets role rewards.

**The ONE change that most increases statistical credibility: B1 — the exact paired sign-flip permutation
test.** It is the magnitude-aware exact test §VIII.5's own logic points to, it fixes the sign test's
structural blindness to the very thing that makes the DP valuable (magnitude), and it refines the
headline *down* honestly (one-sided p≈0.077, two-sided 0.15 — still not separable at 5%). Choosing the
right exact test for a magnitude-concentrated alternative, and using it to refine rather than star-hunt,
is the model-risk maturity the role prizes.

**Do they conflict? No — they are complementary and cheap, so do both.** B1 is ~20 lines + a re-pin;
B2 is prose over existing numbers. **Sequence B1 first**, because it produces a fact (the DP's edge is
magnitude, marginal at p≈0.08) that B2's paragraph should then cite — the permutation result is the
quantitative backbone of the "distribution-awareness pays but isn't separable" sentence. Together they
turn the honest null from an apparent weakness into the two strongest signals in the deliverable: rigor
(B1) and judgment (B2).
