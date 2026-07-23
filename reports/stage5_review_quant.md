# Stage 5 review — quant / desk lens

**Reviewer role:** an ERCOT battery-desk quant who is *also* the Base Power Markets interviewer
reading this as the candidate's portfolio piece. Question I am answering: are the economics
defensible, and does this artifact make me want to hire the author?

**Verification status.** I read `reports/stage5_writeup.md`, `reports/stage5_notes.md`,
`src/stage5_stats.py`, `src/stage5_run.py`, `src/figures.py`, `tests/test_stage5.py`, plan
§VIII.5/§VIII.5a, and Decisions 11/17/19/20. I ran the suite off the cache
(`python -m src.stage5_run`) — **every headline number reproduces bit-for-bit** — and
`pytest tests/test_stage5.py` (**18 passed**). I did not run `--rebuild` (the leak-free discipline
is validated in Stage 4; Stage 5 only consumes the cached daily series and computes pure stats,
which I re-derived by hand where it mattered).

**Bottom line.** The statistics are *correct and honestly reported* — the CI straddling zero is the
right §VIII.5 answer, not a defect, and the code does not manufacture significance anywhere. The
inference module is clean, pure, seeded, and well-tested. My findings are **not** about statistical
errors; they are about **economic framing that either undersells the work or invites an
apples-to-oranges read a domain expert will catch in ten seconds.** There are no blockers. The
single highest-leverage addition is a *value-attribution paragraph* that converts the honest null
into evidence of senior judgment (Upgrade A).

---

## Findings

