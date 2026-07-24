# Stage 7 review — battery-desk quant / Base Markets interviewer lens

Reviewer lens: a battery-desk quant at an ERCOT shop who is also the hiring manager for the Base
Markets quant-dev intern. Question I am answering: **is the settlement methodology and the economic
story defensible to a domain expert, and does this make me want to hire the author?**

Verdict in one line: the *plumbing* is genuinely good (stream-and-discard ETL, tested SQL joins,
duration reproduces ERCOT's fleet average, the AS two-settlement is structurally the right model),
but **the two headline economic claims — the 29% AS share and the "our DP ranks ~14th percentile
because it is information-limited" — are not robust to fixes I can demonstrate against the warehouse.**
The locate-our-policy number in particular is depressed by two apples-to-oranges artifacts worth
~2x and ~1.5x that I reproduced on a sample. Fixing them is the difference between a humble-but-honest
result and a *confounded* one — and a desk will spot the confound in thirty seconds.

All numbers below were reproduced against `data/warehouse_fleet.duckdb` and the cached parquets unless
labeled "suspected."

---

## What is solid (said plainly)

- **AS two-settlement is the RIGHT structure.** Under RTC+B (live 2025-12-05) AS is procured DA at
  DAMCPC and then re-cleared in real time, with a *new AS imbalance settlement* replacing the old RT
  AS imbalance calc (confirmed via ERCOT's RTC+B settlement materials). The code's
  `DA award x DA MCPC + (RT award - DA award) x RT MCPC x 0.25` is exactly the DA-capacity + RT-imbalance
  two-settlement. This is not a rough hack; it is the correct first-order model. Credit.
- **The two-settlement ENERGY join is correct and unit-tested** on a known example (HE1=4 intervals,
  DA 5MW@$20 + (10-5)MW@$40 → $300). The hour-ending↔15-min mapping is right.
- **`$/kW-month` mean-of-ratios is not a problem here.** I worried the per-asset mean would be
  distorted by small assets; it is not — reported mean $1.741 vs MW-weighted fleet aggregate $1.775
  (0.1% apart). The fleet is homogeneous enough after eligibility that the two agree. Credit.
- **Modo reference numbers are real, not invented.** I independently confirmed Modo's Jan-26
  $3.94/kW-month and Feb-26 $1.08/kW-month. The C1 anchor is honest.
- **Duration reproduces ERCOT's published fleet average** and SOC integrity holds — good independent
  checks.

---

## MAJOR findings

### M1. Locate-our-policy compares NET-of-degradation DP profit to GROSS realised revenue and a GROSS ceiling — a ~2x self-inflicted penalty
- **What.** `our_dp_capture = r.profit / ceiling_gross`, but `r.profit` is energy profit **net of the
  c_deg=25 degradation charge** (`backtest.py`: `e_step = price*(d-c)*dt - c_deg*(c+d)*dt`), while
  `realized_capture = realized_energy_rev / ceiling_gross` is **gross/gross**
  (`realized_energy_rev` has no degradation term; `ceiling_gross` is read from
  `gross_revenue_from_dispatch`, gross).
- **Where.** `src/stage7_run.py:300` (`our_cap = r.profit / row.ceiling_gross`) vs `:196` (realised
  capture) and `:67` (gross ceiling).
- **Why it's wrong.** The numerator of our-DP capture is charged degradation; the numerators of both
  the realised operators AND the ceiling are not. That is a straight apples-to-oranges comparison. I
  reproduced it on 4 assets:

  | asset | capture NET (reported) | capture GROSS (fair) | realised |
  |---|---|---|---|
  | SWOOSEII_ESR1 | 9.7% | **19.3%** | 46.2% |
  | ZAPATA_ESR1 | 3.1% | **13.4%** | 19.0% |
  | PYR_ESR1 | -2.2% | **6.0%** | 25.0% |
  | PYR_ESR3 | 5.2% | **12.3%** | 38.5% |

  Degradation is eating **50–137% of gross** (c_deg=25 on throughput is large relative to the thin
  spreads this price-only DP captures). Correcting to gross roughly **doubles** the reported DP
  capture; the "our DP median 10%" headline is closer to ~18–20% on a like-for-like basis.
- **Fix + why correct.** Compute the DP's **gross** energy revenue for the capture numerator
  (`sum(price*(d-c))*dt` from the backtest log, dropping the `-c_deg*(c+d)*dt` term), so numerator and
  denominator are both gross — the same basis as the realised-operator capture. This is not spin: it
  removes a charge the comparator does not bear. (If you prefer net-vs-net, subtract an *assumed* c_deg
  from the operators too — but their degradation is unobserved, which is exactly why the whole stage is
  gross; so gross-vs-gross is the only consistent choice.)
- **Severity: major. Confidence: verified. Resume-value: raises-bar** (a desk will immediately ask
  "is your policy net and theirs gross?"; having already handled it is a credibility signal).

### M2. Locate warm-up: the ceiling denominator includes the ~40% of value the DP earns $0 on during its 2-month train window
- **What.** `WalkForwardDPPolicy(min_train_months=2)` holds (~$0) for the first ~2 months, but
  `our_cap = r.profit / ceiling_gross` divides by the **full-window** ceiling, which includes Dec+Jan.
- **Where.** `src/stage7_run.py:294–300`.
- **Why it's wrong.** I measured the value concentration (avg daily price spread × days, a clean
  arbitrage proxy): **40% of window arbitrage value falls in Dec+Jan**, and January alone has the
  highest daily spread of any month ($185 avg vs ~$80 in Dec/Feb/May) — the cold-snap month, entirely
  inside the warm-up. So the denominator carries ~40% of value the numerator structurally cannot
  touch. This is a denominator-window mismatch, not an information deficit.
- **Fix + why correct.** Report the **matched-traded-window** capture for BOTH our DP and the realised
  operators: restrict numerator *and* ceiling to the post-warm-up window (≈ Feb-05 onward) for a fair
  ratio (self-critique 3a proposes this but it was not done). Removing ~40% from the denominator
  raises the ratio ~1.5x. This is the pre-registered fair comparison; it does not manufacture a result,
  it removes an artifact.
- **Severity: major. Confidence: verified (value concentration measured; ~1.5x is an estimate → the
  exact re-solve is the deliverable). Resume-value: raises-bar.**

### M3. The "information-limited, not optimizer-limited" interpretation is confounded and overreaches
- **What.** The stated conclusion — our DP ranks low *because* it lacks exogenous signal (NWP/load) —
  attributes the entire 10%→35% gap to information. But M1 (degradation ~2x), M2 (warm-up ~1.5x), and
  M4 (DA market access, below) are three separable, non-information causes that each push the DP number
  down, and I have quantified all three as material.
- **Where.** `reports/stage7_notes.md` §6 / §8.3; `src/stage7_run.py` locate print block.
- **Why it's wrong.** Stacking M1 and M2 alone plausibly moves the DP median from 10% toward ~25–30%,
  i.e. from "14th percentile" to "near the median." The conclusion that we rank *near the bottom* may
  **not survive** a fair comparison — which means the single-cause "exogenous signal is the bottleneck"
  story is not yet earned by this evidence. It may still be *directionally* true (Stage 5 argued it on
  cleaner internal grounds), but Stage 7 cannot claim it *externally confirms* the thesis until the
  comparison is apples-to-apples.
- **Fix + why correct.** Re-run locate with M1+M2 fixed and re-state the ranking. Then decompose the
  *residual* gap into the identifiable pieces (market access vs information) rather than asserting one.
  Honest landing: "after correcting degradation, warm-up, and DA-access, our RT-only price-only DP
  still captures X% vs operators' Y%; the residual is consistent with (but does not prove) an
  information gap." That is a *stronger* claim because it survives scrutiny.
- **Severity: major. Confidence: verified. Resume-value: raises-bar** (shows you can tell a confound
  from a finding — the core skill the role screens for).

### M4. Capture uses a two-settlement realised numerator over an RT-ONLY perfect-foresight ceiling — DA>RT, so captures can (and do) exceed 1.0
- **What.** `realized_energy_rev` is DA award×DA price + RT deviation×RT price (two markets), but
  `ceiling_gross` is a perfect-foresight LP on **RT node prices only** (`asset_energy_ceiling` →
  `oracle.solve(prices=rt_lmp)`).
- **Where.** `src/stage7_run.py:58–67` (ceiling) vs `:73–99` (realised).
- **Why it's wrong.** I measured DA vs RT node prices at matched node/hour: **mean DA $35.30 vs RT
  $31.13, E[DA−RT] = +$4.17/MWh, corr only 0.50.** DA is systematically richer, so an operator who
  sold day-ahead can beat an RT-only clairvoyant. This is not hypothetical: **PALACIOS_ESR1 has
  capture 1.21** (realised $230.5k, of which DA $249.1k, vs RT-only ceiling $190.5k). A realised
  capture above its own perfect-foresight ceiling is *impossible against a correct ceiling* and is the
  visible symptom of the basis mismatch. The systematic effect: realised captures are **generous to
  operators** (denied the DA leg the operators actually used), and — compounding M1/M2 — the RT-only DP
  in locate is **doubly disadvantaged** (it cannot even access the DA premium the operators bank).
- **Fix + why correct.** Make the ceiling a **two-settlement clairvoyant**: at each hour let the
  perfect-foresight LP transact at max(DA, RT) opportunity (or, minimally, price the DA-award block at
  the DA path and only the deviation at RT, mirroring the realised construction). This is the only
  ceiling that upper-bounds a two-settlement realised revenue. At minimum, state the basis mismatch and
  cap captures at 1.0 with a flag rather than reporting 1.21. Note for locate: an RT-only DP will never
  match two-settlement operators regardless of information — that gap is *market access*, and should be
  named as such.
- **Severity: major. Confidence: verified. Resume-value: raises-bar.**

### M5. C1 delivered a window-mean band that is too wide to fail; the pre-registered per-MONTH check shows good SHAPE but a systematic ~25% LEVEL shortfall
- **What.** Plan §8 pre-registered the gate as *"monthly fleet-average within ~20% AND the same
  month-to-month shape."* The code instead checks whether the single **window-mean** $1.74 lands in a
  **$1–$4 band** — a band so wide (Feb $1.08 to Jan $3.94 nearly span it) that almost any reconstruction
  "validates."
- **Where.** `src/stage7_run.py:233,259–273` (`C1_MODO_BAND=(1.0,4.0)`, `inband` check).
- **Why it's wrong.** I ran the pre-registered monthly comparison (fleet-aggregate $/kW-month vs
  Modo):

  | month | reconstructed | Modo | ratio |
  |---|---|---|---|
  | 2026-01 | $2.74 | $3.94 | 0.69 |
  | 2026-02 | $0.95 | $1.08 | 0.88 |
  | 2026-04 | $2.44 | $3.12 | 0.78 |

  The **shape matches** (Jan high, Feb low, Apr high) — a genuine, strong validation the band check
  throws away. But the **level is systematically ~20–30% LIGHT every month** (Jan is 31% below,
  outside the pre-registered ±20%). A consistent proportional shortfall is *informative*: it localizes
  an under-count (prime suspects: AS imbalance/deployment, or telemetered-vs-SMNE metered energy, or
  the dropped RT intervals in M8). "Validated to first order" is defensible for *shape* but should not
  paper over a repeatable ~25% level gap.
