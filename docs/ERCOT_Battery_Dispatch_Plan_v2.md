# Duration, Shadow Prices, and Optimal Storage Dispatch Under ERCOT's RTC+B Market Design

## A Stochastic Control Project — Complete Plan, Derivations, and Rationale

> **LIVING PLAN — edit it as we learn.** This document holds the reasoning behind
> the project. It is NOT frozen: if you have new information or a better argument,
> change what needs changing — and update the *reasoning* when you do, rather than
> silently dropping it. `CLAUDE.md` holds the latest working state, so where the
> two disagree, CLAUDE.md is simply newer — reconcile them, don't treat either as
> immutable. Three things a cold-start reader should know up front:
> (1) The **Option C reframing** (Decisions 11–16) supersedes the "Q2 and Q3 are
> the same computation" claim: they are two sides of one SOC coupling — floor cost
> `psi_up` vs. ceiling value `lambda_bar + psi_dn` — not the same object
> (`docs/decision_C_reframing.html`).
> (2) **Stage 0 (viability) is DONE — qualified PROCEED** (Decision 18;
> `reports/step0_results.md`).
> (3) **Target role = Quantitative Developer Intern, Markets** (Decision 17). The
> project is organized as **Stages** (Part XIV), not incremental "steps"; the core
> is Stages 0–5, and the build is organized around the **value of foresight**
> (Decisions 19–20).

**Version 2.** Supersedes the prior plan entirely. All market facts verified as of 20 July 2026. Every mathematical claim in Part IV is derived, not asserted; where something is assumed rather than proved, it is labelled **[Assumption]** and the consequence of its failure is stated.

---

# Table of Contents

**Part 0 — Decisions of Record**
**Part I — Premise and Purpose**
**Part II — The Market, Corrected**
**Part III — Problem Formulation**
**Part IV — The Mathematics, Derived**
**Part V — The Learned Price Model**
**Part VI — The Research Questions**
**Part VII — Risk**
**Part VIII — Evaluation Protocol**
**Part IX — Data and Engineering**
**Part X — Build Order and Gates**
**Part XI — The ADER Chapter**
**Part XII — Known Weaknesses**
**Part XIII — What This Does Not Demonstrate**
**Appendices**
**Part XIV — Execution Stages** *(read this first on any cold start)*

---

# PART 0 — DECISIONS OF RECORD

These were open questions. They are now closed. Each is recorded with its reason so the choice can be defended rather than merely reported.

| # | Decision | Reason |
|---|---|---|
| 1 | **Modelled asset is a grid-scale Energy Storage Resource (ESR)**, hub-settled, with a separate analytical chapter on what changes for an aggregated residential fleet (ADER). | RTC+B's battery-specific changes apply to ESRs. The 60-day disclosure benchmark covers ESRs. The literature is written against ESRs. The ADER chapter supplies employer-specific relevance without forcing the core model to sit on pilot-program rules that are still changing. |
| 2 | **Headline question: the duration-value curve** (Part VI, Q3). **Mechanism: the shadow price of the state-of-charge duration constraint** (Q2). | These are the same computation — §IV.11 proves the duration derivative *is* the sum of the relevant multipliers. One build, two results. The question is legible to a non-specialist, produces a curve rather than a point estimate (robust to thin samples), and RTC+B's duration-requirement changes give a natural before/after framing. |
| 3 | **Secondary result: the day-ahead / real-time ancillary basis** (Q1). | Falls out of the co-optimization already being built. Supplies topical currency. |
| 4 | **Risk chapter: the retailer-plus-battery objective** (Q5). | The only component that addresses the *Risk & Trading* half of the job description. Makes CVaR load-bearing instead of decorative. |
| 5 | **Demoted: stochastic DP vs. MPC option-value comparison** (Q4). | A method-comparison question, not a market question. With ~228 post-launch days dominated by one event, it may not be establishable. Retained as a supporting result, not a headline. |
| 6 | **Cut entirely: decision-focused learning; deep reinforcement learning; the preprint ambition.** | DFL: ~200 daily training instances cannot distinguish it from predict-then-optimize at any plausible effect size, by its own literature's account of when the advantage exists. Deep RL: must be trained on simulated prices, which reintroduces the price model it was meant to avoid while discarding the optimality argument. Preprint: the fleet-benchmark component reproduces work sold commercially; chasing publishability would distort priorities. |
| 7 | **Degradation cost $c_{\text{deg}}$ is per MWh of grid-side throughput, charged on both legs.** | Physically the cell sees throughput on both charge and discharge. Fixing the convention once removes the internal inconsistency that produced a 64% error in the prior plan's breakeven spread. |
| 8 | **Time resolution: 15 minutes for all headline results**, hourly permitted only during development. | 15 minutes is the ERCOT settlement interval. Hourly averaging destroys the spikes that carry the profit *and* destroys the option value that separates stochastic control from certainty-equivalent control — i.e. it biases exactly the comparison being made. |
| 9 | **Horizon: 24-periodic infinite-horizon fixed point**, not a finite-horizon backward pass. | Eliminates the terminal-value problem entirely (§IV.9), and reduces compute by roughly two orders of magnitude. |
| 10 | **Two settlement points**, one of which is congestion-prone. | Guards against the conclusion being an artifact of one node. |
| 11 | **All data from free public sources.** | Full reproducibility is a credibility property. The ingest code written to achieve it *is* the software-engineering evidence the role requires. |
| 12 | **The price model is a learned conditional distribution evaluated by proper scoring rules.** | The Bellman equation requires $\mathbb{E}[V_{t+1}\mid\mathbf{x}_t]$, i.e. a conditional distribution. This is the project's genuine machine-learning content, and it is structurally required rather than added. |
| 13 | **Live paper-trading config: 1 MW rating, run at both 1-hour and 2-hour duration, at two settlement points — four tracks, frozen on day one.** | Under price-taking the problem is homogeneous of degree one in scale ($\mathcal{V}(\alpha\bar p,\alpha E^{\max}) = \alpha\mathcal{V}(\bar p,E^{\max})$), so the MW rating is a reporting convention, not a modelling choice; 1 MW makes outputs directly comparable to the industry's \$/kW-month convention. Duration is the only real choice. ERCOT's operational fleet entered 2026 at 13,888 MW / 22,853 MWh — a **fleet-average duration of 1.65 hours**, up from 1.5 h a year earlier, with systems above 2.5 h still rare (112 MW commissioned in 2025). Running 1 h and 2 h straddles that average and brackets the legacy ancillary-optimised stock against the marginal new build, at the cost of one extra DP solve. **It also makes the headline question something observed forward in real time rather than only backtested.** |
| 14 | **The hedging requirement is met by extending Q5 one step, not by a separate artifact.** | Q5 already computes the joint distribution of retail margin plus battery profit. Adding a priced financial overlay and reporting the marginal cost of tail reduction through each available channel is ~20% more work and answers the question the role actually poses. A standalone congestion-rights study would not. See §VI Q5. |
| 15 | **A viability test precedes all building.** | Q2 and Q3 both rest on the energy-headroom constraints actually binding. If $\psi\equiv 0$ in practice, Q2 has no answer and Q3 collapses to plain energy arbitrage. This is cheap to establish and decisive. See Part XIV, Step 0. |

---

# PART I — PREMISE AND PURPOSE

## 1. What this project is

A single-asset stochastic control study of battery dispatch in ERCOT under the Real-Time Co-optimization plus Batteries (RTC+B) market design, using only post-launch public data, with an exactly-solved optimal policy, a learned conditional price distribution, a perfect-foresight upper bound, an honest statistical treatment of a heavily tail-concentrated profit distribution, and a live forward-running policy log.

Its central deliverable is a **curve**: the marginal economic value of storage duration under the current market rules, together with the mechanism that generates it — the shadow price of the constraint coupling stored energy to ancillary-service obligations.

## 2. Why this question

Three reasons, in decreasing order of how much they should be said out loud.

**It is the question the industry is currently asking.** ERCOT ancillary revenues have fallen roughly 90% since 2023 as storage capacity saturated the market, and value has shifted to energy arbitrage, which requires genuinely good sequential decisions. Simultaneously, RTC+B changed the duration requirements that determine which ancillary products a battery of a given duration can sell at all. The economic value of an additional hour of duration therefore changed discontinuously on 5 December 2025, and nobody has published the new curve from public data with open code.

**It is mathematically clean and the answer is a dual variable.** §IV.11 shows the derivative of optimal value with respect to energy capacity equals a sum of Lagrange multipliers on the capacity and reserve-headroom constraints. This is the same object that generates locational marginal prices in ERCOT's own dispatch optimization. The project therefore exhibits the same principle at three levels — market prices, linear-programming duals, and dynamic-programming value gradients — and can demonstrate that they are one idea.

**It is robust to the data limitation.** With ~228 days of post-launch data and profit concentrated in a handful of events, any single point estimate has a wide interval. A *curve's shape* survives conditions under which any of its individual points would not.

## 3. Success criteria

Success is:

1. A tested, documented, publicly reproducible codebase that a practitioner can read in twenty minutes.
2. A duration-value curve computed under both the pre- and post-RTC+B ancillary duration requirements, with the shadow-price decomposition that explains it, bracketed between a perfect-foresight ceiling and a naive-heuristic floor, with full cost accounting and stated confidence.
3. The ability to derive, without notes, every result in Part IV.
4. An explicit account of what the analysis does not establish.

Success does **not** require that any method beat any other, or that anything be novel. The novelty available is in the setting and the openness of the artifact, not the mathematics, which is decades old.

## 4. The methodological stance

**Exact dynamic programming on a learned model, not approximate control on the true one.**

The honest statement of the position — and the prior plan overstated this — is not that the method delivers an optimality certificate for the market. It delivers the **exact solution of an approximate model**: a discretised state of charge, a learned conditional price distribution, an estimated transition structure, all misspecified to some degree. The comparison against deep reinforcement learning is therefore not "guarantee versus no guarantee." It is:

> **The error of an exactly-solved approximate model is attributable and testable.** Vary the grid, vary the model class, vary the conditioning set, and watch the answer move. Deep reinforcement learning's error is a superposition of model misspecification, function-approximation error, and optimisation failure, and it cannot be decomposed.

That is a stronger claim and it survives scrutiny. It is also the reason the project includes a small tabular Q-learning exhibit (Part X, item 9): an approximate method benchmarked against a known optimum is informative; one benchmarked against nothing is not.

---

# PART II — THE MARKET, CORRECTED

This part builds the market from first principles and corrects several errors that were load-bearing in the prior plan.

## 5. Why electricity is structurally unlike other commodities

Storable commodities couple prices across time through inventory: if tomorrow's expected price exceeds today's by more than carrying cost, buying today and selling tomorrow is profitable, and the act of doing so closes the gap. Storage enforces a no-arbitrage relation between spot and forward prices.

Electricity has, historically, no storage at grid scale. Generation must equal consumption at every instant or system frequency deviates from 60 Hz and protection systems begin disconnecting equipment. There is no buffer, and the consequences follow directly:

**Extreme volatility.** ERCOT real-time prices routinely sit in the \$15–40/MWh range and occasionally reach the cap. Intraday ratios of 100:1 are unremarkable.

**Negative prices.** High wind with low load — typically overnight in West Texas — combined with shutdown/restart costs and production-based subsidies makes some generators willing to pay to deliver. A battery is *paid to charge* in these hours. This is a revenue source, not an anomaly to filter.

**Strong mean reversion.** Spikes are caused by transient physical conditions — heat, a generator trip, low wind at peak — which resolve within hours. This is structurally unlike an equity price, where shocks are approximately permanent.

**Locational variation.** Transmission lines have finite capacity. When cheap West Texas wind cannot physically reach Houston load, the two locations clear at different prices at the same instant. This is congestion.

A battery manufactures storage where none existed. Its profit derives precisely from the volatility the historical absence of storage created.

## 6. Locational marginal pricing

The **Locational Marginal Price** (LMP) is the incremental system cost of serving one additional MW at a specific location and instant:

$$\text{LMP}_{i,t} = \underbrace{\lambda_t}_{\text{system energy}} + \underbrace{\text{cong}_{i,t}}_{\text{congestion}} + \underbrace{\text{loss}_{i,t}}_{\text{losses}}$$

$\lambda_t$ is the dual variable on the systemwide power-balance constraint in ERCOT's Security-Constrained Economic Dispatch (SCED). This is not analogy: ERCOT solves a constrained optimisation every five minutes and the published prices *are* its shadow prices. $\text{cong}_{i,t}$ reflects shadow prices of binding transmission constraints; $\text{loss}_{i,t}$ reflects marginal resistive losses.

**Prices in this industry are shadow prices.** Part IV derives the marginal value of stored energy and shows it is simultaneously a dynamic-programming value gradient and a linear-programming dual. That is the same principle that generates LMPs, applied one level down.

## 7. The two-settlement system

**Day-Ahead Market (DAM).** A financially binding forward auction cleared the day before delivery, producing hourly prices $P^{DA}_t$ per settlement point. Selling day-ahead is entering a financial position; it does not commit specific electrons.

**Real-Time Market (RTM).** SCED re-optimises every five minutes producing $P^{RT}_t$; financial settlement occurs on 15-minute intervals constructed from those five-minute prices.

**Settlement identity.** With $q^{DA}_t$ the day-ahead quantity and $q^{\text{act}}_t$ the delivered quantity,

$$\text{Revenue}_t = P^{DA}_t q^{DA}_t + P^{RT}_t\big(q^{\text{act}}_t - q^{DA}_t\big)$$

Read carefully: the day-ahead position settles at the day-ahead price *unconditionally*; only the deviation touches the real-time price. The DAM is therefore a forward contract and the RTM a spot market. Selling day-ahead and delivering exactly that quantity leaves zero real-time price exposure on the energy leg.

## 8. The forward premium is not a market inefficiency

Under risk-neutrality one would expect $P^{DA}_t = \mathbb{E}[P^{RT}_t \mid \mathcal{F}_{t^-}]$, where $\mathcal{F}_{t^-}$ is information at auction clearing. In ERCOT and elsewhere this fails.

**The prior plan called this a failure of market efficiency. That framing is wrong and will be attacked.** The day-ahead price is an equilibrium price formed by *risk-averse* participants. It equals the expectation of the spot price under a risk-adjusted (pricing) measure $\mathbb{Q}$, not under the physical measure $\mathbb{P}$:

$$P^{DA}_t = \mathbb{E}^{\mathbb{Q}}\big[P^{RT}_t \mid \mathcal{F}_{t^-}\big], \qquad \pi_t \;:=\; \mathbb{E}^{\mathbb{Q}}\big[P^{RT}_t\big] - \mathbb{E}^{\mathbb{P}}\big[P^{RT}_t\big]$$

$\pi_t$ is the **forward risk premium** — the difference between the two measures, i.e. compensation for bearing spot risk. A nonzero $\pi_t$ is exactly what an efficient market populated by risk-averse agents produces. Its *sign* in ERCOT varies by year, hour, and product; real-time has exceeded day-ahead on average in spike-heavy years. Measure it; do not assert its direction.

## 9. Ancillary services

ERCOT procures two categorically different things. **Energy** is megawatt-hours delivered, priced per MWh. **Ancillary services (AS)** are *reserved capability* — the commitment to change output on short notice — paid per MW per hour of availability, whether or not called.

The clearing price is the **Market Clearing Price for Capacity (MCPC)**.

**Duration requirements, from the governing source.** These are set by **NPRR1282, "Ancillary Service Duration under Real-Time Co-Optimization,"** approved by the ERCOT Board on 24 June 2025. The table below reproduces ERCOT's own summary (RTC+B Battery Overview, July 2025, slide 22) with the Nodal Protocol section references, so that each value is citable rather than inherited from secondary commentary.

| Product | Real-time qualification duration | Protocol § | RUC duration | Protocol § | Award & deployment |
|---|---|---|---|---|---|
| Regulation Service | 30 min | 8.1.1.3.1(2) | 30 min | 8.1.1.2.1.1(5) | 1 h |
| RRS (excluding FFR) | 30 min | 8.1.1.3.2(4) | 30 min | 8.1.1.2.1.2(9) | 1 h |
| ECRS | 1 h | 8.1.1.3.4(2) | 1 h | 8.1.1.2.1.7(3) | 1 h |
| Non-Spin | 4 h | 8.1.1.3.3(2) | 4 h | 8.1.1.2.1.3(8) | 1 h |

Fast Responding Regulation Service (FRRS) is **eliminated** under RTC. Pre-RTC+B values for comparison: ECRS 2 h, RRS 1 h, Regulation 1 h, Non-Spin 4 h. **RRS–FFR is excluded from the 30-minute row and its duration must be verified separately in §8.1.1.3.2 before being used** — secondary sources give 15 minutes but ERCOT's own table does not state it, and the project should not carry an unverified parameter.

**The constraint is proportional, not categorical.** ERCOT's formulation *limits award MW* by available energy; it does not disqualify short-duration resources from a product. In ERCOT's words: *"The awards for each Resource are limited based on the Resource's qualification, telemetered physical capabilities, SoC information, ramp rates, and duration requirements for each Ancillary Service type."* Concretely, one MW of Non-Spin award requires four MWh stored at the start of the interval, so a half-hour battery may sell Non-Spin — at one-eighth the MW per unit of rating that a four-hour battery may.

**This matters directly for Part VI.** Because the limit is proportional, the duration-value curve is **continuous** and $\partial\mathcal{V}/\partial E^{\max}$ exists everywhere. A staircase with jumps at 0.25, 0.5, 1 and 4 hours would have broken the finite-difference-versus-multiplier consistency check of §IV.11 at every jump; under the proportional rule, a failure of that check indicates a bug, not a discontinuity.

**A second, categorical layer nonetheless exists.** Ancillary qualification is a separate registration process carrying per-resource qualified MW, including an RRS percentage limit that ESRs were required to resubmit forms to update at the RTC+B transition. The complete constraint is therefore

$$u^k_t \;\le\; \min\Big(\underbrace{\bar u^k_{\text{qual}}}_{\text{registration}},\;\; \underbrace{\tfrac{\eta_d\,(S^+_t - S^{\min})}{\tau_k}}_{\text{real-time SOC}}\Big)$$

The registration cap is administrative and fixed per resource; model it as a constant and note it.

**Selling an ancillary service is selling an option to the grid operator.** The seller's cost is not fuel — it is opportunity cost: capacity committed to reserves is unavailable for energy, and stored energy held to back the commitment is unavailable to sell. §IV.10 derives the exact offer condition. The right-hand side of that condition is what the dynamic program computes.

**Selling an ancillary service is selling an option to the grid operator.** The seller's cost is not fuel — it is opportunity cost: capacity committed to reserves is unavailable for energy, and stored energy held to back the commitment is unavailable to sell. §IV.10 derives the exact offer condition. The right-hand side of that condition is what the dynamic program computes.

## 10. What RTC+B actually changed

**The old design.** Ancillary services were procured principally in the day-ahead market, with the **Supplemental Ancillary Services Market (SASM)** available intraday to fill gaps arising from failure to provide, infeasible capacity, increased need, or insufficient day-ahead offers. Batteries were represented by a "combo model" — one physical device registered as both a generation resource and a controllable load — and SCED did not track state of charge, so a battery could be awarded obligations it lacked the energy to fulfil. Scarcity was priced through the Operating Reserve Demand Curve (ORDC), an adder applied to energy prices, external to the dispatch optimisation.