### Blockers
None. I looked hard for a leak, a sign error, or a manufactured-significance move and found none.
The pure-stats layer is correct; the leak-free discipline is inherited from Stage 4 and the
matched-window recompute (the Stage 4 review's key fix) is faithfully implemented in
`stage5_run._traded_mask` / `_daily_pnl`.

---

### MAJOR 1 — The hero table encodes the *inflated* DP-vs-MPC gap; the honest matched numbers are exiled to prose
- **What.** The section-1 ladder table (the first exhibit an interviewer sees) lists
  `DP $2,364` directly above `learned-forecast MPC −$303`, inviting the eye to read a **$2,667**
  gap. The honest, matched-window numbers (learned MPC **+$344**, option value **$2,020**) appear
  only in "deflation #2" two paragraphs later and in the fig-1 code caption.
- **Where.** `reports/stage5_writeup.md:44-70` (table + deflation prose);
  `src/figures.py:75-98` (`fig_ladder` plots the full-window `MPC_2H` dict `{learned:-303,...}`,
  DP at its traded value $2,364).
- **Why it's wrong/weak.** This is *exactly* the inflation the Stage 4 review corrected. The DP's
  full-window profit equals its traded-window profit ($2,364) only because it holds at $0 through
  warm-up; the MPC's −$303 *includes* warm-up losses the DP was structurally exempt from. Placing
  the two side-by-side in the hero table reintroduces the un-matched comparison the notes explicitly
  disown ("$2,020 is the honest option-value number," `stage5_notes.md:58`). A desk reader who skims
  the table and not the prose walks away with the wrong number — and the *one* number this whole
  stage exists to get right is the honest option value.
- **Fix.** Add a "matched traded window" column to the section-1 table (or a footnoted second value
  in each comparator row): learned MPC `−$303 (full) / +$344 (matched)`; put the **$2,020** option
  value *in the table*, not below it. The fig-1 caption already carries the cross-window note —
  promote that logic into the table itself. This is correct because it puts the fair (matched)
  comparison where the inflated one currently sits, and the honest number stops being a footnote.
- **Severity:** major. **Confidence:** verified. **Value:** raises-bar (shows the candidate
  *leads* with the corrected number rather than burying it — the opposite of a red flag).

### MAJOR 2 — The DP-capture headline (18%) uses the full-window ceiling while the MPC uses the matched window: internally inconsistent, and self-penalizing
- **What.** The abstract and ladder headline the DP at **"18% of the ceiling"** (`$2,364/$13,206`,
  full window). But every *comparator* is corrected to the matched traded window. The same warm-up
  correction that *raises* the MPC (−$303 → +$344) is **not** applied to the DP's capture
  denominator, which would raise it from 18% to **34%** (`$2,364/$6,972`, the traded ceiling —
  `stage5_run` prints exactly this: "34% of traded ceiling, 18% of full ceiling").
- **Where.** `reports/stage5_writeup.md:19-20, 48` and abstract; contrast `stage5_run.py:200-201`
  which reports both denominators; `stage5_notes.md:44` ("34% of the traded ceiling, 18% of the
  full ceiling").
- **Why it's wrong/weak.** The full-window ceiling includes ~2 months of arbitrage the DP could not
  have done — it had *no fitted model yet*. Charging that against the DP is like grading a trader on
  P&L from before their desk was funded. Using the pessimistic denominator for the DP and the
  optimistic (matched) treatment for the MPC is *conservative*, so it is not dishonest — but it is
  **inconsistent**, and it **undersells** the work by ~2x on the single efficiency ratio a desk
  cares about. An interviewer who notices the inconsistency (I did) reads it as sloppiness; one who
  doesn't walks away thinking the policy captures half what it actually does on its operating window.
- **Fix.** Lead with **"34% of the traded ceiling — the window it actually operates on — and 18% of
  the full window including a 2-month cold start."** Both numbers, traded first. This is correct
  because it applies *one* warm-up convention to numerator and denominator alike, matching the
  comparator treatment.
- **Severity:** major. **Confidence:** verified. **Value:** raises-bar.

### MAJOR 3 — "Causal ψ_up max $40.96 > clairvoyant $32.75" compares two different windows *and* two different extraction methods
- **What.** The abstract, §3, and Fig 6 all headline that the causal-operator tail max ($40.96)
  *exceeds* the Stage 0 clairvoyant max ($32.75), citing it as confirmation of Decision 19 ("caught
  short pays more"). But (i) the causal number is computed on the **140-day traded subset**
  (Feb 1 – Jun 20; I verified the cached `dates` span), while Stage 0's $32.75 is on the **full
  198-day window** (Dec 5 – Jun 20); and (ii) the causal ψ_up is a **reserve-LP dual at the executed
  post-decision SOC priced at interval MCPC, ρ=0.05** (`stage5_run.py:133-148`), whereas Stage 0's
  $32.75 is a **perfect-foresight energy+contingency LP dual**. Different estimand, different
  extraction, different sample.
- **Where.** `reports/stage5_writeup.md:16-18, 139-143`; `src/figures.py:198-220` (fig_psi draws the
  $32.75 line as a comparator); `src/stage5_run.py:295-297`.
- **Why it's wrong/weak.** The *mechanism* — a causal operator, having failed to pre-position SOC,
  faces a higher marginal scarcity cost than a clairvoyant who dodged it — is economically real and
  a desk respects it. But the *numeric* ">$32.75" is not a clean apples-to-apples: a domain expert's
  first question is "same window? same dual? same ρ?", and the answer is no on all three. Worse, the
  causal window is a *subset* of the clairvoyant window, so a naive reader might think the causal
  operator was measured over *more* stress, when it is actually fewer days (though it does capture
  the Mar/Apr/Jun spikes). The claim as stated is a small-sample, cross-method curiosity dressed as
  a clean inequality.
- **Fix.** Two options, both correct: (a) **preferred** — recompute the *clairvoyant* ψ_up on the
  **same 140-day window with the same interval-MCPC-at-executed-SOC extraction** (feed the
  perfect-foresight SOC path through the identical `reserves.reserve_lp` call), so the comparison is
  method- and window-matched; then the ">clairvoyant" claim is airtight. (b) If that is out of
  Stage-5 scope, **downgrade the claim to directional** — "the causal tail reaches ~$41/MWh,
  *comparable to and plausibly above* the clairvoyant lower bound; a window/method-matched
  clairvoyant re-extraction is the clean test (scoped)" — and add the window/method caveat to Fig 6.
  Fix (a) is correct because it isolates the *foresight* channel Decision 19 is about, holding window
  and extraction fixed.
- **Severity:** major. **Confidence:** verified (the mismatch is real); the *directional* conclusion
  is likely still true, so this is a credibility/rigor fix, not a numbers-are-wrong fix.
- **Value:** raises-bar (a matched re-extraction is a genuinely stronger result and cheap).

### MINOR 4 — The power statement is a t-test MDE, but the headline test is the sign test (metric mismatch), and sd(D) is computed over the 72 tie-days
- **What.** `power_statement` (`stage5_stats.py:173-194`) gives the minimum detectable *mean*
  difference (a normal-approx t-test MDE), reported as "detects an edge above 54% of the ceiling."
  But the **headline** inferential claim is the **sign test** (§VIII.5c, and the writeup leads with
  it). The two tests have different power curves. Separately, `sd(D)` is taken over all 140 days
  including the **72 exact ties** (both policies idle, `D_i=0`), which deflates sd and inflates n.
- **Where.** `src/stage5_stats.py:185-190`; `reports/stage5_writeup.md:95-99`.
- **Why it's weak.** For the *mean* difference over the 140-day series, including the zeros is
  correct (they are genuine $0 observations), so the number is not wrong. But (i) pairing a
  sign-test *headline* with a t-test *power* statement is a subtle incoherence a stats-literate
  interviewer will flag — "what's the power of the test you actually led with?"; and (ii) the zeros
  make the 54% an *optimistic* floor (as the docstring honestly notes), which happens to *strengthen*
  the "not resolvable" conclusion, so the direction is safe.
- **Fix.** Either (a) add one sentence giving the sign-test's power directly — with 68 non-tied days
  and observed 46%, the sign test cannot distinguish 50% from anything inside roughly [38%, 62%] at
  α=0.05, which is the honest sign-test analogue of the 54% number; or (b) explicitly label the power
  statement "power for the mean-difference t-test (secondary); the sign test is the headline and its
  effective n is 68." Fix (a) is better because it reports power *for the test that leads*.
- **Severity:** minor. **Confidence:** verified. **Value:** raises-bar (signals the candidate knows
  power is test-specific).

### MINOR 5 — "Execution is 97% free; the whole game is the forecast" is *nearly* right but should say *information*, and the §V.26 result sharpens it to *exogenous* signal
- **What.** §1 concludes "the entire difficulty is the forecast." The clairvoyant-MPC = 97%-of-
  ceiling point genuinely isolates execution (a perfect forecast fed to receding-horizon LP recovers
  97%, so the 3% loss is horizon-truncation/CE, not information) — **that half of the claim is
  solid and I affirm it.** But "the *forecast*" conflates two things the study actually separates:
  the *point* forecast (learned MPC) and the *distribution* (DP). And §5's own result — the CRPS-
  winning learned kernel did **not** beat the empirical one in decisions — says sharper
  *distributional* forecasting is **not** the bottleneck either.
- **Where.** `reports/stage5_writeup.md:54-60` (§1 claim) vs `:181-194` (§5 negative result).
- **Why it's weak.** As written, §1 and §5 sit in mild tension: §1 says "it's the forecast," §5 says
  "a better forecast (CRPS) didn't help." The resolution — which is a *stronger* and more defensible
  claim — is: execution is free; a *good* point forecast is necessary (naive loses, learned ≈
  breakeven); but the residual 66% gap to the clairvoyant is **tail-timing that a price-only kernel
  cannot see**, because the missing signal is **exogenous** (weather/load/wind/solar), not forecast
  *sharpness*. That is precisely why CRPS didn't translate.
- **Fix.** Reword §1 to "execution is ~free; the game is **information** — and specifically
  *exogenous* information: a good point forecast is necessary but not sufficient, and §5 shows a
  sharper *price* distribution doesn't close the gap, which points the remaining value at NWP
  features, not at more price modeling." Correct because it reconciles §1 with §5 and states the
  actual bottleneck.
- **Severity:** minor. **Confidence:** verified. **Value:** raises-bar (this *is* the sophisticated
  read — see Upgrade A).

### MINOR 6 — §2's framing leads with the null; the recovery arrives late
- **What.** §2's title is "Is the DP's edge real? The statistics say: not separably, on this
  sample," and the section spends three paragraphs on the null (sign test, CI, power) before the
  "But the DP is unambiguously doing real work" turn. For a desk/interviewer skimming headings, the
  memory that sticks is "not separable from zero" = "doesn't work."
- **Where.** `reports/stage5_writeup.md:74-104`.
- **Why it's weak.** The honesty is a *strength* and must stay — but *order* controls what a fast
  reader retains. The correct desk narrative leads with the **established** claim, then bounds it:
  (1) the DP makes money and beats a naive forecast 3:1 on days (p<0.001); (2) its value is
  spike-concentrated (top-5 = 114% of net) — a market fact; (3) *therefore* the mean is treacherous
  and we lead with the sign test; (4) against a *good* forecast the edge is real in total but **not
  separable** on 140 tail-dominated days, and here is the precise power limit; (5) that is an
  inference-limits statement about the *sample*, not a verdict on the *policy*.
- **Fix.** Retitle §2 to something like "How much of the DP's edge can 140 days certify?" and reorder
  to the (1)-(5) above. Keep every number. This is honest *and* compelling because it makes the null
  a *bound on the sample*, not a *bound on the policy*.
- **Severity:** minor. **Confidence:** verified (framing, not fact). **Value:** raises-bar.

### POLISH 7 — small consistency/robustness nits
- Fig 3 annotation uses `top{k}_share_of_total` (net-total denominator, "114%") while the §2 prose
  and Fig-code comments also cite gross-share ("83%"); make sure the writeup body and figure use the
  *same* denominator side-by-side or the 114% vs 83% will read as a typo to a careful reader
  (`src/figures.py:141-146` vs `stage5_run.py:236-239`). Confidence: verified. Value: cosmetic.
- The abstract is a single dense 19-line paragraph; a desk reader wants a one-line "so what." Add a
  final abstract sentence: "For an operator: the money here is being *positioned* for ~5 scarcity
  days a quarter, not steady arbitrage — and the SOC rule is nearly free until it isn't." Value:
  raises-bar.
- Fig 6 draws the $32.75 clairvoyant line without the window/method caveat of MAJOR 3; annotate it.
  Value: cosmetic.

---

## What a Base Power Markets quant asks that the writeup does NOT answer

These are the questions I would ask in the interview, in order, and the study currently has no
answer to any of them. Closing even one materially raises the artifact.

1. **"What do I trade differently *tomorrow*?"** The study measures value but never states an
   *action*. The answer is latent in the data and would be a killer close: *hold SOC into the
   top-decile scarcity-risk hours; accept that ~half of days you correctly do nothing; the entire
   edge is being long energy-headroom for a handful of events, so size the hold by tail risk, not by
   expected spread.* Signal: the candidate thinks like an operator, not just a modeler.
2. **"What does this imply for the *fleet*?"** The writeup notes ERCOT reserves clear system-wide
   (so ψ_up generalizes across ~300 ESRs on the *same* scarcity days) but never does the
   back-of-envelope. Even a rough one — "mean daily-max ψ_up ≈ $1.5/MWh × fleet MWh of upward-
   reserve hold ≈ $X of system-wide SOC-rule cost per scarcity day" — turns a single-asset result
   into a market-scale statement and directly answers the thin-sample problem (§VIII.5a item 3).
   Signal: connects the micro result to the book Base actually runs.
3. **"Where is the money left on the table, and is it recoverable?"** The 66% gap (traded ceiling →
   DP) is the headline unanswered quantity. §5's negative result is the *evidence* that it is **not**
   recoverable by better price modeling — it needs exogenous NWP signal. Stating that as a
   *diagnosis* (not a limitation) is the highest-value addition (Upgrade A).

---

## Resume / interview-value upgrades (my lens)

**Upgrade A (highest value) — a value-attribution paragraph that diagnoses *where* the value lives.**
Synthesize three results the study already has but never connects: (i) clairvoyant MPC = 97% →
execution is free; (ii) DP > learned MPC → distribution-awareness pays; (iii) §V.26 learned ≈
empirical → a *sharper price distribution does not help*. Conclusion: **the binding constraint is
exogenous information (weather/load/wind/solar), not execution, not forecast sharpness, and not the
optimizer.** This is a causal decomposition of the value-of-foresight gap, and it *prescribes* the
next dollar (NWP features) with evidence rather than hope.
*Why it's the top signal:* it converts an honest null ("edge not separable") into a demonstration of
**senior judgment** — the candidate can look at a stack of results and say precisely which lever
moves the P&L. That is the single most hireable sentence a quant can write, and it is *already
supported* by the existing numbers — no new computation required.

**Upgrade B — a 60-second verbal version (box at the top or in §1).** An interviewer will ask "walk
me through this in a minute." Provide it explicitly: *"One battery, ERCOT's new SOC rule.
Perfect-foresight ceiling → optimal causal DP → forecast-driven MPC → naive floor, all walk-forward,
no leakage. Three findings: (1) the DP turns the MPC's loss into a profit — distribution-awareness is
worth ~$2,020 — but on 140 tail-dominated days I *cannot* certify that edge over a good forecast, and
I show exactly why with a power statement; (2) the SOC rule is nearly free on average but spikes to
~$41/MWh in scarcity — and a real operator caught short pays more than a clairvoyant; (3) the whole
game is exogenous signal, because a sharper price model didn't move the decisions."* Signal:
communication discipline; can lead a meeting.

**Upgrade C — a one-line "what I'd do next, and why it would move the number."** The limitations
section lists NWP/summer/fleet as *caveats*; reframe the top three as a *roadmap with expected
direction*: NWP features (closes the exogenous-info gap A identifies — expected capture ↑); summer
re-solve (ψ_up ↑, one-directional); the ~300-asset fleet on shared scarcity days (the *only* thing
that fixes the thin-sample power limit — turns n=140 day-series into a cross-section). Signal:
prioritization — knows which next step buys the most.

**Upgrade D — make the ladder honest-and-fair in one exhibit (folds in MAJOR 1 & 2).** Rebuild Fig 1
so the DP and its comparators are *all* on the matched traded window, with the two clairvoyant bounds
clearly labeled full-window, and print both the 34%-traded and 18%-full capture. Signal: the
candidate's hero chart is the *corrected* one — reviewers trust every other number more.

---

## What is already right (stated plainly, not padded)

- **The pure-stats layer is correct and genuinely well-engineered.** Sign test drops ties per
  convention and matches scipy's exact binomial; stationary bootstrap is Politis–Romano with
  geometric blocks (correct choice for serially-dependent daily P&L); the concentration function
  reports both net-total *and* gross denominators (the right robustness move when totals can be
  small/negative); jackknife sign-fragility logic handles the full>0/min<0 case correctly. 18 tests
  pin all of it against synthetic inputs with known answers. This is a real software-engineering bar.
- **The CI-straddles-zero headline is the correct §VIII.5 result and is reported without spin.** No
  p-hacking, no denominator games to manufacture a star. That discipline is itself a hire signal.
- **The clairvoyant-MPC = 97% decomposition is a legitimately clean isolation of execution vs
  information** — I pressure-tested it and it holds (perfect forecast → 97% means the 3% is horizon
  truncation, not a weak baseline artifact).
- **The §V.26 "learned ≈ empirical" negative result is exactly the kind of thing that only shows up
  when you evaluate a model *inside the decision it feeds*** — publishing it (with a CI) is a
  maturity signal most candidates lack. It is also the load-bearing evidence for Upgrade A.
- **Q3 "duration buys forgiveness for forecast error" (capture −3% → 25%) is sound and
  interesting,** and correctly grid-corrected (ΔS-constant). Not over-read — the mechanism (a short
  battery must time spikes precisely; a causal policy cannot) is real and the monotone capture curve
  is the right evidence.

---

## Severity roll-up

| # | finding | severity | confidence | value |
|---|---|---|---|---|
| 1 | hero table encodes inflated DP-vs-MPC gap | major | verified | raises-bar |
| 2 | DP capture 18% (full) vs comparators (matched) — inconsistent, undersells | major | verified | raises-bar |
| 3 | ψ_up $40.96 > $32.75 crosses windows *and* extraction methods | major | verified | raises-bar |
| 4 | power statement is t-test MDE; headline is sign test; sd over ties | minor | verified | raises-bar |
| 5 | "the whole game is the forecast" → *information* / exogenous signal | minor | verified | raises-bar |
| 6 | §2 leads with the null; reorder to lead with what's established | minor | verified | raises-bar |
| 7 | concentration denominator consistency; abstract "so what"; Fig 6 caveat | polish | verified | cosmetic/raises-bar |

**Highest-value single upgrade:** A — the value-attribution paragraph (97%-free + DP>MPC + CRPS-
didn't-translate ⇒ the bottleneck is exogenous NWP signal). It needs no new computation and converts
the honest null into the study's most hireable sentence.