- **Fix + why correct.** Replace the band check with the pre-registered per-month ratio + shape test
  (I did it above; it's ~10 lines of SQL), report the ~25% shortfall as a finding, and localize it by
  month/stream. This is what plan §8 said the monthly check is *for* ("the discrepancy localizes the
  reconstruction error, most likely in the AS two-settlement"). Doing the harder, pre-registered check
  and reporting the miss is more credible than passing a band that cannot fail.
- **Severity: major. Confidence: verified. Resume-value: raises-bar.**

---

## MINOR findings

### m6. The 29% AS share is under-determined and may be understated — do not sell it as a clean regime shift
- **What/why.** AS $54.2M / total $186.5M = 29%. But M5 shows total revenue is ~25% light, and the
  most likely locus of the shortfall is the **AS imbalance** (the explicitly flagged approximation) or
  AS-deployment energy. If the missing ~$60M is disproportionately AS, the true AS share could be
  ~40%+. Separately, the "share" divides a *net* energy number (energy revenue nets ~$20M of DA
  charging + RT buybacks) by a *gross* AS capacity number — a mixed denominator. Historically ERCOT
  BESS is 80–90% AS; 29% is a big claim to rest on a reconstruction with a known systematic gap.
- **Where.** `stage7_notes.md` §5/§8.2; `stage7_run.py:264`.
- **Fix.** Report AS share as a **range** bracketed by the DA-only AS ($47.3M → 25% share) and
  RT-total AS ($47.3M DA + $18.5M rt_as_total → 32% share) assumptions, and state that the C1 level
  shortfall could raise it further. Keep the "AS collapsed in 2025–26" narrative (it is real — AS
  saturation + RTC+B price compression are documented) but as a *range with a caveat*, not "29%, regime
  confirmed."
- **Severity: minor. Confidence: verified (share is sensitive; the 25% shortfall is measured).
  Resume-value: raises-bar.**

### m7. DA/RT/ceiling windows are not matched (161 SCED vs 168 DAM vs 171 price days)
- **What/why.** Realised RT energy is summed over **161** SCED days; DA energy+AS over **168** DAM
  days; the ceiling LP runs over **~170** price days. 10 DAM-only days (incl. Dec-6, Dec-7 winter and
  Mar-3/4/5/7/14) book DA revenue with no RT offset; 3 SCED-only days net RT against a zero DA award;
  the ceiling captures ~9 days of arbitrage (incl. Mar-7 $1,874 and Mar-14 $2,000 spikes) that the
  realised numerator never sees → **capture is systematically deflated** by the value in those days.
- **Where.** `stage7_run.py` `_REALIZED_ENERGY_SQL` (no date filter) and
  `energy_cross_section` ceiling loop (`SELECT rt_lmp ... ORDER BY ts_15min`, unfiltered).
- **Fix.** Intersect all three to a **common date set** before summing/solving (a single
  `WHERE ts_15min::date IN (common_dates)`). Small dollar effect but exactly the consistency a desk
  audits.
- **Severity: minor. Confidence: verified. Resume-value: raises-bar.**

### m8. Node-price join is an INNER join — 2.15% of RT intervals silently drop, and any zero-coverage node becomes DA-only
- **What/why.** The `rt` CTE uses `JOIN prices_node` (inner). I measured **97.85%** of SCED rows match
  a node price; the other 2.15% contribute $0 RT deviation, understating RT energy. Worse, an asset
  whose node has *no* prices gets `rt` = NULL → its realised energy collapses to DA-only with no flag.
- **Where.** `stage7_run.py:83–84`.
- **Fix.** Report the per-asset match rate and exclude/flag assets below a coverage threshold (self-
  critique 8 names this; make it a guardrail, not a footnote). Reuse the Stage-1 timestamp-gap audit.
- **Severity: minor. Confidence: verified. Resume-value: neutral.**

### m9. RT energy uses telemetered net output, not SMNE metered energy (acknowledged, but bounds not given)
- **What/why.** True RT energy settlement uses SMNE (`60d_SCED_SMNE_GEN_RES`). The 15-min *mean* of
  5-min telemetry is a proxy; for a heavily-cycling battery the gap can be a few %, and it plausibly
  contributes to the M5 level shortfall. Acknowledged in §8.4 but with no magnitude.
- **Fix.** Either ingest SMNE for a sample of assets/days to *bound* the telemetry-vs-metered error, or
  state the expected sign/size. A desk will ask "how far off is telemetered from settled MWh?"
- **Severity: minor. Confidence: suspected (I did not ingest SMNE). Resume-value: neutral.**

### m10. AS "award" sign/meaning assumption is unstated
- **What/why.** `(RT award − DA award)` is the correct imbalance **only if** the SCED "AS Awards"
  field is the *total* real-time AS responsibility (gross), not an already-incremental quantity.
  Believed correct (ERCOT 60-day SCED reports total assigned AS), but it is the linchpin of the whole
  AS number and is not asserted/tested anywhere.
- **Fix.** Add a one-line data-dictionary note + a sanity check (e.g., on a day with no DAM AS award,
  RT award should equal total assigned AS, not zero). Cheap insurance on a load-bearing assumption.
- **Severity: minor. Confidence: suspected. Resume-value: neutral.**

---

## POLISH
- `stage7_notes.md` reports duration median 1.64h; all-327 median is 1.705h (eligible subset differs).
  Label which population the 1.64 is from so the "vs ERCOT 1.65" match is exactly reproducible.
- The `warnings.filterwarnings("ignore", "overflow encountered in reduce")` at module import hides a
  real numeric overflow somewhere in the ceiling solves — track down which asset overflows rather than
  muting it globally.

---

## What a Base Markets quant would ask that the record doesn't answer
1. **"Is your policy number net and the operators' gross?"** — yes, and it's ~2x (M1). This is the
   first question and currently the answer is unflattering.
2. **"Your capture exceeds 1.0 for an asset — how?"** — DA/RT basis mismatch (M4). Must not ship a
   >1.0 capture without explanation.
3. **"What's the AS share, and how sensitive is it to your imbalance assumption?"** — 25%–32%+ range,
   not a point (m6).
4. **"Why is every month ~25% below Modo?"** — currently unaddressed; the band check hides it (M5).
5. **"Did your DP miss the January cold snap because it was still training?"** — yes, and Jan is the
   single highest-value month (M2).

## The 1–3 additions that would most make me trust this person with fleet dispatch code
1. **The matched, gross-vs-gross, common-window locate comparison (M1+M2+M4+m7 together).** One clean
   re-run turns a confounded "14th percentile" into a defensible number and shows the author reflexively
   controls for basis, degradation, and warm-up. This is the single highest-value change and the thing
   I would most want to see before trusting them with dispatch P&L.
2. **The per-month C1 with the ~25% shortfall reported and localized to a stream (M5/m6).** Reproducing
   a commercial benchmark's *shape* and honestly owning a *level* gap is exactly "validating an
   economic model against observed behaviour" — the named job responsibility — done to a real bar.
3. **A settlement data-dictionary + assertions for the AS-award and DA/RT basis assumptions (m10, M4).**
   Turning the two load-bearing settlement assumptions into tested invariants is the TDD signal the
   role screens for.

---

## Highest-value single fix
**Re-run locate-our-policy as a like-for-like comparison: gross DP revenue (drop c_deg from the
numerator), over the post-warm-up matched window for BOTH the DP and the operators, against a ceiling
restricted to that same window.** I reproduced that the degradation basis alone is ~2x and the warm-up
denominator is ~1.5x, and January (highest-value month) sits entirely inside the warm-up — so the
current 10% / 14th-percentile / "information-limited" headline is not robust. The corrected number is
the honest one, and whichever way it lands (still-below-median = thesis holds cleanly; near-median =
thesis was overclaimed) it is *more* defensible and *more* impressive than the confounded version.