*(The prior plan's claim that ancillary capacity was "locked" once awarded day-ahead was wrong. SASM existed, and AS positions were tradeable.)*

**The new design, effective 5 December 2025.**

1. **Ancillary services are procured in the real-time market, co-optimised with energy.** SCED jointly determines energy dispatch and AS awards every interval. Real-time AS prices are produced directly by SCED for the first time.
2. **Batteries are a single resource with explicit state of charge.** ERCOT tracks SOC inside SCED and Reliability Unit Commitment and enforces that a resource has the stored energy to deliver its commitments. Duration requirements are **rolling and forward-looking**, enforced against telemetered SOC: an offer for the next five-minute interval requires enough SOC to sustain the award for the product's full duration going forward. Offers violating this are subject to mitigation in SCED.
3. **Scarcity pricing was restructured.** The ORDC was replaced by per-product **Ancillary Service Demand Curves (ASDCs)** embedded in the co-optimisation. (The ORDC survives as the Aggregate ORDC, built from June 2014–August 2025 data, from which the individual ASDCs are derived.) Reserve scarcity now propagates directly into both AS clearing prices and LMPs.
4. **SASM was eliminated.** Its role is served by the co-optimised RUC and real-time market.
5. **The offer cap was split.** The single systemwide offer cap of \$5,000/MWh became a day-ahead cap (DASWCAP) of \$5,000/MWh and a **real-time cap (RTSWCAP) of \$2,000/MWh**. System lambda and real-time MCPCs are capped at effective Value of Lost Load, currently the DASWCAP of \$5,000/MWh. Nodal LMPs can still exceed the offer cap through extreme congestion. **This project is a real-time project; \$2,000/MWh bounds the offers, not \$5,000.**
6. **Portfolio-level ancillary management was abolished.** ERCOT: *"QSE management of Ancillary Service responsibility across their portfolio no longer exists."* Before RTC+B a scheduling entity could cover its obligations across its whole fleet; now feasibility is enforced per resource, inside SCED. **This tightens exactly the constraint this project measures and is the strongest single justification for the project's premise.**
7. **The day-ahead market does not consider state of charge at all.** ERCOT: *"State of Charge (SOC) is not considered in the clearing for Energy and Ancillary Services in the DAM. (If not careful, a QSE representing ESRs could 'oversell' its capability in DAM. Financial Exposure is based on imbalance between DAM and Real-Time.)"* The physical constraint binds **only in real time**. See §11 for why this is a structural asymmetry rather than an oversight.
8. **Performance tolerance tightened.** Base Point Deviation was replaced by **Set Point Deviation** with a tolerance of the greater/lesser of 3% of the Average Aggregated Set Point or 3 MW — materially less forgiving than the prior calculation. This bounds how much execution slippage a realistic backtest may assume (§XII.2).
9. **ERCOT publishes projected Deployment Factors** per ancillary product per hour, valued in $[0,1]$ and used in RUC to simulate deployment. These supply $\rho_k$ directly (§III.19).

**Primary source for items 2, 5–9 and the duration table:** ERCOT, *Real-Time Co-Optimization + Batteries: Overview of the "+Batteries" Portion of the Project*, Kenneth Ragsdale, July 2025 — `https://www.ercot.com/files/docs/2025/07/15/RTC-B-Battery-Overview.pdf`. The "+B" scope comprises NPRR1014 (single model), NPRR1204 (state of charge with RTC), NPRR1236 (RUC capacity-short), NPRR1246 (terminology), and NPRR1282 (ancillary duration).

## 11. Day-ahead ancillary is now a financial position

This is the single most important correction to the prior plan, and it invalidated its central question.

**Under RTC+B, day-ahead ancillary awards are financially binding only.** A resource is paid the day-ahead clearing price for its award and settles any imbalance against the real-time MCPC — structurally identical to the day-ahead/real-time energy two-settlement.

Worked example: clear 100 MW of ECRS day-ahead at \$10/MW-h; provide none of it in real time; real-time ECRS averages \$20/MW-h that hour. The imbalance charge is $100 \times (20 - 10) = \$1{,}000$.

Two consequences.

**First, there is no "locked commitment" counterfactual.** A policy that "commits ancillary capacity day-ahead and cannot revise" does not correspond to either the old market (SASM existed) or the new one (you can always buy back). Any result framed as "the value of real-time co-optimisation versus day-ahead commitment" is measuring nothing.

**Second, the reward function must carry two ancillary prices, not one.** Writing a single $P^k_t$ is the same category of error as writing energy revenue with a single price. §III.17 does it correctly.

**Third — and this was not visible until ERCOT's own documentation was read — the two settlements are governed by *different physics*.** The energy-headroom constraint (EH-up)/(EH-dn) is enforced in real time by SCED against telemetered state of charge. It is **not enforced in the day-ahead market at all**. A resource may therefore sell more ancillary capability day-ahead than it can physically deliver, and settle the difference financially at the real-time MCPC.

This is a genuine structural asymmetry, and it changes what Q1 is asking:

$$\underbrace{\text{DA ancillary}}_{\text{financial, unconstrained by SOC}} \qquad\text{versus}\qquad \underbrace{\text{RT ancillary}}_{\text{physical, SOC-constrained}}$$

Combined with the observed empirical pattern — real-time ancillary clearing below day-ahead roughly 93% of the time since launch, and day-ahead generally outperforming — deliberately overselling day-ahead and buying back in real time is a **structurally available trade**, not a modelling artefact. The question is not whether it exists but what tail risk it carries: the rare reversals are large, and one real-time spike has been observed to convert a month's accumulated positive basis into a negative one. That makes Q1 a question about selling tail risk, which is the same exposure the retail book already carries (§12) — so the two positions **compound rather than diversify**. See §VI Q1.

## 12. Why a retail-plus-battery company cares

A retail electricity provider sells at a fixed or near-fixed rate while purchasing from the volatile wholesale market. Revenue is approximately deterministic; cost is a random variable with a severe right tail. During an extreme scarcity event, wholesale costs can exceed retail revenues by orders of magnitude; multiple Texas retailers became insolvent in 2021 for exactly this reason.

In derivatives language: **selling fixed-price electricity while purchasing at spot is economically a short position in a large portfolio of call options on the power price.**

There are two responses: financial hedging (forwards, congestion revenue rights, heat-rate options) and the battery fleet as a *physical* hedge — a charged battery during scarcity means power discharged rather than purchased at the cap.

**Methodological consequence.** A dispatch policy maximising expected arbitrage profit but leaving the fleet depleted during the worst hour of the year can have *negative* value to such a firm. Risk-aware dispatch is therefore closer to the true objective than expected-value maximisation. This is the argument that makes Part VII load-bearing.

---

# PART III — PROBLEM FORMULATION

## 13. Time

Intervals $t = 0,1,\dots$ of length $\Delta t$. Headline results use $\Delta t = 1/4$ hour, matching ERCOT settlement. All energies in MWh, all powers in MW, all prices in \$/MWh (energy) or \$/MW-h (capacity).

## 14. State

$$s_t = \big(S_t,\; \mathbf{x}_t\big)$$

$S_t \in [0, E^{\max}]$ is the **state of charge** in MWh — the *endogenous* state, the only component the controller influences.

$\mathbf{x}_t$ is the **exogenous market state**. The prior plan listed a rich conditioning vector and then proposed tabulating fifty states, which is a contradiction. The resolution, stated explicitly because it must be defended:

> **The tabulated exogenous state is a low-dimensional sufficient statistic. All other information enters through the *estimation* of the conditional distribution, not through the state.**

Concretely, $\mathbf{x}_t = (h_t,\; b_t,\; z_t)$ where $h_t$ is hour-of-day (or a coarser time-of-day block), $b_t$ is a bin index of the deseasonalised price, and $z_t$ is a bin index of a scarcity indicator (net-load forecast error, or reserve margin). Everything else — load, wind, solar, forecast vintages, outages — is a *feature* used by the model of Part V to predict the transition probabilities, not a dimension of the tabulated state.

**[Assumption A1 — Markov sufficiency.]** $\mathbb{P}(\mathbf{x}_{t+1}\in A \mid \mathcal{F}_t) = \mathbb{P}(\mathbf{x}_{t+1}\in A \mid \mathbf{x}_t)$. This is what makes dynamic programming valid. It is false in reality — prices depend on generator outage schedules, weather persistence, and fuel prices with longer memory than any modest state captures. **Consequence of failure:** the computed policy is optimal for a process that is not the true one; the magnitude of the resulting suboptimality is bounded by the model-error term in §IV.13 and must be probed by state-augmentation sensitivity (add a lag, re-solve, measure the change in the answer).

## 15. Action

Net injection $g_t \in [-\bar p, \bar p]$, positive meaning discharge to the grid, plus ancillary commitments.

$$a_t = \big(g_t,\; \mathbf{u}^{RT}_t\big), \qquad \mathbf{u}^{RT}_t = (u^{1}_t,\dots,u^{K}_t) \ge 0$$

**Why net power rather than separate $(c_t,d_t)$.** The prior plan used $c_t, d_t \ge 0$ with the constraint $c_t d_t = 0$, which is nonconvex, and then dropped it in the linear program with an unproved justification. Using $g_t$ with $c_t = (g_t)^- = \max(-g_t,0)$ and $d_t = (g_t)^+ = \max(g_t,0)$ makes the complementarity automatic and the degradation term $c_{\text{deg}}|g_t|$ convex. The nonconvexity disappears by construction. §IV.7 nonetheless proves the two formulations agree, because the proof is required in interview.

Day-ahead positions $q^{DA}_t$ and $\mathbf{u}^{DA}_t$ are treated as **exogenous inputs** to the real-time problem, per §II.11 — they are financial positions already struck, and the real-time decision is the physical one whose deviation settles at real-time prices.

## 16. Transition

Define the **throughput map**

$$\Phi(g) \;=\; -\frac{(g)^+}{\eta_d} \;+\; \eta_c\,(g)^-$$

so that

$$S_{t+1} \;=\; S_t \;+\; \Phi(g_t)\,\Delta t$$

**Derivation.** Delivering $g\Delta t$ MWh to the grid at discharge efficiency $\eta_d < 1$ requires drawing $g\Delta t/\eta_d$ from storage. Consuming $|g|\Delta t$ MWh from the grid at charge efficiency $\eta_c < 1$ adds only $\eta_c|g|\Delta t$ to storage. Losses appear on both legs; the asymmetry is physical and must not be simplified away.

**Property (used repeatedly).** $\Phi$ is concave and piecewise linear: its slope is $-\eta_c$ for $g<0$ and $-1/\eta_d$ for $g>0$, and since $\eta_d<1<1/\eta_c$ we have $-1/\eta_d < -\eta_c$, so the slope is nonincreasing in $g$. ∎

Round-trip efficiency is $\eta := \eta_c\eta_d$.

## 17. Constraints

**Energy bounds.**
$$0 \;\le\; S_t \;\le\; E^{\max}$$

**Power bound.**
$$-\bar p \;\le\; g_t \;\le\; \bar p$$

**Power headroom — corrected.** The prior plan wrote $d_t + \sum_{\mathcal{K}^{\text{up}}} u^k \le \bar p$ and $c_t + \sum_{\mathcal{K}^{\text{dn}}} u^k \le \bar p$. That is a *generator's* constraint. A battery charging at full rate has $2\bar p$ of upward capability: it can stop charging and then discharge. The correct constraints, in terms of net injection, are

$$g_t + \sum_{k\in\mathcal{K}^{\text{up}}} u^k_t \;\le\; \bar p, \qquad\qquad -g_t + \sum_{k\in\mathcal{K}^{\text{dn}}} u^k_t \;\le\; \bar p$$

**Derivation.** Upward capability is the amount by which net injection can increase from its scheduled value before hitting the physical limit: $\bar p - g_t$. Committing $\sum_{\mathcal{K}^{\text{up}}} u^k$ of upward reserve requires that capability. Symmetrically downward: net injection can fall by $g_t - (-\bar p) = \bar p + g_t$. ∎

The prior formulation makes overnight charging while selling RegUp infeasible. That is one of the most common profitable stacked positions in ERCOT, and it is precisely the position an oversized residential battery is built for.

**Energy headroom — corrected, and post-decision.** To *deliver* $\tau_k u^k_t$ MWh at the terminals under an upward deployment requires $\tau_k u^k_t/\eta_d$ MWh drawn from storage. To *absorb* $\tau_k u^k_t$ MWh under a downward deployment adds $\eta_c \tau_k u^k_t$ to storage. Because the requirement is rolling and forward-looking (§II.10), it binds on the **post-decision** state of charge $S^+_t := S_t + \Phi(g_t)\Delta t$:

$$S^+_t \;-\; S^{\min} \;\ge\; \frac{1}{\eta_d}\sum_{k\in\mathcal{K}^{\text{up}}} \tau_k\, u^k_t \tag{EH-up}$$

$$E^{\max} \;-\; S^+_t \;\ge\; \eta_c\sum_{k\in\mathcal{K}^{\text{dn}}} \tau_k\, u^k_t \tag{EH-dn}$$

with $S^{\min} \ge 0$ a reserved floor (zero for a grid-scale ESR; strictly positive for a residential unit with a backup obligation — see Part XI).

**(EH-up) and (EH-dn) are the mathematical content of RTC+B.** They are what force stored energy to be allocated between energy sales and reserve obligations, making the products competitors for a shared scarce resource rather than independently optimisable. Everything in Part VI derives from the multipliers on these two constraints.

## 18. Reward

$$r_t \;=\; \underbrace{P^{RT}_t\big(g_t - q^{DA}_t\big)\Delta t}_{\text{energy deviation}} \;+\; \underbrace{\sum_{k} P^{k,RT}_t\big(u^k_t - u^{k,DA}_t\big)\Delta t}_{\text{ancillary deviation}} \;-\; \underbrace{c_{\text{deg}}\Big(|g_t| + \sum_k \phi_k u^k_t\Big)\Delta t}_{\text{degradation}} \;+\; \underbrace{\text{const}_t}_{\text{DA settlement}}$$

where $\text{const}_t = P^{DA}_t q^{DA}_t + \sum_k P^{k,DA}_t u^{k,DA}_t$ is not a function of the real-time decision and therefore does not affect the policy, though it does affect reported profit.

**The $\phi_k$ term.** $\phi_k$ is expected grid-side throughput per MW of product $k$ committed, per interval. The prior plan charged degradation only on $c_t$ and $d_t$, making ancillary commitment *costless* in the model. Regulation causes real throughput. Since the entire purpose of Part VI is to price ancillary against energy on a common basis, omitting $\phi_k$ biases the headline result toward ancillary. Estimate $\phi_k$ from ERCOT's published deployment factors and, for Regulation, from AGC signal statistics.

## 19. Deployment: two distinct mechanisms

The prior plan folded all products into a single "deployment probability" $\rho_k$. That is wrong for Regulation and a practitioner will notice immediately.

**Contingency products (RRS, ECRS, Non-Spin)** deploy as *discrete, rare, large* events, correlated with scarcity. Model as a Bernoulli event with state-dependent probability $\rho_k(\mathbf{x}_t)$; on deployment, energy $\tau_k u^k_t$ flows and is compensated at the real-time energy price in addition to the capacity payment.

**Regulation (RegUp/RegDn)** deploys *continuously*, following an AGC signal. Expected net energy displacement per interval is near zero; what matters is the **variance** it induces in $S$ and the throughput it causes. Model as a mean-zero increment with variance $\sigma^2_{\text{reg}} u^k_t{}^2 \Delta t$ added to the state transition, plus the $\phi_k$ throughput cost.

**The correlation is adverse and must be modelled, not caveated.** Contingency reserves are most likely to deploy exactly when energy prices are highest, so the true opportunity cost of ancillary commitment exceeds what an independence assumption implies. Since the model of Part V already produces a conditional scarcity indicator, making $\rho_k$ a function of it is nearly free.

**$\rho_k$ does not need to be invented.** ERCOT publishes projected **Deployment Factors** for each ancillary product for each hour, valued in $[0,1]$, and uses them inside RUC to simulate deployment. Use ERCOT's published factors as the baseline $\bar\rho_k$, then estimate the *conditional* deviation $\rho_k(\mathbf{x}_t) - \bar\rho_k$ from realised deployment data stratified by scarcity regime. Anchoring on the operator's own published numbers and modelling only the conditional departure is both more defensible and less work than estimating the level from scratch.

## 20. Objective

$$\max_{\pi\in\Pi} \;\; \liminf_{T\to\infty}\frac{1}{T}\,\mathbb{E}^{\pi}\!\left[\sum_{t=0}^{T-1} r_t\right] \qquad\text{(average reward)}$$

over policies $\pi: s_t \mapsto a_t$ **adapted** to the information filtration $\{\mathcal{F}_t\}$ — using only information available at decision time. Part VII replaces this with a risk-aware objective.

**Why average reward and not discounted.** A discount factor at 15-minute resolution has no economic content; setting $\gamma$ "slightly below 1" is a numerical convenience that distorts the policy near the SOC bounds. The 24-periodic average-reward formulation of §IV.9 is exact, has no free parameter, and eliminates the terminal-value problem.

## 21. Adaptedness is the formal statement of "no lookahead"

A **filtration** $\{\mathcal{F}_t\}$ is an increasing family of $\sigma$-algebras representing accumulating information: $\mathcal{F}_t$ contains every event whose truth is determined by time $t$. A policy is **adapted** if $a_t$ is $\mathcal{F}_t$-measurable.

Every backtest failure mode in Part VIII is, formally, a violation of $\mathcal{F}_t$-measurability. This is not decoration — it is what the test suite in §IX.4 asserts on.

**And it contains a trap the prior plan would have fallen into.** A policy stated as "discharge if $P^{RT}_t > \theta$" is *not* $\mathcal{F}_t$-measurable, because $P^{RT}_t$ is the clearing price of interval $t$ and is not known when the decision for interval $t$ is made. §IV.6 shows how the threshold policy is rescued: the decision object is an **offer curve** submitted before clearing, and dispatch is determined by comparing the realised price to the offer. §VIII.2 makes this a required, tested property.

---

# PART IV — THE MATHEMATICS, DERIVED

Every result here is proved. Assumptions are labelled and their failure modes stated.

## IV.1 The value function and the Bellman equation

Fix the 24-periodic structure and write $V_h(S,\mathbf{x})$ for the value function at time-of-day index $h$. Define the **average-reward optimality (Bellman) equation** with gain $\rho$ and bias $V$:

$$\rho + V_h(s) \;=\; \max_{a\in\mathcal{A}(s)}\Big\{\, r(s,a) \;+\; \mathbb{E}\big[V_{h+1}(s')\,\big|\,s,a\big] \Big\} \tag{B}$$

where $h+1$ is taken modulo 24 (in units of $\Delta t$, modulo the number of intervals in a day) and $s'$ is the successor state.

**Why (B) holds — the principle of optimality.** Suppose $\pi^\star$ is optimal from state $s$ at time $h$, and suppose its continuation from the successor state $s'$ at time $h+1$ were strictly suboptimal for the subproblem faced at $(h+1, s')$. Replace that continuation with an optimal one for the subproblem. The decision at $h$ is unchanged, the immediate reward is unchanged, and the expected continuation value strictly increases — so total expected reward strictly increases, contradicting optimality of $\pi^\star$. Hence every tail of an optimal policy is optimal for its subproblem, which is exactly the self-referential statement (B). ∎

**Conditions required.** (i) Additive separability of the objective across periods — holds by construction in §III.20. (ii) The Markov property [A1]. (iii) For the average-reward formulation, a unichain condition ensuring the gain $\rho$ is state-independent — satisfied here because from any $(S,\mathbf{x})$ the battery can reach any other SOC in finitely many intervals and the exogenous chain is irreducible on its recurrent class, so the induced chain has a single recurrent class. **[Assumption A2]**, verifiable numerically by checking the estimated transition matrix is irreducible.

## IV.2 The post-decision state — and why the prior plan's centrepiece was circular

Split the transition into its deterministic and stochastic halves. Define the **post-decision state of charge**

$$S^+ \;=\; S + \Phi(g)\Delta t$$

and the **post-decision value function**

$$\widetilde V_h(S^+,\mathbf{x}) \;:=\; \mathbb{E}\big[V_{h+1}(S^+, \mathbf{x}')\,\big|\,\mathbf{x}\big]$$

so (B) becomes

$$\rho + V_h(S,\mathbf{x}) \;=\; \max_{a}\Big\{ r(S,\mathbf{x},a) + \widetilde V_h\big(S+\Phi(g)\Delta t,\;\mathbf{x}\big)\Big\} \tag{B'}$$

Define the **marginal value of stored energy**

$$\boxed{\;\mu_h(S^+,\mathbf{x}) \;:=\; \frac{\partial \widetilde V_h(S^+,\mathbf{x})}{\partial S^+}\;}$$

**This, not $\partial V/\partial S$, is the opportunity cost, the decision threshold, and the bid price.** The prior plan used $\mu = \partial V_h/\partial S$, which is circular. To see why, apply the envelope theorem to (B') in the discharge region, where the optimal $g^\star > 0$ is interior:

$$\frac{\partial V_h}{\partial S} \;=\; \frac{\partial \widetilde V_h}{\partial S^+} \;=\; \mu_h$$

— fine when $g^\star$ is interior, but when the power constraint binds ($g^\star = \bar p$) the envelope gives $\partial V_h/\partial S = \mu_h$ still, whereas when the *SOC* constraint binds the two differ. More importantly, substituting $\partial V_h/\partial S$ into the threshold condition derived next produces, in the region where the optimum is at a kink, the vacuous statement $P_t > P_t$. The pre-decision gradient already contains the option to trade at $P_t$; the threshold must be built from the gradient of the *continuation* value, which is $\mu_h$.

Two practical benefits follow from the post-decision formulation. The expectation is computed once per $(S^+,\mathbf{x})$ rather than once per action, and $\widetilde V$ is the object that is actually submitted to the market.

## IV.3 The optimal policy is a state-dependent price band — derivation

Ignore ancillary for a moment (added in §IV.10). The inner problem of (B') in $g$ is

$$\max_{g\in[-\bar p,\bar p]} \; \Big\{ \big(P_t g - c_{\text{deg}}|g|\big)\Delta t \;+\; \widetilde V_h\big(S + \Phi(g)\Delta t,\mathbf{x}\big)\Big\}$$

Write $\mu := \mu_h(S^+,\mathbf{x})$ evaluated at the resulting $S^+$.

**Discharge branch, $g>0$.** Here $|g|=g$ and $\Phi(g) = -g/\eta_d$. Differentiating:

$$\frac{\partial}{\partial g} = \big(P_t - c_{\text{deg}}\big)\Delta t \;-\; \frac{\mu}{\eta_d}\Delta t$$

This is positive — so discharging is worthwhile — iff

$$\boxed{\;P_t \;>\; \frac{\mu}{\eta_d} \;+\; c_{\text{deg}}\;} \tag{D}$$

**Charge branch, $g<0$.** Substitute $g = -c$ with $c>0$; then $|g| = c$ and $\Phi = \eta_c c$. Differentiating with respect to $c$:

$$\frac{\partial}{\partial c} = -\big(P_t + c_{\text{deg}}\big)\Delta t \;+\; \eta_c\mu\,\Delta t$$

Positive iff $\eta_c\mu > P_t + c_{\text{deg}}$, i.e.

$$\boxed{\;\mu \;>\; \frac{P_t + c_{\text{deg}}}{\eta_c}\;} \tag{C}$$

**The prior plan wrote (C) as $\mu > P_t/\eta_c + c_{\text{deg}}$.** That divides only the price by $\eta_c$ and not the degradation cost, understating the required marginal value by $c_{\text{deg}}(1/\eta_c - 1)$. The error is small numerically (≈\$1.58/MWh at $c_{\text{deg}}=30$, $\eta_c=0.95$) and fatal in interview, because it reveals a transcribed symmetry rather than a derivation.

**The no-trade band.** Neither (D) nor (C) holds when

$$\eta_c\mu - c_{\text{deg}} \;\le\; P_t \;\le\; \frac{\mu}{\eta_d} + c_{\text{deg}}$$

whose width is

$$W \;=\; \mu\Big(\frac{1}{\eta_d} - \eta_c\Big) \;+\; 2c_{\text{deg}} \;>\; 0$$

**This is a derivable, non-obvious, defensible result.** Round-trip inefficiency and degradation together create a strictly positive band of prices at which the optimal action is to do nothing. The band widens with the marginal value of stored energy and with degradation cost. A fixed-threshold heuristic has no such band and therefore over-trades — which is the mechanism by which it underperforms, not a vague appeal to "optimality."

## IV.4 The round-trip breakeven spread

**Claim.** A charge-then-discharge round trip is profitable only if

$$\boxed{\;P^{\text{sell}} \;>\; \frac{P^{\text{buy}}}{\eta} \;+\; c_{\text{deg}}\Big(1 + \frac{1}{\eta}\Big)\;}$$

**Derivation.** Purchase 1 MWh grid-side at $P^{\text{buy}}$. Storage gains $\eta_c$ MWh. Delivering that stored energy to the grid yields $\eta_c\eta_d = \eta$ MWh grid-side. Grid-side throughput is $1$ on the charge leg and $\eta$ on the discharge leg, so degradation cost is $c_{\text{deg}}(1+\eta)$. Net profit:

$$\Pi = \eta P^{\text{sell}} - P^{\text{buy}} - c_{\text{deg}}(1+\eta)$$

Setting $\Pi>0$ and dividing by $\eta$ gives the claim. ∎

**Numerically**, at $P^{\text{buy}} = \$20$, $\eta = 0.90$, $c_{\text{deg}} = \$30$/MWh:

$$\frac{20}{0.9} + 30\Big(1 + \frac{1}{0.9}\Big) = 22.22 + 63.33 = \$85.56$$

The prior plan reported \$52 — a 64% understatement of the threshold, in the very section that criticised others for ignoring degradation. The error came from writing $+c_{\text{deg}}$ instead of $+c_{\text{deg}}(1+1/\eta)$, i.e. charging degradation on one leg when the reward function charges it on two.

**Consistency check against §IV.3.** In steady state with $\mu$ approximately constant across the round trip, (C) and (D) give $P^{\text{buy}} < \eta_c\mu - c_{\text{deg}}$ and $P^{\text{sell}} > \mu/\eta_d + c_{\text{deg}}$. Eliminating $\mu$: $\mu > (P^{\text{buy}}+c_{\text{deg}})/\eta_c$ and $P^{\text{sell}} > \mu/\eta_d + c_{\text{deg}}$, so

$$P^{\text{sell}} > \frac{P^{\text{buy}}+c_{\text{deg}}}{\eta_c\eta_d} + c_{\text{deg}} = \frac{P^{\text{buy}}}{\eta} + c_{\text{deg}}\Big(\frac{1}{\eta}+1\Big)$$

identical. ∎ The threshold policy and the static breakeven are the same statement, which is a useful internal consistency test on the implementation.

## IV.5 Degradation cost from first principles

$$c_{\text{deg}} \;=\; \frac{C_{\text{replace}}}{N_{\text{cyc}}\cdot E^{\max}_{\text{nom}} \cdot \text{DoD}} \;\times\; \frac{1}{1 + \eta}\cdot(1+\eta)$$

More simply: amortise replacement cost over lifetime grid-side throughput.

**Derivation.** A pack costing $C_{\text{replace}}$ (\$) delivers $N_{\text{cyc}}$ equivalent full cycles before end of warranty life. One equivalent full cycle moves $E^{\max}_{\text{nom}}$ MWh out of storage and requires $E^{\max}_{\text{nom}}/\eta_c$ MWh in, so grid-side throughput per cycle is $E^{\max}_{\text{nom}}(\eta_d + 1/\eta_c)$. Hence

$$c_{\text{deg}} \;=\; \frac{C_{\text{replace}}}{N_{\text{cyc}}\,E^{\max}_{\text{nom}}\big(\eta_d + 1/\eta_c\big)}$$

At \$200/kWh installed = \$200,000/MWh, $N_{\text{cyc}} = 5{,}000$, $\eta_c=\eta_d=0.95$: denominator $=5000\times 1\times(0.95+1.053) = 10{,}015$, so $c_{\text{deg}} \approx \$20$/MWh. Warranty terms with lower cycle counts or higher installed cost push this toward \$50.

**[Assumption A3 — linear throughput degradation.]** Real degradation is nonlinear in depth of discharge, temperature-dependent, and path-dependent (rainflow counting). The linear model is convex, preserves the linearity of the optimisation, and captures first-order economics, but it **understates the cost of deep cycling and overstates the cost of shallow cycling**. **Consequence of failure:** the optimal policy cycles too deeply. Probe by re-solving with a piecewise-linear convex depth penalty and measuring the change in the duration curve.

$c_{\text{deg}}$ is comparable in magnitude to typical intraday spreads. Sensitivity over $c_{\text{deg}}\in[0,60]$ is therefore a required deliverable, not a robustness afterthought; if the sign of a conclusion flips inside that range, that is the headline finding.

## IV.6 The bid curve

Real-time markets require a monotone price–quantity offer curve, submitted **before** clearing. The optimal offer to sell the $q$-th MWh is the price at which the operator is exactly indifferent, which by (D) is

$$\boxed{\;\text{offer}(q) \;=\; \frac{\mu_h\!\big(S - q/\eta_d,\;\mathbf{x}\big)}{\eta_d} \;+\; c_{\text{deg}}\;}$$

and symmetrically the bid to buy the $q$-th MWh is $\eta_c\,\mu_h(S+\eta_c q,\mathbf{x}) - c_{\text{deg}}$.

**This resolves the adaptedness trap of §III.21.** The decision object submitted at $t$ is the function $\text{offer}(\cdot)$, which depends only on $(S_t,\mathbf{x}_t)$ and hence is $\mathcal{F}_t$-measurable. Dispatch is then determined by the market: the operator is dispatched for quantity $q$ such that $\text{offer}(q) \le P^{RT}_t < \text{offer}(q+\mathrm{d}q)$. Because $\text{offer}$ is exactly the inverse of the threshold rule, the resulting dispatch coincides with (D) — so the threshold policy is *self-consistent* under correct execution semantics. **This is a genuine result and should be stated explicitly in the writeup**, because it is the difference between a backtest that leaks and one that does not.

**MPC does not get this for free.** A receding-horizon controller produces a *plan* ("inject 0.5 MW at $t$"), and converting a plan into an offer curve is a modelling choice that determines whether MPC receives an unfair information advantage. §VIII.2 specifies the conversion.

**Non-differentiability.** The discretised $\widetilde V$ is piecewise linear in $S^+$, so $\partial\widetilde V/\partial S^+$ does not exist at grid points; the correct object is the superdifferential, and the offer curve is a **step function** whose steps are the finite differences $\big[\widetilde V(S_{j}) - \widetilde V(S_{j-1})\big]/\Delta S$. This is convenient rather than problematic: ERCOT wants a stepped curve.

## IV.7 Concavity, monotonicity, and the complementarity relaxation

**Proposition 1 (Concavity).** If $V_{h+1}(\cdot,\mathbf{x})$ is concave in $S$ for every $\mathbf{x}$, then $V_h(\cdot,\mathbf{x})$ is concave in $S$.

**Proof.** Work in the $(c,d)$ representation with $c,d\ge 0$ and the constraint $cd=0$ **relaxed** (justified by Proposition 3). Then the feasible set

$$\mathcal{C}(S) = \Big\{(c,d,\mathbf{u}) \;:\; 0\le c,d\le\bar p,\; \mathbf{u}\ge 0,\; \text{(power headroom)},\;\text{(EH-up)},\;\text{(EH-dn)},\; 0\le S + (\eta_c c - d/\eta_d)\Delta t\le E^{\max}\Big\}$$

is a polyhedron in $(S,c,d,\mathbf{u})$ jointly, since every constraint is affine in those variables. The reward $P(d-c) - c_{\text{deg}}(c+d) - c_{\text{deg}}\sum\phi_k u^k + \sum P^k u^k$ is linear. The successor state $S^+ = S + (\eta_c c - d/\eta_d)\Delta t$ is affine in $(S,c,d)$.

Since $V_{h+1}$ is concave and the map into it is affine, $V_{h+1}(S^+,\mathbf{x}')$ is concave in $(S,c,d)$ — **no monotonicity of $V_{h+1}$ is required**, because concavity is preserved under composition with an affine map regardless of monotonicity. Expectation over $\mathbf{x}'$ is a nonnegative combination, preserving concavity. The sum of a linear reward and a concave continuation is concave in $(S,c,d,\mathbf{u})$ jointly. Finally, partial maximisation of a jointly concave function over a convex feasible set that is itself defined by joint affine constraints yields a concave function of the remaining variable. Hence $V_h(\cdot,\mathbf{x})$ is concave. ∎

The induction bottoms out because value iteration can be initialised at $V^{(0)}\equiv 0$, which is concave, and Proposition 1 shows concavity is preserved by each application of the Bellman operator; the fixed point is therefore concave as a pointwise limit of concave functions.

**Corollary (Monotone bid curve).** $V_h$ concave in $S$ $\Rightarrow$ $\widetilde V_h$ concave in $S^+$ (expectation of concave) $\Rightarrow$ $\mu_h$ nonincreasing in $S^+$. The fuller the battery, the less an additional MWh is worth; the offer curve is monotone increasing in quantity, as a well-formed market offer must be. **Verifying monotonicity of the computed $\mu$ is a correctness test on the implementation**, and it will fail if §IV.8's interpolation rule is violated.

**Proposition 2 (Monotonicity of $V$ is *not* guaranteed).** It is tempting to assert $V_h$ is nondecreasing in $S$. It is not, in general. At $S$ near $E^{\max}$ with a sufficiently negative price anticipated, holding more energy is a liability because it forecloses profitable charging. So $\mu_h < 0$ is possible. **This is worth stating honestly rather than assuming away**, and it is checkable: report the fraction of $(h,S^+,\mathbf{x})$ cells with $\mu < 0$ and the price conditions under which they occur.

**Proposition 3 (The complementarity relaxation is exact where $\mu\ge 0$).** Suppose an optimal solution to the relaxed problem has $\min(c,d) = \delta > 0$. Reduce both by $\delta$.

*Reward:* $P(d-c)$ is unchanged; $-c_{\text{deg}}(c+d)$ increases by $2c_{\text{deg}}\delta\Delta t$.

*State:* $S^+$ changes by $-\eta_c\delta\Delta t + \delta\Delta t/\eta_d = \delta\Delta t\big(1/\eta_d - \eta_c\big) > 0$, since $\eta_d<1<1/\eta_c$.

*Constraints:* reducing both $c$ and $d$ relaxes the power headroom constraints; the increase in $S^+$ relaxes (EH-up) and tightens (EH-dn), so the argument requires (EH-dn) slack or $u^{\text{dn}}=0$.

Therefore the reduced action changes total value by $2c_{\text{deg}}\delta\Delta t + \mu\,\delta\Delta t(1/\eta_d-\eta_c) \ge 0$, strictly positive if $c_{\text{deg}}>0$ or $\mu>0$. So simultaneous charge and discharge is weakly dominated, and strictly dominated under the stated conditions. ∎

**Note the exact conditions.** The relaxation requires $\eta_c\eta_d < 1$ (otherwise the state term vanishes) and $\mu \ge 0$ (see Proposition 2) or $c_{\text{deg}}>0$. Rather than assume it, **assert it in code**: after every solve, check $\min(c_t,d_t) = 0$ for all $t$ and raise if violated. Reporting that this check exists is a small but real signal.

## IV.8 Discretisation, and the trap that silently destroys concavity

Discretise $S$ on a uniform grid $\{S_0,\dots,S_{N_S}\}$ with spacing $\Delta S = E^{\max}/N_S$.

The transition $S^+ = S + \Phi(g)\Delta t$ generally does **not** land on a grid point. There are two ways to handle this and only one is correct.

**Wrong: nearest-neighbour rounding.** Snapping $S^+$ to the nearest node introduces a bias of order $\Delta S/2$ in the state, destroys concavity of the discretised value function, and will make the monotonicity test of §IV.7 fail for reasons unrelated to any real bug. This is the default thing people do and it is why their bid curves are ragged.

**Correct option (a): linear interpolation.** If $S^+\in[S_j, S_{j+1}]$, set $\widetilde V(S^+) = (1-w)\widetilde V(S_j) + w\widetilde V(S_{j+1})$ with $w = (S^+-S_j)/\Delta S$. The piecewise-linear interpolant of a concave function sampled on a grid is concave (the interpolant is the pointwise infimum-free chord construction; each chord lies below the function and slopes are nonincreasing across intervals), so concavity is preserved exactly.

**Correct option (b), preferred: grid-aligned actions.** Choose the action grid so that every admissible $g$ maps $S$ exactly onto a grid point:

$$g \in \Big\{\, \tfrac{-m\,\Delta S}{\eta_c\Delta t} \;:\; m=0,\dots \Big\} \cup \Big\{\, \tfrac{m\,\eta_d\Delta S}{\Delta t} \;:\; m = 0,\dots \Big\} \;\cap\; [-\bar p,\bar p]$$

Then no interpolation is needed, the dynamic program is exact on the grid, and concavity holds by Proposition 1 without qualification. This is simpler and faster. **Adopt (b).**

**Discretisation error.** With grid-aligned actions the only approximation is that the true optimal $g^\star$ may lie between admissible levels. Since the objective is concave in $g$ and the admissible set is a $\Delta S$-net of the feasible interval in state space, the value loss is bounded by

$$0 \;\le\; V^{\text{true}} - V^{\text{grid}} \;\le\; \sup_h \big|\mu_h\big|\cdot \Delta S$$

per interval, giving a total bound proportional to $\Delta S$. **Report the empirical version**: solve at $N_S \in \{50,100,200,400\}$ and show the headline answer converging. If it has not converged, the grid is too coarse and the result is not reportable.

## IV.9 The 24-periodic fixed point — and why the terminal-value problem disappears

Let $\mathcal{T}_h$ denote the Bellman operator at time-of-day index $h$:

$$(\mathcal{T}_h W)(S,\mathbf{x}) \;=\; \max_{a\in\mathcal{A}(S)}\Big\{ r(S,\mathbf{x},a) + \mathbb{E}\big[W(S^+,\mathbf{x}')\mid\mathbf{x}\big]\Big\}$$

and let $H$ be the number of intervals in a day ($H=96$ at $\Delta t = 1/4$ h). Define the **daily operator**

$$\mathcal{T} \;=\; \mathcal{T}_0\circ\mathcal{T}_1\circ\cdots\circ\mathcal{T}_{H-1}$$

**[Assumption A4 — periodic stationarity.]** After deseasonalisation, the conditional law of $\mathbf{x}_{t+1}$ given $\mathbf{x}_t$ depends on $t$ only through $h_t = t \bmod H$. **Consequence of failure:** the fixed point is a policy for a market whose diurnal structure is stable, and seasonal drift (summer vs. winter) is not captured; mitigate by fitting and solving separately by season and reporting both.

**Solve $V^\star = \mathcal{T}V^\star - H\rho\mathbf{1}$ by relative value iteration:**

1. Initialise $W^{(0)} \equiv 0$.
2. $\widehat W^{(n+1)} \leftarrow \mathcal{T}W^{(n)}$.
3. $\rho^{(n+1)} \leftarrow \widehat W^{(n+1)}(s_{\text{ref}})$ for a fixed reference state $s_{\text{ref}}$.
4. $W^{(n+1)} \leftarrow \widehat W^{(n+1)} - \rho^{(n+1)}\mathbf{1}$.
5. Stop when $\mathrm{span}\big(W^{(n+1)}-W^{(n)}\big) := \max(\cdot) - \min(\cdot) < \varepsilon$.

**Convergence.** Under [A2] (unichain) the relative value iteration operator is a span-contraction, so $W^{(n)}$ converges to the bias $V^\star$ up to an additive constant and $\rho^{(n)}\to\rho^\star$, the optimal average reward per day. Convergence is geometric in the span seminorm; empirically a few tens of daily sweeps.

**Three things this buys.**

1. **There is no terminal condition to choose.** The prior plan flagged terminal value as "a real implementation trap" and left it unresolved, offering three options. The fixed point *is* the resolution: the value function is self-consistent across the day boundary by construction, and the artificial end-of-day emptying behaviour that a poorly chosen salvage value produces cannot occur.
2. **Compute drops by roughly two orders of magnitude** relative to an 8,760-interval (or 35,040-interval) finite-horizon pass, because you store $H$ value functions rather than $T$.
3. **A finite-horizon result, if wanted, uses the converged $V^\star$ as its terminal condition.** That is what production systems do, and saying so is a domain signal.

**Verification.** After convergence, check the Bellman residual $\max_{s}\big|\rho + V^\star_h(s) - (\mathcal{T}_hV^\star)(s)\big| < \varepsilon$ at every state and every $h$. This is a real correctness test and it catches indexing errors that produce plausible-looking but wrong policies.

## IV.10 Ancillary services priced on a common basis

Now include $\mathbf{u}$. Attach multipliers:

| Constraint | Multiplier |
|---|---|
| $g + \sum_{\mathcal{K}^{\text{up}}}u^k \le \bar p$ | $\omega^{\text{up}}_t \ge 0$ |
| $-g + \sum_{\mathcal{K}^{\text{dn}}}u^k \le \bar p$ | $\omega^{\text{dn}}_t \ge 0$ |
| (EH-up): $S^+ - S^{\min} \ge \tfrac{1}{\eta_d}\sum_{\mathcal{K}^{\text{up}}}\tau_k u^k$ | $\psi^{\text{up}}_t \ge 0$ |
| (EH-dn): $E^{\max}-S^+ \ge \eta_c\sum_{\mathcal{K}^{\text{dn}}}\tau_k u^k$ | $\psi^{\text{dn}}_t \ge 0$ |

**Derivation of the offer condition.** The Karush–Kuhn–Tucker stationarity condition in $u^k$ for an upward product $k$, at an interior optimum, reads

$$\underbrace{P^{k,RT}_t}_{\text{revenue}} \;-\; \underbrace{c_{\text{deg}}\phi_k}_{\text{throughput}} \;-\; \underbrace{\omega^{\text{up}}_t}_{\text{power}} \;-\; \underbrace{\psi^{\text{up}}_t\frac{\tau_k}{\eta_d}}_{\text{energy headroom}} \;-\; \underbrace{\rho_k(\mathbf{x}_t)\,\tau_k\Big(\frac{\mu_t}{\eta_d} - P^{RT}_t\Big)}_{\text{expected deployment}} \;=\; 0$$

so the operator should offer product $k$ if and only if

$$\boxed{\;P^{k,RT}_t \;>\; \omega^{\text{up}}_t \;+\; \psi^{\text{up}}_t\frac{\tau_k}{\eta_d} \;+\; c_{\text{deg}}\phi_k \;+\; \rho_k(\mathbf{x}_t)\,\tau_k\Big(\frac{\mu_t}{\eta_d} - P^{RT}_t\Big)\;} \tag{AS}$$

**Read (AS) carefully; it is the conceptual spine of the project.**

- $\omega^{\text{up}}_t$ is the shadow price of *instantaneous power capability*. It is zero whenever the battery is not power-constrained.
- $\psi^{\text{up}}_t$ is the shadow price of *stored energy pledged as reserve*. It is zero whenever SOC is abundant relative to obligations, and strictly positive when RTC+B's energy-headroom requirement binds. **This is the object Question Q2 asks for.**
- The factor $\tau_k/\eta_d$ says a product's energy cost scales with its duration requirement. RRS–FFR at 15 minutes costs one-sixteenth the energy headroom of Non-Spin at 4 hours. When RTC+B halved RRS and Regulation duration requirements and cut ECRS from 2 h to 1 h, it directly halved (or quartered) this term for those products. **That is the mechanism by which RTC+B re-priced duration.**
- The deployment term is the adverse-correlation term: $\rho_k$ is largest exactly when $P^{RT}_t$ is largest, and $\mu_t/\eta_d - P^{RT}_t$ is most negative then. Modelling $\rho_k$ as an unconditional constant destroys this structure.

**All products are priced against one another through a single object, $\mu_t$, plus two scarcity multipliers.** That is what co-optimisation means, and it is what the value function supplies.

## IV.11 The duration-value curve — Q3, and its identity with Q2

**Claim.** The marginal value of energy capacity is the sum, over the horizon, of the multipliers on the constraints in which $E^{\max}$ appears:

$$\boxed{\;\frac{\partial \mathcal{V}^\star}{\partial E^{\max}} \;=\; \sum_t \Big(\bar\lambda_t \;+\; \psi^{\text{dn}}_t\Big)\;}$$

where $\bar\lambda_t\ge 0$ is the multiplier on $S_t \le E^{\max}$ and $\psi^{\text{dn}}_t$ is as in §IV.10.

**Derivation.** $E^{\max}$ enters the optimisation in exactly two places: the upper SOC bound $S_t \le E^{\max}$, and (EH-dn), $E^{\max}-S^+_t \ge \eta_c\sum\tau_k u^k_t$. By the envelope theorem (equivalently, by LP sensitivity analysis on the perfect-foresight problem of §IV.12), the derivative of the optimal value with respect to a right-hand-side parameter equals the sum of the multipliers on the constraints in which it appears, weighted by $\partial(\text{RHS})/\partial E^{\max}=1$ in both cases. ∎

**Consequences.**

1. **Q2 and Q3 are the same computation.** The shadow price of the SOC–duration coupling *is* the mechanism generating the duration curve. One build, two results, and each validates the other.
2. **Duration is $E^{\max}/\bar p$**, so at fixed power rating the derivative with respect to duration is $\bar p\sum_t(\bar\lambda_t + \psi^{\text{dn}}_t)$.
3. **This gives a free and strong correctness test.** Sweep $E^{\max}$, re-solve at each value, and compute the finite difference of the optimal value. Separately, at each $E^{\max}$, sum the multipliers. The two must agree to within discretisation error. If they do not, there is a bug in the multiplier extraction or the sweep. Almost nobody does this and it is exactly the kind of check that distinguishes a careful implementation.

**The natural experiment.** Recompute the curve under the pre-RTC+B duration requirements ($\tau_{\text{ECRS}}=2$ h, $\tau_{\text{RRS}}=\tau_{\text{Reg}}=1$ h) and under the current ones ($1$ h, $0.5$ h, $0.5$ h, with RRS–FFR at $0.25$ h), holding prices fixed. The difference isolates the effect of the *rule change* from the effect of *price changes*. That is a clean identification of a mechanism, and it is what makes this more than a parameter sweep.

**[Assumption A5 — price-taking.]** The sweep holds prices fixed as $E^{\max}$ varies. Valid for a single asset; invalid for a fleet. §XII.1 gives the sensitivity treatment.

## IV.12 The perfect-foresight linear program and the dual recursion

**The program.** With all prices known,

$$\max_{\{c_t,d_t,S_t\}}\;\; \sum_{t=1}^{T}\Big[P_t(d_t-c_t) - c_{\text{deg}}(c_t+d_t)\Big]\Delta t$$

subject to, for all $t$,

$$S_{t+1} - S_t - \eta_c c_t\Delta t + \tfrac{1}{\eta_d}d_t\Delta t = 0 \qquad [\mu_t]$$
$$S_t \le E^{\max}\;[\bar\lambda_t],\qquad -S_t\le 0\;[\underline\lambda_t],\qquad c_t\le\bar p,\; d_t\le\bar p,\; c_t,d_t\ge 0$$

This is a linear program — linear objective, affine constraints — solvable for a full year in seconds with HiGHS.

**Dual recursion.** Lagrangian stationarity with respect to $S_t$ for $1\le t\le T-1$: the variable $S_t$ appears with coefficient $-1$ in balance constraint $t$ and $+1$ in balance constraint $t-1$, plus the bound multipliers. Hence

$$\boxed{\;\mu_{t-1} \;=\; \mu_t \;+\; \bar\lambda_t \;-\; \underline\lambda_t\;}$$

**Interpretation, and it is a good one.** When neither SOC bound binds, $\bar\lambda_t=\underline\lambda_t=0$ and $\mu_{t-1}=\mu_t$: **the marginal value of stored energy is constant across time.** Energy is freely transportable through time when the battery is neither full nor empty, so under perfect foresight there is one price of energy for the whole unconstrained stretch, and $\mu$ steps only where a bound binds. That single sentence explains the entire shape of a battery's optimal dispatch and is derivable in thirty seconds on a whiteboard.

**Stationarity in $d_t$.** With $\nu^d_t\ge 0$ the multiplier on $d_t\le\bar p$:

$$(P_t - c_{\text{deg}})\Delta t - \frac{\mu_t}{\eta_d}\Delta t - \nu^d_t = 0$$

so $d_t>0$ requires $P_t - c_{\text{deg}} \ge \mu_t/\eta_d$ — **the identical inequality to (D)**. The DP threshold and the LP optimality condition are the same statement; the only difference is informational.

## IV.13 The value of information decomposition

Let

- $\mathcal{V}^{\text{PF}}$ = perfect-foresight optimum (the LP),
- $\mathcal{V}^{\text{DP}}$ = expected value of the exactly-solved policy under the *learned* model, realised on out-of-sample data,
- $\mathcal{V}^{\text{MPC}}$ = realised value of the certainty-equivalent receding-horizon policy,
- $\mathcal{V}^{\text{heur}}$ = realised value of a fixed-threshold heuristic.

Then

$$\underbrace{\mathcal{V}^{\text{PF}} - \mathcal{V}^{\text{DP}}}_{\text{value of information}} \;+\; \underbrace{\mathcal{V}^{\text{DP}} - \mathcal{V}^{\text{MPC}}}_{\text{option value}} \;+\; \underbrace{\mathcal{V}^{\text{MPC}} - \mathcal{V}^{\text{heur}}}_{\text{value of optimisation}} \;=\; \mathcal{V}^{\text{PF}} - \mathcal{V}^{\text{heur}}$$

**Value of information** is what is unattainable purely because the future is unknown, as distinct from what is unattainable because of physical constraints. **Option value** is what certainty equivalence discards: MPC substitutes a point forecast for a distribution, so it will not hold charge in anticipation of a low-probability, high-magnitude spike, because the point forecast does not contain the spike. The payoff is convex in price, so the expected price is not the price that matters.

**The testable hypothesis (Q4, demoted).** The option-value term should increase with volatility and spike frequency. Report it stratified by regime.

**The honest caveat.** $\mathcal{V}^{\text{DP}}$ is realised under a *learned* model, so $\mathcal{V}^{\text{DP}} - \mathcal{V}^{\text{MPC}}$ conflates genuine option value with the difference in model quality between a distributional forecaster and a point forecaster. To separate them, run MPC using the *mean* of the same learned distribution. Then the comparison is clean: same information, different treatment of uncertainty.

## IV.14 Complexity

Let $N_S$ be SOC levels, $N_X$ exogenous states, $N_A$ action levels, $H$ intervals per day, $M$ value-iteration sweeps.

**Naive** (expectation recomputed inside the action loop): $O(M\,H\,N_S\,N_X\,N_A\,N_X)$.

**Correct** (precompute the expectation as one matrix multiply per sweep, then maximise):

$$\underbrace{O\big(M\,H\,N_S\,N_X^2\big)}_{\text{expectation}} \;+\; \underbrace{O\big(M\,H\,N_S\,N_X\,N_A\big)}_{\text{maximisation}}$$

At $N_S=200$, $N_X=200$, $N_A=41$, $H=96$, $M=40$: expectation $\approx 3.1\times10^{10}$ multiply-adds — but as a dense matrix product it is a single BLAS call per $(h,\text{sweep})$ and runs in seconds; maximisation $\approx 6.3\times10^9$, vectorised over states.

**Be able to state both counts and explain why loop ordering matters.** The prior plan's count omitted the expectation entirely, which is the dominant term. Getting the count wrong in interview undoes the entire methodological argument, since "I computed the size of the state space and determined an exact method was available" is the sentence the stance rests on.

---

# PART V — THE LEARNED PRICE MODEL

## 22. Why this is required, not optional

The Bellman equation contains

$$\mathbb{E}\big[V_{h+1}(S^+,\mathbf{x}_{t+1})\,\big|\,\mathbf{x}_t\big] \;=\; \sum_{\mathbf{x}'} \mathbb{P}\big(\mathbf{x}_{t+1}=\mathbf{x}'\mid\mathbf{x}_t\big)\,V_{h+1}(S^+,\mathbf{x}')$$

The dynamic program is **structurally incapable of running** without an estimate of the conditional distribution $\mathbb{P}(\mathbf{x}_{t+1}\mid\mathbf{x}_t)$. Estimating a conditional distribution from data, with held-out evaluation and calibration diagnostics, is machine learning in the strict sense — the question being answered is *will this fitted conditional distribution hold on data it has not seen*, which is the generalisation question and the entire content of the field.

This matters for two separate reasons. It is the correct thing to build. And it is the only component of the project that constitutes genuine ML, which is relevant if this artifact is to serve applications beyond a single employer.

## 23. What is being predicted

Not a point forecast. A **conditional predictive distribution** of the real-time settlement price at horizon $\ell$:

$$\widehat F_{t+\ell\mid t}(\cdot) \;\approx\; \mathcal{L}\big(P^{RT}_{t+\ell}\;\big|\;\mathbf{f}_t\big)$$

where $\mathbf{f}_t$ is the full feature vector — hour, day type, month, lagged prices, load forecast and its vintage, wind and solar forecasts and their vintages, net load, forecast error, reserve margin, resource outage capacity. Note $\mathbf{f}_t$ is much richer than the tabulated state $\mathbf{x}_t$ of §III.14: the features drive the *estimation*; the tabulated state is where the estimate is *evaluated*.

## 24. Method: quantile regression, and why the loss recovers the quantile

Fit a set of conditional quantiles $\{\widehat q_\alpha(\mathbf{f}_t)\}_{\alpha\in\mathcal{A}}$ for a grid of levels $\mathcal{A}\subset(0,1)$, using gradient-boosted trees with the **pinball loss**

$$\rho_\alpha(u) \;=\; u\big(\alpha - \mathbb{1}\{u<0\}\big) \;=\; \begin{cases}\alpha u & u\ge 0\\ (\alpha-1)u & u<0\end{cases}$$

**Theorem.** $\arg\min_q \mathbb{E}\big[\rho_\alpha(Y-q)\big] = F_Y^{-1}(\alpha)$.

**Proof.** Write

$$L(q) = \alpha\!\int_q^\infty (y-q)\,dF(y) \;+\; (1-\alpha)\!\int_{-\infty}^q (q-y)\,dF(y)$$

Differentiate under the integral (Leibniz; the boundary terms vanish because the integrands are zero at $y=q$):

$$L'(q) = -\alpha\big(1-F(q)\big) + (1-\alpha)F(q) = F(q) - \alpha$$

Setting $L'(q)=0$ gives $F(q)=\alpha$. Since $L''(q) = f(q)\ge 0$, $L$ is convex and the stationary point is the global minimum. ∎

**Why this rather than fitting a parametric jump-diffusion.** Electricity prices are heavy-tailed, asymmetric, occasionally negative, capped above, and heteroskedastic in a way that depends on physically observable conditions (net load relative to available capacity). A parametric form imposes shape assumptions on precisely the region — the right tail — where the economics lives and where the sample is thinnest. Quantile regression imposes no distributional shape and lets the tail be whatever the data plus the physical conditioning say it is. The parametric mean-reverting jump-diffusion is retained as a **baseline to beat**, not as the model.

**Monotonicity.** Independently fitted quantiles can cross. Enforce monotonicity by isotonic rearrangement of $\{\widehat q_\alpha\}$ in $\alpha$ at each $\mathbf{f}_t$; rearrangement is guaranteed not to increase the pinball loss.

## 25. Evaluation: proper scoring rules

A scoring rule $S(F,y)$ is **proper** if the expected score is optimised by reporting the true distribution: $\mathbb{E}_{Y\sim G}[S(G,Y)] \le \mathbb{E}_{Y\sim G}[S(F,Y)]$ for all $F$. Propriety is what prevents a forecaster from gaming the metric by hedging.

**Continuous Ranked Probability Score.**

$$\text{CRPS}(F,y) \;=\; \int_{-\infty}^{\infty}\big(F(z) - \mathbb{1}\{z\ge y\}\big)^2\,dz$$

**Identity (proved by Fubini and the pinball theorem above).**

$$\text{CRPS}(F,y) \;=\; 2\int_0^1 \rho_\alpha\big(y - F^{-1}(\alpha)\big)\,d\alpha$$

so **CRPS is the pinball loss integrated over quantile levels**. Training on pinball loss at a grid of levels is therefore a discretisation of training on CRPS, and the two are consistent. This is worth being able to state.

**Calibration by the probability integral transform.** If $Y\sim F$ with $F$ continuous, then $U := F(Y)\sim\text{Uniform}(0,1)$.

*Proof:* $\mathbb{P}(U\le u) = \mathbb{P}(F(Y)\le u) = \mathbb{P}(Y \le F^{-1}(u)) = F(F^{-1}(u)) = u$. ∎

So compute $\widehat u_t = \widehat F_{t\mid t-\ell}(y_t)$ on held-out data and histogram it. **A flat histogram means calibrated.** A U-shape means the forecast is *underdispersed* (too confident — outcomes land in the tails too often). A hump means *overdispersed*. A leftward or rightward tilt means biased. Report the histogram and a Kolmogorov–Smirnov statistic against uniform.

**The critical point for this project: an underdispersed price forecast is the single most dangerous failure mode.** The DP's willingness to hold charge for a spike is driven entirely by the right tail of $\widehat F$. Understate the tail and the policy degenerates toward MPC; overstate it and the policy hoards and never trades. **The calibration diagnostic is therefore not a side check — it is a direct diagnostic of the policy's economic behaviour**, and connecting the two explicitly is one of the more sophisticated things this project can say.

## 26. From predictive distribution to transition matrix

The DP needs $\mathbb{P}(\mathbf{x}_{t+1}\mid\mathbf{x}_t)$ on the tabulated state, not $\widehat F$ on the raw price. Construct it:

1. Fit the seasonal component $m(h,\text{daytype},\text{month})$ **inside each walk-forward fold** (see §VIII.3 — fitting it once globally is a leak).
2. Define bin edges on the deseasonalised residual using **non-uniform, log-spaced bins in the right tail**. Uniform bins collapse the entire spike region into one cell and the DP will never see the option value it exists to capture. Choose edges as empirical quantiles of the training fold, refined above the 95th percentile.
3. For each tabulated state $\mathbf{x} = (h,b,z)$, form the transition row by integrating the fitted predictive distribution over the successor bins, conditional on the features that characterise cell $\mathbf{x}$: $T^{(h)}[\mathbf{x},\mathbf{x}'] = \widehat F_{t+1\mid t}(\text{upper edge of }b') - \widehat F_{t+1\mid t}(\text{lower edge of }b')$, averaged over the training observations falling in cell $\mathbf{x}$.
4. **Transition matrices must be hour-indexed.** Residual volatility and spike intensity are strongly hour-dependent; a single pooled matrix is misspecified in a way that directly damages the evening-peak policy.
5. Verify each row sums to one and the chain is irreducible (required by [A2]).

**Baseline for comparison.** The purely empirical count-based transition matrix (count observed transitions between bins, normalise). This is nonparametric and robust and may well be adequate. Build it first, and only adopt the learned model if it wins on held-out CRPS *and* produces a better realised capture rate. **A negative result here — "the empirical matrix was as good as the learned model" — is a publishable-quality finding about the market, not a failure.**

---

# PART VI — THE RESEARCH QUESTIONS

## Q3 (headline) — What is a marginal hour of storage duration worth under RTC+B?

**Statement.** For a battery of fixed power rating $\bar p$ operating optimally at a given settlement point over the post-launch period, compute realised value as a function of duration $E^{\max}/\bar p$ across $\{0.5, 1, 2, 3, 4, 6, 8\}$ hours, and report the marginal value curve $\partial\mathcal{V}/\partial(\text{duration})$.

**Deliverables.**
1. **Two curves, not one** — see the confound treatment below. $\mathcal{V}^{\text{PF}}(E^{\max})$ and $\mathcal{V}^{\pi}(E^{\max})$, each with a confidence band from §VIII.5.
2. **The capture-rate curve** $\kappa(E^{\max}) = \mathcal{V}^{\pi}(E^{\max})/\mathcal{V}^{\text{PF}}(E^{\max})$.
3. The same curves computed under pre-RTC+B duration requirements, holding prices fixed — isolating the rule change from the price change.
4. Decomposition into the energy-arbitrage contribution and the ancillary-headroom contribution, via §IV.11's identity.
5. The finite-difference-versus-multiplier-sum consistency check.

**Resolving the control-difficulty confound.** A realised duration curve mixes two distinct effects: how much the market pays for duration, and how much harder a longer battery is to control well. A four-hour asset has a larger state space, longer-horizon dependencies, and a policy more sensitive to forecast quality, so its capture rate may be lower for reasons having nothing to do with market rules. **The separation requires no additional experiment**, only reporting both curves:

- $\mathcal{V}^{\text{PF}}(E^{\max})$ is computed under perfect foresight and therefore contains *zero* control difficulty. It is the pure market signal.
- $\mathcal{V}^{\pi}(E^{\max})$ contains both the market signal and the control difficulty.
- $\kappa(E^{\max})$ isolates the second. **If $\kappa$ is flat in duration there is no confound. If $\kappa$ declines, that is itself a finding** — longer duration is worth more but harder to capture, so the realised premium is smaller than the theoretical one. An operator cares about this more than about either curve alone, and both numerator and denominator are already being computed for the sweep.

**Fleet context for interpreting the answer.** ERCOT entered 2026 with 13,888 MW / 22,853 MWh operational — a fleet-average duration of 1.65 hours, up from 1.5 h a year earlier, with systems above 2.5 h still rare (112 MW commissioned during 2025) but four-hour projects nearing completion. The fleet is effectively bimodal: a large legacy stock of one-hour units built for ancillary services, a growing two-hour cohort, and a thin four-hour tail about to thicken. The curve should be read against that distribution.

**A forward-looking discontinuity worth naming.** ERCOT's forthcoming Dispatchable Reliability Reserve Service (DRRS) is expected to carry a **four-hour** duration requirement. If the curve shows the marginal value of the third and fourth hours is currently near zero under RTC+B's relaxed requirements, while DRRS would switch on a new revenue stream at exactly four hours, that is a sharp and directly investment-relevant finding: **the current rules and the announced rules value duration in opposite directions.**

**Why the answer is interesting either way.** If the curve is steep, RTC+B rewarded duration and the industry's push toward longer assets is validated by the market rules. If it is flat beyond two hours, the duration-requirement reductions largely eliminated the marginal value of the third and fourth hour — which would be a direct and surprising commentary on the current investment thesis, sharpened by the DRRS point above.

## Q2 (mechanism) — What does RTC+B's state-of-charge enforcement cost?

**Statement.** Report the distribution over time of $\psi^{\text{up}}_t$ and $\psi^{\text{dn}}_t$ — the shadow prices of the energy-headroom constraints — by hour, by season, and stratified by scarcity regime. Report the fraction of intervals in which each binds, and the implied revenue foregone.

This is the mechanism generating Q3 and it is computed in the same solve. It also answers, directly, the question every ERCOT storage operator has been asking since December: *how much is the new SOC enforcement actually costing me?*

## Q1 (secondary) — The day-ahead / real-time ancillary basis

**Statement.** Day-ahead ancillary has generally cleared above real-time since RTC+B launched — real-time cleared below day-ahead roughly 93% of the time in the first month — yet the basis is dominated by rare reversals: in one observed month, a single real-time spike converted a large positive cumulative basis into a negative one. Given this, what day-ahead/real-time allocation does an optimal SOC-aware policy choose, and how does the answer change under the risk-aware objective of Part VII?

**Why it is not trivially "always sell day-ahead."** Because the imbalance settlement of §II.11 means a day-ahead position is a *short* real-time option: you owe the real-time price on any shortfall. Selling day-ahead harvests a premium and sells tail exposure. That is exactly the structure the retail book already has (§II.12), so the two exposures compound rather than diversify. Under expected value the answer may be "sell day-ahead"; under CVaR it may not. **The divergence between the two answers is the result.**

**The structural feature that makes this more than a spread trade.** Per §II.10 item 7 and §II.11, ERCOT does **not** enforce state of charge in day-ahead clearing, only in real time. The day-ahead ancillary position is therefore not bounded by the physical constraint (EH-up) at all — a resource can sell more ancillary capability day-ahead than it could ever deliver, and settle the difference at the real-time MCPC. The optimisation this creates is genuinely two-stage:

$$\max_{\mathbf{u}^{DA}} \;\Big\{\underbrace{\textstyle\sum_k P^{k,DA}_t u^{k,DA}_t}_{\text{unconstrained by SOC}} \;+\; \mathbb{E}\big[\,\mathcal{V}^{RT}\big(S_t,\mathbf{x}_t;\,\mathbf{u}^{DA}\big)\big]\Big\}$$

where the real-time value function $\mathcal{V}^{RT}$ *is* SOC-constrained and absorbs the buy-back cost. **Report the optimal day-ahead ancillary position as a multiple of physically deliverable capability**, under both the expected-value and the CVaR objectives. A ratio above one is the model telling you the market pays to sell capability you do not have; how far above one, and how fast it falls as risk aversion rises, is the deliverable.

**Caveat to state plainly:** overselling is bounded in practice by credit requirements, ERCOT's capacity-short RUC calculations, and Protocol obligations that this model does not represent. The result is the *unconstrained economic* optimum, and the gap between it and what a real operator would do is itself worth a paragraph.

## Q5 (risk chapter) — The retailer-plus-battery objective

**Statement.** For an operator whose obligation includes serving load at a fixed retail rate, how much expected arbitrage profit should be forgone to keep the fleet charged into scarcity, and what is the efficient frontier in (expected profit, tail risk) space?

Construct a synthetic retail book from public ERCOT load-zone load shapes scaled to a stated customer count, at a stated fixed retail rate. Total profit becomes

$$\Pi \;=\; \underbrace{\Pi^{\text{battery}}}_{\text{dispatch}} \;+\; \underbrace{\sum_t\big(R^{\text{retail}} - P^{RT}_t\big)L_t\Delta t}_{\text{retail margin}}$$

and the risk-aware objective of §VII.4 is applied to $\Pi$, not to $\Pi^{\text{battery}}$ alone.

**Why this is the sharpest question available for this employer.** It also makes CVaR load-bearing: the optimal dispatch under the joint objective is genuinely different from the standalone one, and quantifying that difference is the first deliverable.

**Note the two positions are one entity by regulatory construction, not by choice.** Under ERCOT's ADER framework an aggregation must consist of premises within a single Load Zone sharing the same Load Serving Entity, which in practice makes the retail provider the aggregator. Being a retailer is therefore a *prerequisite* for aggregating residential batteries into the wholesale market, not a separate line of business. The joint objective is the correct one on structural grounds, not merely as a modelling convenience.

### Q5b — The hedging extension

The role's *Risk & Trading* responsibilities name identifying and assessing new products and contract structures, and automating their valuation. Nothing else in this project addresses that. **The correct response is to extend Q5 by one step rather than to build a separate artifact**, because the substantive question is not "what should be hedged" — it is *given that a large physical hedge is already owned, what residual exposure remains and is financial protection on it worth the cost?*

There are three channels for removing tail risk, and a quantitative treatment must price them on a common basis:

| Channel | Mechanism | Cost |
|---|---|---|
| **Physical** | Hold charge into scarcity instead of arbitraging | Forgone expected arbitrage profit |
| **Financial** | Buy a forward strip or a call on the settlement point price | Option premium / forward risk premium (§II.8) |
| **Contractual** | Time-of-use rates, critical-peak pricing, dispatch-rights-for-discount | Reduced retail margin, customer acquisition friction |

**Deliverables, in order.**

1. **Residual tail.** Compute $\text{CVaR}_\alpha(\Pi)$ at the risk-optimal dispatch from Q5 — i.e. after the physical hedge has already done its work. This is the exposure that actually needs hedging, and it is much smaller than gross exposure.
2. **Price a simple overlay.** Value a forward strip, and a strike-$K$ call on the real-time settlement point price at notional matching the load, against the empirical distribution. Use the measure-change framing of §II.8: the premium *is* the gap between $\mathbb{Q}$ and $\mathbb{P}$, so pricing the hedge and measuring the forward premium are the same exercise.
3. **The headline number: the marginal cost of tail reduction by channel.**

$$\boxed{\;\text{MCTR}_j \;=\; \frac{\partial\,\mathbb{E}[\Pi]}{\partial\,\text{CVaR}_\alpha(\Pi)}\bigg|_{\text{channel }j}\;}$$

Dollars of expected profit surrendered per dollar of tail risk removed, computed for the physical and financial channels and compared. **This is the number a trading desk would want and does not have.** Report it as a function of fleet duration, since a longer fleet is a better physical hedge and should therefore need less financial protection — which, if true, closes the loop back to Q3 and gives the duration curve a second economic interpretation.

**Scope discipline.** Q5b is an extension of an existing computation, not a new pipeline: it reuses the Q5 joint distribution, the §VII.29 CVaR linear program, and the §II.8 premium measurement. It is item 8 in the build order and shipping without it is a complete result.

## Q4 (demoted, supporting) — Option value of stochastic control over certainty equivalence

Per §IV.13, with the clean comparison (MPC run on the mean of the same learned distribution) rather than the confounded one.

---

# PART VII — RISK

## 27. Why expected value is the wrong objective

Two policies with identical expected profit: one earns \$100/day steadily; the other loses \$50/day for 364 days and earns \$54,750 on one. Identical means, entirely different businesses. For an operator whose retail book can be destroyed by a single scarcity event, the distinction is existential.

## 28. Risk measures, and the definition the prior plan got wrong

**Variance.** $\text{Var}(R)=\mathbb{E}[(R-\mathbb{E}R)^2]$. Penalises upside identically to downside — inappropriate for a distribution this asymmetric.

**Value at Risk.** $\text{VaR}_\alpha(R) = \inf\{\ell : \mathbb{P}(-R\le\ell)\ge 1-\alpha\}$. Two defects: it says nothing about severity beyond the threshold, and it is **not subadditive**, so diversification can appear to increase measured risk.

**Conditional Value at Risk.** The prior plan defined this as $\mathbb{E}[-R \mid -R \ge \text{VaR}_\alpha(R)]$. **That definition is valid only when $\mathbb{P}(-R = \text{VaR}_\alpha(R)) = 0$.** Every distribution in this project is empirical, hence atomic, hence the conditional-expectation form is *not* subadditive and *not* coherent — the exact defect it was introduced to fix. Use instead:

$$\boxed{\;\text{CVaR}_\alpha(R) \;=\; \frac{1}{\alpha}\int_0^\alpha \text{VaR}_v(R)\,dv \;=\; \min_{\tau\in\mathbb{R}}\Big\{\tau + \frac{1}{\alpha}\mathbb{E}\big[(-R-\tau)^+\big]\Big\}\;}$$

CVaR so defined is **coherent**: monotone, translation-equivariant, positively homogeneous, and subadditive.

## 29. The Rockafellar–Uryasev representation, derived

**Theorem.** Let $\phi(\tau) = \tau + \frac{1}{\alpha}\mathbb{E}[(-R-\tau)^+]$. Then $\phi$ is convex, its minimiser is $\text{VaR}_\alpha(R)$, and $\min_\tau\phi(\tau)=\text{CVaR}_\alpha(R)$.

**Proof of the first two parts.** $(-R-\tau)^+$ is convex in $\tau$ for each realisation (maximum of two affine functions), so its expectation is convex, so $\phi$ is convex. Where $F_{-R}$ is differentiable,

$$\phi'(\tau) = 1 - \frac{1}{\alpha}\,\mathbb{P}(-R > \tau) = 1 - \frac{1}{\alpha}\big(1 - F_{-R}(\tau)\big)$$

Setting $\phi'(\tau)=0$ gives $\mathbb{P}(-R>\tau) = \alpha$, i.e. $\tau^\star = \text{VaR}_\alpha(R)$. (With atoms, $\phi$ has a kink and the minimiser is a subgradient-zero point, which is exactly why the general definition is the variational one.) ∎

**Why it matters computationally.** With $N$ sampled scenarios giving profits $R_1,\dots,R_N$, the empirical minimand is

$$\min_{\tau, z}\;\; \tau + \frac{1}{\alpha N}\sum_{i=1}^N z_i \qquad\text{s.t.}\qquad z_i \ge -R_i - \tau,\quad z_i\ge 0$$

which is **linear**. CVaR therefore appends directly to the existing scenario linear program as $N+1$ variables and $2N$ constraints.

## 30. The risk-aware objective and the efficient frontier

$$\max\;\; (1-\beta)\,\mathbb{E}[\Pi] \;-\; \beta\,\text{CVaR}_\alpha(\Pi), \qquad \beta\in[0,1]$$

Sweeping $\beta$ traces the **efficient frontier** in (expected profit, tail risk) space.

**Specify the unit of analysis, which the prior plan did not.** CVaR of *what* random variable, aggregated over *what* period? Daily profit, monthly, annual? The risk that matters to a retailer is annual, but only one realisation of an annual outcome exists in the sample. **Decision:** report the frontier for daily $\Pi$ as the primary (with $n\approx 228$ realisations), and a *scenario-based* annual frontier constructed from block-bootstrapped resamples of daily outcomes as a clearly labelled secondary. State explicitly that the annual frontier inherits the block bootstrap's assumptions and is not an independent measurement.

## 31. Time consistency — an unresolved limitation, stated

**CVaR does not decompose additively across time and therefore does not admit a naive Bellman recursion.** The dynamic programming principle requires an objective separable across periods; coherent risk measures generally are not. Optimising the CVaR of *total* profit is not equivalent to optimising it period by period, and a naive recursion can yield a **time-inconsistent** policy — one that, upon reaching $t+1$, prefers to deviate from what it planned at $t$.

Rigorous treatments use nested (dynamic) risk measures in the sense of Ruszczyński, or the state-augmentation approach of Bäuerle and Ott in which the CVaR threshold $\tau$ is carried as an additional state variable.

**Position taken:** implement CVaR in the **scenario-based linear program**, where it is convex and clean; retain expected value in the **dynamic program**; and state the limitation explicitly. Naming a subtlety that was identified but not solved is a stronger signal than silently avoiding it.

---

# PART VIII — EVALUATION PROTOCOL

Every item is enforced **in code**, not by intention. This section is short and it is the single largest determinant of whether the results are believed.

## VIII.1 Adaptedness

Every feature informing the decision at $t$ must have been *published* by $t$. This is subtler than it looks: 60-day disclosure is lagged 60 days; day-ahead prices become known the previous afternoon; load and renewable forecasts have vintages and are revised. **Every row in the feature store carries an explicit publication timestamp, and an automated assertion verifies that no feature used at decision time $t$ has a publication timestamp later than $t$.**

## VIII.2 Execution semantics

Per §IV.6. The decision object is an offer curve, measurable with respect to $\mathcal{F}_t$; dispatch is determined by comparing the realised clearing price to the curve. **The MPC baseline's plan is converted to an offer curve by the same rule** — offer the marginal quantity at the price implied by the horizon-LP's dual on the SOC balance constraint — so that both policies face identical execution mechanics and neither receives an information advantage. This conversion is specified in code, tested, and documented, because it is the most likely place for a subtle leak.

## VIII.3 Walk-forward, including estimation-sample leakage

Expanding-window walk-forward: fit on months $1..m$, evaluate on month $m+1$, advance. Time series are never randomly shuffled.

**And every estimated object is re-fit inside each fold** — the seasonal decomposition, the bin edges, the transition matrix, the quantile models, the deployment factors $\rho_k$, the throughput factors $\phi_k$. A single global `deseasonalize()` call before the loop leaks future information into the past and is the easiest way to silently destroy the project's credibility. **The test suite asserts that no fitted object's training indices intersect its evaluation indices.**

## VIII.4 Bracketed reporting

Every performance figure is reported against both the perfect-foresight ceiling and a naive-heuristic floor. A number without bounds is not a result.

**Capture rate** $= \mathcal{V}^\pi/\mathcal{V}^{\text{PF}}$. Report the level alongside the ratio, and **never** report a capture rate for a window in which $\mathcal{V}^{\text{PF}}$ is near zero, where the ratio is unstable and sign-ambiguous. Specify that perfect foresight is computed over the full evaluation window, not reset daily; a daily-reset ceiling is a different and lower bound and the two must not be mixed.

Reported capture rates for real ERCOT operators typically fall in the 50–80% range. A computed rate near 100% almost certainly indicates lookahead contamination; near 20% indicates a bug or misconfigured cost parameter. These function as implementation tests.

## VIII.5 Statistics for a tail-concentrated profit distribution

Profit in this market is extremely concentrated: a single day in the post-launch sample produced roughly 45% of that month's fleet-wide battery revenue. Standard inference will mislead. The protocol:

**(a) Paired differences.** Compare policies by daily paired differences $D_i = \Pi^A_i - \Pi^B_i$ over $n\approx 228$ days, not by two separately-estimated totals.

**(b) Block bootstrap, with block length as a reported sensitivity.** Serial dependence in $D_i$ invalidates the i.i.d. bootstrap. Use the stationary bootstrap with expected block length chosen by an automatic rule, and **plot the confidence interval as a function of block length**. An interval that moves substantially with block length is itself information.

**(c) A distribution-free headline statistic.** Bootstrap coverage for the *mean* degrades badly under heavy tails. Report the **sign test**: under $H_0$ of no difference, $\#\{i: D_i>0\}\sim\text{Binomial}(n,1/2)$. "Policy A beats policy B on 61% of days, $p=0.003$" is defensible when the confidence interval on $\mathbb{E}[D]$ straddles zero. **Make this the headline claim and the mean difference the secondary one.**

**(d) Concentration reporting.** The fraction of $\sum_i D_i$ contributed by the top 1 and top 5 days. Report prominently. It is a finding about the market, not an embarrassment.

**(e) Leave-one-day-out jackknife over all days**, reporting the min and max of the recomputed statistic. If removing any single day flips a sign, say so in the abstract.

**(f) A power statement.** Given the observed variance of $\{D_i\}$, what effect size was detectable at $n$? "This design could detect a difference above 8% of the perfect-foresight ceiling; smaller differences are not resolvable with this sample" is the single most credibility-enhancing sentence available, and almost nobody writes it.

### VIII.5a Three different sample sizes, and which constrains what

These are routinely conflated. They are not the same number and they constrain different claims.

| Quantity | Size | Constrains |
|---|---|---|
| Post-launch calendar days | ~228 and growing | Everything; a hard ceiling |
| 15-minute intervals | ~21,900 per settlement point | Price-model fitting, transition estimation, solving the control problem — **ample** |
| Daily paired differences | ~228 | Policy comparison (§VIII.5) — adequate |
| **Intervals in which energy headroom binds** | possibly ~2% of intervals, clustered into 10–20 scarcity days | **Q2 directly. This is the binding constraint on the project.** |

The last row is the one that matters. Even if headroom binds in 440 intervals, those cluster into a handful of days, so the *effective* sample for a statement about $\psi$ is closer to 15 than to 440. **Establishing this number is the entire purpose of the viability test in Part XIV Step 0**, and it must be measured before the dynamic program is built, because it determines whether Q2 has an answer at all.

**Why 228 days cannot be extended backwards.** RTC+B went live 5 December 2025. Before that date SCED did not enforce state of charge — the constraint whose shadow price Q2 measures **did not exist**. One cannot measure the price of a constraint using data from a period in which the constraint was absent. This is not a conservative modelling choice; it is the definition of the object.

**And why counterfactual application to pre-launch prices is invalid.** It is tempting to impose RTC+B constraints on pre-December price data to manufacture sample. This does not work, and being able to say why is worth more than the extra data would be: pre-RTC prices were formed under a different clearing mechanism, so *the prices themselves* would have been different under the new rules. The exercise measures a constraint against a price path that could not have occurred under it.

**Four legitimate ways to increase usable sample, all of which should be used.**

1. **Cross-section over settlement points.** Congestion means different nodes reach scarcity at different times. Ten nodes is not ten times the data, but it is materially more than one.
2. **Cross-section over durations.** Each duration in the Q3 sweep has a *different* binding pattern — a one-hour battery is energy-constrained far more often than a four-hour one. These are not repeated observations of the same event; they are different constraints observed under the same prices.
3. **The 60-day disclosure fleet.** Roughly 297 ESRs settled energy or ancillary revenue in ERCOT during 2026 year-to-date. That is a genuine cross-section of ~300 assets observed across the *same* scarcity days, with known power and duration. **This is the strongest available answer to the thin-sample problem and the principal reason the fleet benchmark is worth building** (build order item 7).
4. **Elapsed time.** Every day the live log runs adds a day of forward out-of-sample record. This is the reason the log is item 1 and not item 9.

## VIII.6 Structural break

Data before 5 December 2025 was generated under a different market design and is **not** naively pooled. All ancillary results use post-launch data only. Energy-only arbitrage results may optionally use the longer history, with the pooling justified explicitly and a pre/post comparison shown.

## VIII.7 Required sensitivities

- $c_{\text{deg}}\in[0,60]$ \$/MWh.
- SOC grid resolution $N_S\in\{50,100,200,400\}$ (convergence).
- State augmentation: add one price lag, re-solve, report the change (probes [A1]).
- Two settlement points.
- Both seasons where data permits.

---

# PART IX — DATA AND ENGINEERING

## IX.1 Access, and the free path

All data is public and free.

**Registration.** Create an account at `apiexplorer.ercot.com`; obtain a subscription key following `developer.ercot.com/applications/pubapi/user-guide/registration-and-authentication/`. Authentication is username/password → ID token (valid one hour, no refresh; re-POST to renew) plus an `Ocp-Apim-Subscription-Key` header. The `gridstatus` open-source library handles the token flow via environment variables.

**Two keys are required.** The 60-day disclosure ESR products sit behind a separate **ESR API** needing its own subscription key from the same account. Requesting only the public key produces 403s on the disclosure endpoints. Obtain both at the outset.

**Hard limit.** The ERCOT Public API serves data from 11 December 2023 onward. Earlier data requires manual download from ERCOT's Data Access Portal. Irrelevant here — the window begins 5 December 2025.

**The hosted `gridstatus.io` API is a paid product and is not needed.** The open-source `gridstatus` library plus your own free ERCOT keys is sufficient.

**Authoritative rule documents — read these rather than commentary.**

| Document | Location |
|---|---|
| ERCOT Nodal Protocols (current) — §8.1.1.2 RUC qualification, §8.1.1.3 real-time qualification | `ercot.com/mktrules/nprotocols/current` |
| RTC+B Battery Overview (July 2025) — duration table with protocol citations, SOC in SCED, DAM/RT asymmetry, set-point deviation | `https://www.ercot.com/files/docs/2025/07/15/RTC-B-Battery-Overview.pdf` |
| NPRR1282 — Ancillary Service Duration under RTC | ERCOT NPRR database, approved 24 June 2025 |
| NPRR1014, 1204, 1236, 1246 — the remainder of the "+B" scope | ERCOT NPRR database |
| ADER Pilot, all phases | `https://www.ercot.com/mktrules/pilots/ader` |
| ADER Phase 3 Governing Document + Phase 2 Report | `https://www.ercot.com/files/docs/2025/06/16/4.3-Aggregate-Distributed-Energy-Resource-ADER-Pilot-Project-Phase-3.pdf` |
| Single-model ESR name mapping (pre/post RTC+B resource identifiers) | `https://www.ercot.com/files/docs/2025/02/14/single-model-esr-names_16Jun2025.xlsx` |

The last row is operationally important and easy to miss: resource names **changed** at the single-model transition (a paired `X_BES1` generation resource and `X_LD1` load resource became one `X_ESR1`). Any join of pre- and post-launch disclosure data on resource name will silently fail without this mapping.

**Full reproducibility from free public sources is a credibility property, not a compromise.** The additional ingest, pagination, retry, and schema-normalisation code required is itself the software-engineering evidence the role asks for.

## IX.2 The two lags

| Stream | Lag | Post-launch window as of 20 Jul 2026 |
|---|---|---|
| Settlement point prices, real-time MCPC, ASDCs, load, wind, solar, forecasts | Minutes to hours | **~228 days** — full |
| 60-Day SCED / DAM Disclosure (per-resource offers, awards, dispatch) | 60 days | **~167 days**, growing daily |

There is no access problem in either stream. The disclosure lag simply means fleet-benchmark results always trail the price-based results by two months, and that disclosure data can never inform a live decision.

## IX.3 Data inventory

| Dataset | Purpose | Note |
|---|---|---|
| Real-time settlement point prices | Primary energy signal | 5-min and 15-min |
| Day-ahead settlement point prices | Forward price; premium measurement | Hourly |
| Real-time MCPC by SCED interval (NP6-788-RTCMT) | Post-RTC+B AS prices | **Core** |
| Real-time MCPC, 15-minute (NP4-212-CD) | Settlement-interval AS prices | **Headline AS series** |
| DAM ancillary MCPC | Day-ahead AS leg | Hourly |
| DAM and SCED Ancillary Service Demand Curves (NP5-526-CD) | The ASDCs being bid into | Rarely used by outsiders |
| Weekly / Projected RUC AS Deployment Factors | Supplies $\rho_k$ directly | Resolves §III.19 |
| Total Capability of Resources Available to Provide AS by SCED Interval | Fleet AS capability **already capped by ESR duration requirements and available SOC** | Ready-made validation target for the headroom constraints |
| System load, load forecast | Net load; conditioning | Forecast vintages matter |
| Wind and solar production and forecast | Net load; conditioning | Forecast vintages matter |
| Hourly Resource Outage Capacity | Scarcity conditioning | |
| 60-Day DAM / SCED Disclosure (incl. ESR offers, awards, dispatch) | Fleet benchmark | ESR API key; 60-day lag |

**Known breakage to budget for:** `gridstatus.get_as_prices()` raises `ValueError` for dates on or after 2025-12-06 because ERCOT's file changed at go-live. The data exists; use the post-RTC endpoints above. This will be encountered on the first day of ingest, at exactly the date of interest.

## IX.4 Repository and engineering commitments

```
ercot-storage-duration/
├── README.md                 # findings first, reproduction second
├── pyproject.toml
├── .github/workflows/ci.yml  # lint, type-check, test, smoke run
├── data/raw/                 # immutable; never edited
├── data/warehouse.duckdb     # SQL layer
├── src/
│   ├── ingest/               # ERCOT API clients, publication-lag metadata
│   ├── warehouse/            # DDL, views, loaders
│   ├── features/             # deseasonalisation, net load, calendar, vintages
│   ├── forecast/             # quantile models, scoring, calibration
│   ├── markov/               # binning, hour-indexed transition matrices
│   ├── optimize/
│   │   ├── lp_oracle.py      # perfect-foresight LP + duals
│   │   ├── dp.py             # periodic relative value iteration
│   │   ├── mpc.py            # receding horizon + offer conversion
│   │   └── cvar.py           # risk-aware scenario LP
│   ├── policies/             # unified offer-curve interface
│   ├── live/                 # scheduler, append-only decision log
│   └── evaluate/             # walk-forward, metrics, leakage assertions
├── tests/
└── reports/
```

**Commitments.**

- Typed Python, `mypy` and `ruff` clean.
- **A genuine SQL layer.** A star schema over prices, AS clearing, awards, dispatch, and forecasts in DuckDB, with the feature pipeline expressed as SQL views. This is natural for the disclosure work and it is the difference between SQL as evidence and SQL as decoration. A reviewer who opens the repo and finds one `import duckdb` will read it as ornament.
- **Unit tests** covering: SOC conservation under arbitrary admissible action sequences; constraint satisfaction; LP optimality against small analytically-solvable instances; DP–LP agreement on deterministic price paths; monotonicity of the computed bid curve; Bellman residual below tolerance; complementarity ($\min(c_t,d_t)=0$) after every solve; the finite-difference-versus-multiplier-sum identity of §IV.11.
- **Property-based tests** (`hypothesis`) on the dynamics.
- **A dedicated leakage test suite**: publication-timestamp assertions (§VIII.1) *and* estimation-fold-intersection assertions (§VIII.3).
- **CI on every push**, including an end-to-end smoke run on a small slice.
- **One reproducibility command** regenerating every headline figure from raw data.

---

# PART X — BUILD ORDER AND GATES

The dominant risk in a project of this shape is not idea quality; it is arriving at a deadline with four partially-working advanced components and no complete baseline. The ordering below is not negotiable, and **component $N+1$ does not begin until component $N$ is tested, documented, and defensible without notes.**

Items **1–5 are the project.** Items **6–9 are optional** and shipping without them is a complete result.

**1. Live decision log.** Scheduler pulls current prices and forecasts, runs the current policy (a naive threshold is fine initially), writes the intended offer curve to an append-only log with a wall-clock timestamp, and reports realised profit against the log.

*Why first:* an append-only, timestamped forward log cannot be contaminated by future information, by construction. It is a structural proof of no lookahead rather than a test for it. It accrues an out-of-sample record passively from day one, and it is the only component that speaks to deploying to a production stack. Started first it is worth months of record; started last it is worth nothing.

*Configuration, frozen on day one and never changed:* **1 MW rating, run at both 1-hour and 2-hour duration, at two settlement points — four tracks.** Rationale in Part 0, decision 13. The log's entire value derives from being an unbroken forward record; changing the rating, duration, or settlement point mid-run resets it to zero. Every later variant is evaluated offline against history, never by altering the live configuration.

**Step 0 precedes everything. See Part XIV.**

**2. Ingest, SQL warehouse, and perfect-foresight LP oracle.** Including exploratory analysis: price versus net load; spike frequency and clustering; the measured day-ahead/real-time ancillary basis by product; the forward premium, measured not asserted.

*Gate:* the LP passes the complementarity check and the analytical small-instance tests; the ceiling is computed for every duration in the Q3 sweep.

**3. Learned conditional price distribution.** Quantile models, CRPS and pinball evaluation against the parametric and empirical baselines, PIT calibration histograms, then construction of hour-indexed transition matrices.

*Gate:* calibration histograms are flat on held-out folds, or the deviation is characterised and its direction of bias on the policy stated.

**4. Periodic dynamic program, multi-product co-optimisation, and the headline results.** Relative value iteration to the fixed point; multiplier extraction; the duration sweep; Q2 and Q3; Q1 as a by-product.

*Gate:* Bellman residual below tolerance; $\mu$ monotone in $S^+$; grid-convergence demonstrated; the finite-difference-versus-multiplier identity holds.

**5. Statistical protocol and the writeup.** §VIII.5 in full, including the power statement.

*Gate:* every headline number carries a bracket, an interval, and a concentration statistic.

---

**6. The ADER chapter** (Part XI). Analytical; no new code.

**7. Fleet benchmark from 60-day disclosure.** Reconstruct realised revenue per ESR; compute each asset's perfect-foresight ceiling at its own power and duration; publish the cross-sectional distribution of capture rates; locate the modelled policy within it; decompose the shortfall.

*Note on framing:* Modo Energy and Ascend Analytics sell products that do this. This is not novel and must not be claimed as such. Its value is that it is **open, reproducible, and externally checkable**, and that agreement with published benchmarks validates the pipeline while disagreement is itself a finding. Frame it as *validating an economic model against observed behaviour* — which is what it is, and which is a named responsibility of the role.

**8. Risk chapter (Q5 and Q5b).** Synthetic retail book; joint objective; efficient frontier; then the hedging extension — residual tail, priced overlay, and the marginal cost of tail reduction by channel. Q5b reuses the Q5 distribution and the §VII.29 linear program; it is not a new pipeline.

**9. Tabular Q-learning exhibit.** On the reduced problem where the exact optimum is known. One figure: fraction of optimal value achieved versus number of training transitions. Roughly a hundred lines. It neutralises the reinforcement-learning keyword risk with *better* evidence than a deep agent, because it comes with ground truth and it lets the "why not RL?" question be answered with data rather than opinion.

---

# PART XI — THE ADER CHAPTER

**Purpose.** The modelled asset is a grid-scale ESR. A distributed residential fleet participates in ERCOT under a materially different framework, and this chapter states — precisely, without pretending the core model covers it — what changes and in which direction.

**Prerequisite, now located.** The **ADER Pilot Governing Document (Phase 3)** is public. Read it before writing this chapter; the pilot's rules have changed at every phase and secondary summaries go stale quickly.

- **Landing page, all phases:** `https://www.ercot.com/mktrules/pilots/ader`
- **Phase 3 board item** — Governing Document as Attachment A, redline against Phase 2 as Attachment B, and ERCOT staff's **Phase 2 Report** as Attachment C: `https://www.ercot.com/files/docs/2025/06/16/4.3-Aggregate-Distributed-Energy-Resource-ADER-Pilot-Project-Phase-3.pdf`

The Phase 2 Report is the most useful of the three for this chapter: it contains ERCOT's own observations on what did not work in Phase 2 and the reasoning behind each Phase 3 change.

**One structural fact that reframes the employer's business model.** An ADER must consist of premises within a **single Load Zone**, sharing the same **Load Serving Entity** and Distribution Service Provider — which in practice makes the retail provider the aggregating entity. Being a retail electricity provider is therefore a *regulatory prerequisite* for aggregating residential batteries into ERCOT, not a separate business bolted onto a hardware company. The retail book and the battery fleet are one entity by construction. **This is the structural justification for the joint objective in Q5** (§VI), which would otherwise look like an arbitrary modelling choice.

What follows is the chapter's structure and the facts verified so far; specifics must be checked against the governing document.

**Verified as of this writing.**

- Aggregated distributed resources participate through the **ADER pilot**, a separate registration framework, not as registered ESRs.
- **The "+B" half of RTC+B — single-resource modelling with SOC enforced inside SCED — is an ESR change.** It does not directly apply to ADERs. The core model's central mechanism therefore does not transfer without argument.
- ADER injections settle as **negative Load**, not as generation.
- Ancillary eligibility is restricted. ECRS was the only qualifying product in Phase 2; Phase 3 broadened access and introduced a simpler non-SCED-dispatchable participation model.
- Program-wide limits as of March 2026: registered capacity cap raised to **500 MW**, ancillary limit unchanged at **100 MW**, single-QSE share raised to 90%.
- ADERs are subject to ancillary service imbalance settlement.
- Location is modelled at load-zone level; ERCOT was still studying the appropriate granularity.

**What changes in the formulation, and in which direction.**

1. **A hard SOC floor.** A residential unit carries a backup-power obligation to the homeowner: $S^{\min} > 0$, and plausibly time-varying with outage risk and weather. This tightens (EH-up) directly, so it *raises* $\psi^{\text{up}}$ and — by §IV.11 — *raises* the marginal value of duration. **This is the strongest single argument the chapter can make, and it is quantitative:** re-run the duration sweep with $S^{\min}>0$ and show the curve shift.
2. **A retail-offset revenue term.** Energy discharged to serve the home avoids a retail purchase at the retail rate, not the wholesale rate. This is a different, and typically much larger, price. It may be the largest single term in the true objective and it has no analogue in the ESR model.
3. **Restricted product set.** With ancillary eligibility narrowed, the co-optimisation collapses toward fewer products, changing which $\tau_k$ terms appear in (AS).
4. **Settlement as negative load** changes the sign conventions and the applicable price series.
5. **Aggregation.** Heterogeneous units with independent SOC, independent household load, and communication constraints. The fleet's aggregate flexibility is not the sum of individual flexibilities under a shared SOC constraint; diversification across households smooths some of it and correlated weather removes that smoothing exactly when it matters.

**Position:** state each of these, quantify (1) and (2) with sensitivities on the existing model, and be explicit that (3)–(5) are named but not modelled. That is a scoping decision honestly declared, which is a stronger position than a fleet model built on rules not read.

---

# PART XII — KNOWN WEAKNESSES

## XII.1 Price-taking fails for a fleet

The formulation assumes actions do not move prices. Defensible for a single asset; false for a fleet dispatching simultaneously into a spike, which suppresses the spike it is capturing.

**A calibrated impact model is deliberately not attempted**, for four reasons that should be stated rather than hidden. Prices and battery dispatch are simultaneously determined, so a regression of price change on fleet dispatch is endogenous and there is no instrument available here. Under RTC+B the residual demand curve facing a battery is the output of a co-optimisation including ASDCs, not a simple energy merit order, so a slope read off the energy offer stack is not the required object. The 60-day lag confines calibration to data at least two months old. And it is an econometrics project grafted onto a control project.

**Instead:** introduce a single linear impact parameter $P^{\text{realised}}_t = P_t - \theta g_t$, sweep $\theta$ across a range bracketed by a stack-slope estimate, and report the fleet MW at which marginal profit reaches zero — labelled a **sensitivity, not an estimate**. Then say plainly: *measuring $\theta$ properly requires an identification strategy this project does not have.* That is a stronger interview position than a fragile calibrated model, and it invites the more interesting conversation.

## XII.2 Perfect market access is assumed

Offers are assumed accepted as submitted and dispatch assumed to follow instruction. Reality includes offer mitigation (explicitly present under RTC+B when duration requirements are violated), deployment following an operator signal rather than the participant's plan, telemetry requirements, and performance obligations. Real capture rates are lower than idealised backtests for reasons unrelated to strategy quality.

## XII.3 The operator has less control than the model assumes

Under RTC+B, SCED constrains ancillary awards by telemetered SOC and the rolling forward-looking duration requirement. The model has the operator freely choosing $u^k_t$. In reality one submits offers into a co-optimisation that can override them. This overstates achievable capture, and the direction is known.

## XII.4 Markov sufficiency is an approximation

[A1]. Prices depend on conditions with longer memory than any modest tabulated state captures. State augmentation mitigates but does not eliminate. Probed by the sensitivity in §VIII.7.

## XII.5 Extreme events are rare and dominate

Any short sample either contains a major scarcity event — in which case results are dominated by it and generalise poorly — or does not, in which case tail risk is systematically understated. The post-launch window contains at least one such event. **Both failure modes are reported**, and §VIII.5 exists to prevent statistical claims that the sample cannot support.

## XII.6 CVaR time inconsistency

§VII.31. Unresolved by design and explicitly declared.

## XII.7 The linear degradation model

[A3]. Understates deep cycling, overstates shallow cycling. Probed by re-solving with a convex depth penalty.

## XII.8 Congestion and basis are out of scope

A single settlement point price is taken as given. Congestion Revenue Rights and basis risk between settlement points are not modelled. Two settlement points are reported to demonstrate the conclusions are not a single-node artifact, which is a weaker guarantee than modelling congestion.

## XII.9 The fleet benchmark reproduces commercial work

§X.7. Stated, not claimed as novelty.

## XII.10 Presentation risks

**Overclaiming novelty.** The correct claim is narrow: standard machinery applied to a recently-changed market design, on post-launch public data, with open code and an honest evaluation protocol.

**Overclaiming fleet applicability.** §XII.1.

**Under-selling the engineering.** The test infrastructure, the two-layer leakage suite, the live decision log, and the reproducibility guarantee are *features of the deliverable*, not background work.

**Framing of negative results.** If the learned price model does not beat the empirical transition matrix, or if MPC performs comparably to the exact policy, the correct presentation is as a characterised finding with a mechanism — not as a failure, and not buried.

---

# PART XIII — WHAT THIS DOES NOT DEMONSTRATE

Stated so the remaining gaps are known rather than discovered in interview.

**Named in the role, not covered:**

**Fleet-scale algorithms.** The role names trading a *fleet*. Note first where the objection does **not** apply: under price-taking with identical units the single-asset solution *is* the fleet solution, because the problem is homogeneous of degree one in scale. Ten thousand identical batteries at identical state of charge are ten thousand copies of one battery. Four things break that, and they compound:

1. **Price impact.** One battery discharging into a spike does not change the spike; a fleet discharging into it is part of why the spike ends. The objective stops being linear in dispatch and [A5] fails. §XII.1 gives the sensitivity treatment, not a solution.
2. **Heterogeneity.** Ten thousand batteries averaging 50% charge, with half at 90% and half at 10%, has entirely different capability from ten thousand at 50%, and a scalar $S_t$ cannot distinguish them. The fleet state is a *distribution*; dynamic programming over a distribution is a materially harder problem.
3. **Aggregate instruction, disaggregate execution.** ERCOT issues one dispatch instruction to the aggregation. Allocating it across individual premises is a second optimisation beneath the first, with fairness constraints (one cannot drain the same customer every day), communication limits, and device failures. **At a company operating a residential fleet this is most of the engineering, and none of it appears here.**
4. **Correlated failure at the worst moment.** Diversification across households smooths consumption on ordinary days. During a heat wave or a freeze every household's load spikes together and every backup reserve requirement tightens together — the diversification disappears precisely during the scarcity event that generates the profit.

The trading logic scales. The fleet problem is a different problem stacked on top of it, and it is the harder one.

**Deployment to a production trading stack.** The live decision log is the closest analogue and it is a scheduled job. Scheduling is *not* the gap — the algorithm is perhaps a tenth of a production trading system, and the rest is what must be true for its output to become a market position without losing money. Specifically, the log does not submit anything (it writes to a file, whereas production authenticates to ERCOT's API on a five-minute deadline with no retry); cannot be wrong expensively (a crash costs a data point, not an unhedged position under a tightened 3%-or-3-MW set-point deviation regime); performs no position reconciliation against settlement statements; has no risk limits or kill switch; has no state recovery after failure; and has no defined behaviour for stale telemetry, missing feeds, or late price publication. **Describe it precisely — "a scheduled job running a policy against live prices with an auditable decision log" — which is accurate and substantial, rather than as a trading system, which invites a question with no answer.**

**Hedging instruments — now partially covered; state the boundary precisely.** Q5b (§VI) computes the residual tail after the physical hedge, prices a forward strip and a call overlay against it, and reports the marginal cost of tail reduction by channel. That addresses the *assessment and valuation* half of the role's Risk & Trading block. **Not covered:** congestion revenue rights and locational basis instruments (§XII.8 excludes congestion by scope); heat-rate options and any gas-market linkage; bilateral contract negotiation and credit; and automated *execution*, as opposed to valuation. The honest summary is that the project prices simple hedges against a measured exposure and does not trade them.

**Likely in interview, not in the role text:**

- **Working in someone else's codebase.** Every line here is yours: no code review, no inherited constraints, no merge conflicts. A small accepted pull request to `gridstatus` would address this and would be directly on-topic.
- **Latency and real-time systems.** SCED clears every five minutes; this pipeline runs on a schedule.
- **Dirty operational data.** ERCOT's public feeds are clean relative to telemetry from thousands of residential inverters.
- **Test-driven development in a team.** A solo repository with `pytest` and CI is evidence of the *practice*, not of the skill under collaboration. "Tell me about a time your tests caught a colleague's bug" has no answer here.

---

# APPENDICES

## Appendix A — Notation

| Symbol | Definition |
|---|---|
| $t$, $\Delta t$ | Interval index; interval length (hours) |
| $h$, $H$ | Time-of-day index; intervals per day |
| $S_t$, $S^+_t$ | State of charge; post-decision state of charge (MWh) |
| $E^{\max}$, $S^{\min}$ | Energy capacity; reserved floor (MWh) |
| $\bar p$ | Maximum charge/discharge power (MW) |
| $\eta_c,\eta_d,\eta$ | Charge, discharge, round-trip efficiency ($\eta=\eta_c\eta_d$) |
| $g_t$ | Net injection, positive = discharge (MW) |
| $c_t, d_t$ | Charge, discharge power (MW); $c=(g)^-$, $d=(g)^+$ |
| $\Phi(g)$ | Throughput map, $-(g)^+/\eta_d + \eta_c(g)^-$ |
| $u^k_t$, $\tau_k$, $\rho_k$, $\phi_k$ | AS commitment (MW); duration requirement (h); deployment rate; throughput factor |
| $c_{\text{deg}}$ | Marginal degradation cost (\$/MWh grid-side throughput) |
| $P^{RT}_t, P^{DA}_t$ | Real-time, day-ahead energy price (\$/MWh) |
| $P^{k,RT}_t, P^{k,DA}_t$ | Real-time, day-ahead MCPC for product $k$ (\$/MW-h) |
| $\mathbf{x}_t$, $\mathbf{f}_t$ | Tabulated exogenous state; full feature vector |
| $r_t$, $\rho$ | Interval reward; optimal average reward (gain) |
| $V_h$, $\widetilde V_h$ | Pre-decision, post-decision value function |
| $\mu_h$ | $\partial\widetilde V_h/\partial S^+$ — marginal value of stored energy |
| $\bar\lambda_t,\underline\lambda_t$ | Multipliers on $S\le E^{\max}$, $S\ge 0$ |
| $\omega^{\text{up}}_t,\omega^{\text{dn}}_t$ | Multipliers on power headroom |
| $\psi^{\text{up}}_t,\psi^{\text{dn}}_t$ | Multipliers on energy headroom (EH-up), (EH-dn) |
| $\mathcal{F}_t$ | Information filtration |
| $\alpha,\beta$ | CVaR tail probability; risk-aversion weight |
| $\rho_\alpha(\cdot)$ | Pinball loss at level $\alpha$ |

## Appendix B — Assumptions register

| # | Assumption | Where used | Failure consequence | Probe |
|---|---|---|---|---|
| A1 | Markov sufficiency of $\mathbf{x}_t$ | Bellman validity | Policy optimal for the wrong process | Add a lag, re-solve, measure change |
| A2 | Unichain / irreducible exogenous chain | Average-reward formulation | Gain becomes state-dependent | Check irreducibility of $T^{(h)}$ |
| A3 | Linear throughput degradation | Reward, LP linearity | Over-deep cycling | Convex depth penalty, re-solve |
| A4 | Periodic stationarity after deseasonalisation | 24-periodic fixed point | Seasonal drift uncaptured | Fit and solve by season |
| A5 | Price-taking | Duration sweep, all results | Fleet extrapolation invalid | Impact-parameter sensitivity |
| — | $\eta_c\eta_d<1$ | Complementarity relaxation | Relaxation not exact | Assert $\min(c_t,d_t)=0$ post-solve |
| — | $\mu\ge 0$ | Complementarity relaxation | Relaxation not exact at high SOC | Report fraction of cells with $\mu<0$ |

## Appendix C — Glossary

**ADER (Aggregate Distributed Energy Resource).** ERCOT's pilot framework for aggregations of behind-the-meter devices participating in the wholesale market. Separate registration class from an ESR.

**Adapted.** A policy using only information available at decision time; the formal statement of "no lookahead."

**ASDC (Ancillary Service Demand Curve).** Per-product demand curve introduced under RTC+B, replacing the ORDC as the scarcity-pricing mechanism.

**Bellman equation.** The recursion expressing the value of a state as the best attainable sum of immediate reward and expected continuation value.

**Capture rate.** Realised profit divided by perfect-foresight profit.

**Certainty equivalence.** Optimising as if a point forecast were exact; the defining approximation of standard MPC.

**Coherent risk measure.** One satisfying monotonicity, translation equivariance, positive homogeneity, and subadditivity. CVaR is; VaR is not.

**CRPS.** Continuous Ranked Probability Score; a proper scoring rule for distributional forecasts, equal to pinball loss integrated over quantile levels.

**Duration.** $E^{\max}/\bar p$ — hours of discharge at full rated power.

**ESR (Energy Storage Resource).** ERCOT's registration category for grid-connected storage.

**Gain / bias.** In average-reward dynamic programming, the long-run reward per period and the state-dependent relative value.

**LMP.** Locational Marginal Price; the shadow price of the power-balance constraint at a location.

**MCPC.** Market Clearing Price for Capacity; the clearing price of an ancillary product.

**PIT (Probability Integral Transform).** $F(Y)\sim\text{Uniform}(0,1)$ when $Y\sim F$; the basis of the calibration diagnostic.

**Post-decision state.** The state after the controller acts but before exogenous randomness resolves.

**Proper scoring rule.** One whose expected score is optimised by reporting the true distribution.

**RTC+B.** ERCOT's market redesign effective 5 December 2025: real-time co-optimisation of energy and ancillary services, single-resource battery modelling with state of charge enforced in SCED, and ASDCs replacing the ORDC.

**RTSWCAP / DASWCAP.** Real-time (\$2,000/MWh) and day-ahead (\$5,000/MWh) system-wide offer caps under RTC+B.

**SASM.** Supplemental Ancillary Services Market; the pre-RTC+B intraday AS procurement process, eliminated at go-live.

**SCED.** Security-Constrained Economic Dispatch; ERCOT's real-time dispatch optimisation, run every five minutes.

**Shadow price.** The Lagrange multiplier on a constraint; the marginal value of relaxing it.

**Span seminorm.** $\mathrm{span}(v) = \max_i v_i - \min_i v_i$; the norm in which relative value iteration contracts.

**Water value.** The marginal value of stored energy; terminology inherited from hydropower scheduling, where this theory originated.

---

# PART XIV — EXECUTION STAGES

This part exists so the project can be resumed from a cold start without re-deriving the reasoning. The project is organized into **stages** — distinct, completable units of work, not incremental micro-steps. Each stage states **what**, **why it comes where it does**, and **the gate** that must pass before proceeding. **Stages 0–5 are the core project and are what we apply on; Stages 6–9 are optional add-ons** — shipping without them is a complete result.

The ordering principle throughout: **stage $N+1$ does not begin until stage $N$ is tested, documented, and defensible without notes.** The dominant failure mode is not poor ideas — it is arriving at a deadline with four partially-working advanced components and no complete baseline.

> **Note on numbering (post-Step-0 restructure).** This project was originally
> written with "Steps". It is now organized as the **Stages** below. Body prose in
> the detailed sections may still say "Step N"; for N ≥ 3 that maps to "Stage N"
> unchanged. The two that moved: the old *Step 2* (ingest/oracle) is now **Stage 1**
> (the foundation comes first, since every policy needs the oracle as its
> denominator), and the old *Step 1* (live decision log) is now a **continuous
> track** that starts once a policy exists (Stage 2), because its value is passive
> forward accrual and it needs something to log.

## STAGE MAP

| Stage | Delivers | Status |
|---|---|---|
| **0 — Viability** | Perfect-foresight LP, gate, reframe | ✅ done |
| **1 — Data & oracle foundation** | Full-window ingest, DuckDB/SQL warehouse + feature views, LP oracle generalized with dual extraction, `pytest` + CI | partial (ingest + validated LP exist) |
| **2 — MPC / first causal policy** | Receding-horizon reoptimization + naive baseline → first value-of-foresight gap; a deployable policy AND the certainty-equivalent baseline the DP must beat. Live-log track starts here. | next |
| **3 — Learned price model** | Quantile-regression conditional distribution, pinball/CRPS, PIT calibration, hour-indexed transition matrices — the ML content and a required input to Stage 4 | — |
| **4 — Dynamic program + headline results** | Periodic DP (post-decision, grid-aligned), multiplier extraction, duration sweep → **Q2** (psi_up, real operator), **Q3** (duration curves), **Q1** (basis). The optimal causal policy | — |
| **5 — Statistics, validation & writeup** | Walk-forward protocol, sign test, bootstrap, power statement, full verification suite, findings-first writeup. **Apply after this.** | — |
| *Track — Live decision log* | Forward, no-lookahead record; runs continuously from Stage 2 on | — |
| **6 — ADER chapter** | Residential-fleet relevance | optional |
| **7 — Fleet benchmark** | External validation vs 60-day disclosure | optional |
| **8 — Risk & hedging (Q5/Q5b)** | The Risk & Trading block of the role | optional |
| **9 — Tabular Q-learning exhibit** | Neutralizes the RL question with ground truth | optional |

**Organizing frame — the value of foresight (Decision 19).** The Stage 0
perfect-foresight LP is the *ceiling* on profit / *floor* on constraint cost — a
clairvoyant bound, not achievable. A causal policy (past + forecast only) is what a
real operator achieves. The gap between them is the **value of foresight**, the
number a battery desk cares most about. The core stages produce it as a measured
sequence — **perfect-foresight LP (Stage 0) ≥ dynamic program (Stage 4) ≥
MPC-with-forecast (Stage 2) ≥ naive floor** — all backtested walk-forward on real
prices with no lookahead leakage. This upgrades **Q2** (psi_up) and **Q3**
(duration curve) from a clairvoyant bound to a *realistic-operator* number: the
causal psi_up is higher and is the real one. **The full dynamic program is the
headline deliverable — it is the "sequential decision-making algorithm" the target
role centers on — so Stage 4 is built in full (fed by Stage 3), not as a reduced
stand-in. The MPC (Stage 2) is built first because it reuses the Stage 0 LP, is the
most production-realistic piece, and is the baseline the DP is measured against.**

---

## STAGE 0 — Viability test

> **STATUS: DONE (21 Jul 2026). Verdict = qualified PROCEED.** Run on the full
> post-launch window (HB_NORTH, 2025-12-05 → 2026-06-20, 18,891 intervals, 198
> days). EH-up binds (contingency-only, 2 h) in 7.98% of intervals across 129
> days by the pre-registered tolerance — kill condition NOT triggered — but
> `psi_up` is a heavy-tailed scarcity price (median $0.015, max $32.75, material
> > $5 on ~5 days). Summer scarcity season not yet observed; `psi_up` is a lower
> bound. Full result + verification checks in `reports/step0_results.md`; verdict
> and reframe in CLAUDE.md Decision 18. **The gate outcome below has been read;
> the three-outcome table is superseded by the four-outcome reading in CLAUDE.md
> Decisions 7/14/18.**

**Do this before writing any modelling code. It is decisive and cheap.**

**What.** Register for both ERCOT API keys. Ingest one month of post-launch 15-minute settlement point prices and real-time MCPCs for one settlement point. Write *only* the perfect-foresight linear program of §IV.12, with the ancillary constraints of §III.17 included. Solve it for 1-hour, 2-hour, and 4-hour durations. Extract and report:

1. The fraction of intervals in which (EH-up) is active, by duration.
2. The fraction in which (EH-dn) is active, by duration.
3. The magnitude and time-distribution of $\psi^{\text{up}}_t$, $\psi^{\text{dn}}_t$ when active.
4. How many distinct *days* those active intervals cluster into.

**Why first.** Q2 and Q3 both rest on the energy-headroom constraints binding. $\psi \equiv 0$ whenever stored energy is abundant relative to ancillary obligations. RTC+B *cut* the duration requirements substantially — ECRS 2 h → 1 h, RRS and Regulation 1 h → 30 min. That reduction may have been large enough that headroom stopped binding for typical assets, in which case:

- $\psi \equiv 0$, so **Q2 has no answer**;
- by §IV.11's identity the ancillary contribution to the duration curve vanishes and **Q3 collapses to plain energy arbitrage**, a well-worn question;
- the framing that RTC+B made products compete for a shared scarce resource is a story about a constraint that does not bite.

This cannot be settled from the literature and it must not be discovered after the dynamic program is built. Item 4 above is the one that determines whether §VIII.5 has anything to work with — see §VIII.5a.

**Gate — three outcomes, three responses.**

| Outcome | Response |
|---|---|
| Binds meaningfully (>5% of intervals for a 2-hour asset, across ≥10 distinct days) | Proceed with the plan as written |
| Binds only for short-duration assets | Proceed; reframe Q3 as *where duration stops paying*. The curve is steep at the low end and flat above — still a result |
| Essentially never binds | **Stop.** Q2 is dead and Q3 needs a new mechanism. Re-scope before building anything further |

**Also read during this step, and do not delegate to summaries:** ERCOT Nodal Protocols §8.1.1.3.1–8.1.1.3.4 (real-time ancillary qualification, including the unresolved RRS–FFR duration flagged in §II.9), and the RTC+B Battery Overview deck.

---

## LIVE DECISION LOG — continuous track (starts at Stage 2)

**What.** A scheduled job that pulls current prices and forecasts, runs the current policy, writes the intended **offer curve** to an append-only log with a wall-clock timestamp, and reports realised profit against that log. A naive threshold policy is fine initially; better policies are swapped in later without disturbing the log.

**Configuration, frozen permanently on day one:** 1 MW rating, both 1-hour and 2-hour duration, two settlement points — four tracks.

**Why a continuous track, started as early as possible.**

- An append-only, timestamped forward log **cannot be contaminated by future information, by construction.** It is a structural proof of no lookahead rather than a test for one, and it is the only such proof available.
- It accrues out-of-sample record passively while every other component is built. Started the moment a policy exists (Stage 2) it is worth months by the time it matters; started at Stage 9 it is worth nothing. It needs *some* policy to log, which is why it begins at Stage 2 rather than Stage 0 — a naive threshold is a fine first occupant, swapped for the MPC and then the DP without disturbing the log.
- It is the only component addressing deployment, and — per §VIII.5a item 4 — the only mechanism that increases the sample over time.
- Because the log records an *offer curve* rather than a dispatch decision, it is $\mathcal{F}_t$-measurable by §IV.6, so the live artifact and the backtest share identical execution semantics.

**Why the configuration is frozen.** The log's entire value is that it is an unbroken forward record. Changing rating, duration, or settlement point mid-run resets it to zero. Every later variant is evaluated offline against history.

**Gate.** Log runs unattended for a week; timestamps verified monotone; a deliberate restart mid-interval recovers without gaps or duplicate entries.

---

## STAGE 1 — Data & oracle foundation (ingest, SQL warehouse, perfect-foresight oracle)

*(**DONE — at the Stage 1 gate.** Full build record: `reports/stage1_notes.md`.
**Shipped:** a DuckDB warehouse over the price + MCPC panel with the feature
pipeline as SQL views (`src/warehouse.py`); the Stage 0 LP generalised into a
reusable oracle with dual extraction **and boundary conditions** (`s_init` /
`s_final` / `cyclic`) so Stage 2's MPC can call it in a rolling loop
(`src/oracle.py`); a 38-test `pytest` verification suite + GitHub Actions CI.
**Scope decisions (living doc — revisited with new information, reasoning kept):**
the warehouse covers the two real-time series Stage 0 used; **awards, dispatch,
forecasts, and day-ahead prices are deferred to the stages that consume them** —
nothing consumes them yet and building empty fact tables is decoration (§IX.4).
Re-attachment: ERCOT load/price **forecasts → Stage 3 features**; **day-ahead
prices + the DA/RT basis + forward premium → an OPTIONAL Stage 3 enhancement / Q1
color** (not redundant with the RT-only Stages 0–1, but not core — build only if
the forecaster wants the feature or Q1 is reported); **awards + dispatch dropped
from the core path** — telemetry is out of scope per Decision 17, revisit only for
the optional fleet-benchmark add-on (Stage 7). **Data hygiene:** 6 exact-duplicate
intervals were found and dropped at source (`ingest.dedup_panel`, default on) — a
hygiene fix, not a parameter change, so consistent with the frozen
pre-registration; Stage 0 was regenerated on the deduped panel (headline binding
fraction 7.98% → 8.00%, psi_up max $32.75 and verdict unchanged — "Option A"). A
**timestamp-gap audit** was added (`warehouse.audit_gaps` + a hard sub-interval
assertion): the DST spring-forward shows as a clean 75-min forward jump, closing
the misalignment risk. The §VIII.1 publication-timestamp assertions move to
Stage 2/3, where point-in-time features and the fact tables that carry
publication vintages actually arrive.)*

**What (original intent — reconciled by the status note above).** Production-quality ingest for the full dataset inventory of §IX.3, each row carrying an explicit publication timestamp. A star schema in DuckDB over prices, ancillary clearing, awards, dispatch, and forecasts, with the feature pipeline expressed as SQL views. The perfect-foresight LP generalised from Stage 0 to the full window and all durations, with dual extraction. Add `pytest` coverage of the verification suite and a CI job — the software-engineering evidence the role requires (§XII.10), not an afterthought.

Exploratory analysis delivered here: price versus net load; spike frequency and clustering; the measured day-ahead/real-time ancillary basis by product; and the forward premium **measured, not asserted** (§II.8 — its sign varies by year, hour and product).

**Why here.** Everything downstream consumes this. The LP oracle is the denominator of every reported number, so it must exist before any policy is evaluated. Building the SQL layer now rather than retrofitting it is what makes it genuine evidence rather than decoration (§IX.4).

**Watch for:** `gridstatus.get_as_prices()` raises `ValueError` for dates ≥ 2025-12-06; use the post-RTC endpoints in §IX.3. Resource names changed at the single-model transition — join through the ERCOT mapping file (§IX.1) or pre/post joins will silently fail.

**Gate.** LP passes the complementarity assertion $\min(c_t,d_t)=0$ and the analytical small-instance tests; the ceiling is computed for every duration in the Q3 sweep; publication-timestamp assertions (§VIII.1) pass on the whole warehouse. **Status — met:** the complementarity + analytical + full verification suite pass as `pytest` (38 tests, green in CI); the oracle computes the ceiling for {1,2,4}-h durations (real-data test asserts optimal, finite, and the energy-only ≤ +contingency ≤ +all-products ordering). The §VIII.1 publication-timestamp assertion is **deferred to Stage 2/3** with the fact tables that carry vintages; in its place the warehouse asserts uniqueness, price bounds, monotone + no-sub-interval timestamps, and a time-axis gap audit.

---

## STAGE 2 — MPC / first causal policy (and the value-of-foresight baseline)

*(**DONE.** Record: `reports/stage2_notes.md`. `src/backtest.py` (no-lookahead
walk-forward harness), `src/policies.py` (naive threshold floor + receding-horizon
MPC), `src/forecast.py` (causal forecasters), `src/stage2_run.py`; 10 Stage-2
tests. **Full-window result @ 2 h: value of foresight $16,660 = $360 execution +
$16,300 forecast error** — with a perfect forecast the same controller captures
97% of the ceiling, so the gap is almost entirely forecast quality. Reserve
co-optimisation adds a steady +$2,919 carry (energy −$3,453 → total −$366). The
causal psi_up (Decision 19) is extracted from each solve's headroom dual — median
matches Stage 0, tail ~4× fatter (max $141 vs $33). Execution decision: the MPC
commits the LP's planned first action (certainty-equivalent); the mu[0]-priced
offer curve of §IV.6/§VIII.2 captured only ~57% even with perfect foresight
(degenerate at SOC bounds) and is deferred to Stage 4, where the DP value function
supplies a robust water value. The naive floor still executes as a genuine offer
curve, so both models are exercised.)*

**What.** A receding-horizon reoptimization controller: at each interval, solve the Stage 1 LP over a rolling look-ahead window using a *forecast* of future prices (not the realised future), convert the first-interval plan into an offer curve per §IV.6, execute, advance, re-solve. Start with a simple, transparent forecast (e.g. same-hour-last-week, or a small regression); the forecast is upgraded to the learned model of Stage 3 later without changing the controller. Backtest walk-forward on real prices against two references: the Stage 0 perfect-foresight LP (ceiling) and a naive threshold policy (floor). Report the first **value-of-foresight gap**.

**Why here — before the dynamic program.** It reuses the Stage 1 oracle almost verbatim, so it is the fastest causal policy to stand up, and it is the most production-realistic artifact ("deploying algorithms to a production trading stack"). It is also not throwaway: the certainty-equivalent MPC is exactly the baseline the exact DP of Stage 4 must beat (§IV.6, §VIII.2), so building it now is building a required comparator. The live-decision-log track begins here, with the MPC as its first occupant.

**Watch for — the adaptedness trap (§III.21, §IV.6).** MPC produces a *plan*, and converting a plan into an offer curve is the modelling choice that determines whether the backtest leaks future information. Use the §VIII.2 conversion so the MPC and the exact policy share identical, $\mathcal{F}_t$-measurable execution semantics. A backtest that dispatches on the realised price rather than a pre-committed offer is measuring nothing.

**Gate.** Walk-forward backtest with no fold-intersection leakage; the offer-curve conversion is $\mathcal{F}_t$-measurable and tested; the value-of-foresight gap (ceiling − MPC and MPC − naive) is reported with a bracket, not a point.

---

## STAGE 3 — Learned conditional price distribution

**What.** Quantile-regression models over the feature vector $\mathbf{f}_t$, evaluated by pinball loss and CRPS against two baselines — the empirical count-based transition matrix and the parametric mean-reverting jump model. PIT calibration histograms on held-out folds. Then construction of **hour-indexed** transition matrices with log-spaced tail bins (§V.26).

**Why here — before the dynamic program, not after.** The Bellman equation contains $\mathbb{E}[V_{h+1}\mid\mathbf{x}_t]$; the DP is structurally incapable of running without this object. It is also the project's only genuine machine-learning content, and it is load-bearing rather than decorative.

**Why calibration is a policy diagnostic, not a side check.** The DP's willingness to hold charge for a spike is driven entirely by the right tail of the predictive distribution. An underdispersed forecast collapses the policy toward MPC; an overdispersed one makes it hoard and never trade. Connecting the calibration histogram to the policy's economic behaviour is one of the more sophisticated things this project can say.

**Gate.** Calibration histograms flat on held-out folds — or the deviation characterised, with its direction of bias on the policy stated explicitly. Every fitted object re-fit inside each walk-forward fold (§VIII.3); the fold-intersection assertion passes.

**Status: COMPLETE** (see `reports/stage3_notes.md`). GBT quantile regression beat both baselines on held-out CRPS (learned 2.708 < jump 2.903 < empirical 5.192, 4/5 folds) → adopted. Gate MET with a *characterised* deviation: PIT near-uniform (KS 0.031) but mildly under-dispersed in the tails → biases the Stage 4 policy to under-hold for spikes (toward MPC); mitigation (extreme tail levels / variance inflation) is the first Stage 4 action. Hour-indexed transition matrices (log-spaced tail bins) are row-stochastic and irreducible. Swapped into the certainty-equivalent MPC the learned forecast recovered $3,139 = 19% of the $16,300 forecast-error cost (median only; the tail value is Stage 4's).

---

## STAGE 4 — Periodic dynamic program and the headline results *(the headline deliverable — built in full)*

**What.** Post-decision-state formulation (§IV.2); grid-aligned action set (§IV.8); relative value iteration to the 24-periodic fixed point (§IV.9); multiplier extraction; multi-product co-optimisation via (AS) (§IV.10); the duration sweep. Delivers **Q3** (two curves plus the capture-rate curve), **Q2** (the shadow-price distributions), and **Q1** as a by-product of the two-settlement structure.

**Why the periodic formulation.** It eliminates the terminal-value problem entirely — the value function is self-consistent across the day boundary by construction — and reduces compute by roughly two orders of magnitude versus a finite-horizon pass. Both benefits from one choice.

**Why grid-aligned actions rather than interpolation.** Nearest-neighbour rounding of $S^+$ destroys concavity and biases the policy, and the resulting monotonicity failure looks like a bug elsewhere. Aligning the action grid so every transition lands exactly on a state grid point makes the DP exact on the grid with no interpolation.

**Gate.** Bellman residual below tolerance at every state and hour; $\mu$ monotone non-increasing in $S^+$; grid convergence demonstrated across $N_S \in \{50,100,200,400\}$; **the finite-difference-versus-multiplier-sum identity of §IV.11 holds.** That last check is nearly free, almost nobody runs it, and it validates the multiplier extraction that Q2 depends on entirely.

---

## STAGE 5 — Statistical protocol and writeup *(apply after this)*

**What.** §VIII.5 in full: paired daily differences, stationary block bootstrap with block length as a reported sensitivity, the **sign test as the headline statistic**, concentration reporting, leave-one-day-out jackknife, and the power statement. Then the writeup, findings first.

**Why the sign test leads.** Bootstrap coverage for a mean degrades badly under the tail concentration this market exhibits — a single day has produced ~45% of a month's fleet-wide revenue. "Policy A beats policy B on 61% of days, $p=0.003$" survives a fat tail; a confidence interval on $\mathbb{E}[D]$ may not.

**Why the power statement matters disproportionately.** "This design could detect a difference above 8% of the perfect-foresight ceiling; smaller differences are not resolvable with this sample" is the single most credibility-enhancing sentence available, and almost nobody writes it.

**Gate.** Every headline number carries a bracket (ceiling and floor), an interval, and a concentration statistic. One command regenerates every figure from raw data.

---

**Stages 0–5 constitute a complete, defensible project and are what we apply on. Everything below is optional.**

---

## STAGE 6 — ADER chapter *(optional add-on)*

**What.** Read the Phase 3 Governing Document and Phase 2 Report (§IX.1). Write Part XI: quantify the backup-floor effect ($S^{\min}>0$ tightens (EH-up), raising $\psi^{\text{up}}$ and therefore raising the marginal value of duration — re-run the sweep and show the shift) and the retail-offset term; name but do not model the restricted product set, negative-load settlement, and aggregation.

**Why here.** Analytical, no new code, and it converts a single-asset result into employer-relevant commentary. Cheap and high-leverage, which is why it precedes the larger optional items.

---

## STAGE 7 — Fleet benchmark from 60-day disclosure *(optional add-on)*

**What.** Reconstruct realised revenue per ESR from disclosure data; compute each asset's perfect-foresight ceiling at its own power and duration; publish the cross-sectional distribution of capture rates across the ~297 ESRs that settled revenue; locate the modelled policy within it; decompose the shortfall into forecast error, energy/ancillary allocation, and SOC management.

**Why it is worth more than its position suggests.** It is the strongest available answer to the thin-sample problem (§VIII.5a item 3): ~300 assets observed across the *same* scarcity days is a fundamentally different inferential position from one time series with a handful of interesting days. It is also the only component that is externally checkable against reality.

**Framing, non-negotiable.** Modo Energy and Ascend Analytics sell products that do this. It is not novel and must not be presented as such. Its value is that it is open, reproducible, and checkable — agreement with published benchmarks validates the pipeline, disagreement is itself a finding. Present it as *validating an economic model against observed behaviour*, which is both accurate and a named responsibility of the role.

---

## STAGE 8 — Risk chapter (Q5 and Q5b) *(optional add-on)*

**What.** Synthetic retail book from public load-zone shapes; joint objective; efficient frontier over $\beta$. Then Q5b: residual tail after the physical hedge, a priced forward-strip and call overlay, and **the marginal cost of tail reduction by channel**, reported as a function of fleet duration.

**Why last among the substantive items.** It depends on the risk machinery of Part VII and on the duration results of Step 4. It is also the only component addressing the role's Risk & Trading block, which makes it the highest-value optional item — build it before Step 9 if time is short.

**Why the extension rather than a separate hedging artifact.** The substantive question is not *what should be hedged* but *given that a large physical hedge is already owned, what residual remains and is financial protection on it worth the cost?* Q5b answers that using the Q5 distribution and the §VII.29 linear program already built. A standalone congestion-rights study would answer a question nobody asked.

---

## STAGE 9 — Tabular Q-learning exhibit *(optional add-on)*

**What.** Tabular Q-learning or fitted Q-iteration on the reduced problem where the exact optimum is known. One figure: fraction of DP-optimal value achieved versus number of training transitions. Roughly a hundred lines.

**Why it exists at all.** It neutralises the reinforcement-learning keyword risk with *better* evidence than a deep agent would provide, because it comes with ground truth. It converts "why didn't you use RL?" from an opinion into a measurement. Do not build deep RL; §I.4 stands.

**Why last.** It is the only item that adds no new knowledge about the market.

---

## Standing rules

1. **Freeze the live configuration.** Four tracks, never altered. Variants are evaluated offline.
2. **Every estimated object is re-fit inside each walk-forward fold.** A single global `deseasonalize()` call before the loop is the easiest way to silently destroy the project's credibility.
3. **Assert, do not assume.** Complementarity after every solve; monotonicity of $\mu$; Bellman residual; publication timestamps; fold-intersection. These are cheap and they are the difference between results that are believed and results that are not.
4. **Bracket every number.** A performance figure without a ceiling and a floor is not a result.
5. **Negative results are results.** If the learned model does not beat the empirical transition matrix, or MPC matches the exact policy, present it as a characterised finding with a mechanism — not as a failure, and not buried.
6. **Do not claim novelty.** The correct claim is narrow: standard machinery, applied to a recently changed market design, on post-launch public data, with open code and an honest evaluation protocol.
7. **Stages 0–5 are shippable.** If the timeline compresses, the MPC (Stage 2) is the earliest genuinely-shippable causal policy — but the target is through Stage 5, because the full dynamic program (Stage 4) is the sequential-decision headline the role centers on. Describe whatever ships as what it is — a complete single-asset study — rather than as an unfinished version of something larger.
