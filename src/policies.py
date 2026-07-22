"""
Dispatch policies for the Stage 2 value-of-foresight ladder.

Every policy commits, at interval t and using ONLY the realised past, a decision
that the backtest then applies. Two execution models appear here, both
F_t-measurable (decided before the realised price is known — no lookahead leak,
plan §III.21):

  * OFFER CURVE (price-contingent): pre-commit thresholds; the realised price
    clears them. How a real ERCOT offer works. The naive floor uses it.
  * COMMITTED DISPATCH (certainty-equivalent): pre-commit a quantity computed
    from the forecast; execute it, value it at the realised price. The standard
    certainty-equivalent MPC. The MPC uses it.

The MPC commits a quantity rather than a mu[0]-priced offer curve because we
tested the mu[0] offer and it captures only ~57% of the clairvoyant ceiling even
with a PERFECT forecast (mu[0] is degenerate at the SOC bounds, so the band
whipsaws); the planned-action MPC captures ~97%. The price-contingent offer-curve
MPC needs a robust marginal water value, which the Stage 4 DP value function
provides — deferred there, not faked here.

Reserve co-optimisation (Stage 2 follow-up): the MPC can sell contingency reserves
(RRS/ECRS/Non-Spin) alongside energy. The oracle co-optimises them under the RTC+B
energy-headroom constraint; the committed reserve MW earn the realised capacity
price (MCPC) and the dual on the first headroom constraint, psi_up[0], is the
CAUSAL operator's marginal cost of the SOC-enforcement rule at that interval
(Decision 19 — the real-operator Q2 number).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from src import oracle
from src.forecast import Forecaster, SeasonalNaiveForecaster


@dataclass
class History:
    """The realised past handed to a policy at interval t (prices[:t] and each
    MCPC series[:t]). The backtest builds this; a policy that peeked past it would
    be leaking the future, which the harness makes structurally impossible."""

    prices: np.ndarray
    mcpc: dict = field(default_factory=dict)


def _clip_charge(c, soc, params, E_max):
    return max(0.0, min(c, params.p_bar, (E_max - soc) / (params.eta_c * params.dt)))


def _clip_discharge(d, soc, params, E_max):
    return max(0.0, min(d, params.p_bar, soc * params.eta_d / params.dt))


@dataclass
class Offer:
    """A pre-committed, price-contingent offer curve for one interval."""

    p_charge_below: float
    p_discharge_above: float
    cap: float
    u_plan: dict = field(default_factory=dict)   # (naive floor sells no reserves)
    psi_up: float = 0.0

    def dispatch(self, price, soc, params, E_max):
        if price >= self.p_discharge_above:
            return 0.0, _clip_discharge(min(self.cap, params.p_bar), soc, params, E_max)
        if price <= self.p_charge_below:
            return _clip_charge(min(self.cap, params.p_bar), soc, params, E_max), 0.0
        return 0.0, 0.0


@dataclass
class CommittedDispatch:
    """A pre-committed quantity (certainty-equivalent MPC). Ignores the realised
    price for the decision; the price only enters the profit accounting. Clipped
    to SOC feasibility so a plan can never over-draw. Carries the committed reserve
    MW (u_plan) and the causal shadow price psi_up on the headroom constraint."""

    c_plan: float
    d_plan: float
    u_plan: dict = field(default_factory=dict)
    psi_up: float = 0.0

    def dispatch(self, price, soc, params, E_max):
        return (_clip_charge(self.c_plan, soc, params, E_max),
                _clip_discharge(self.d_plan, soc, params, E_max))


class Policy:
    """Interface: from the realised past + current SOC, commit a decision for t."""

    def decide(self, soc: float, hist: History, E_max: float, params):
        raise NotImplementedError


@dataclass
class NaiveThresholdPolicy(Policy):
    """FLOOR. Charge in the price's cheap tail, discharge in its rich tail, with
    thresholds from a trailing window of realised prices — no forecast, no
    optimisation, no reserves. The dumb operator every real policy must beat."""

    q_low: float = 0.25
    q_high: float = 0.75
    lookback: int = 96 * 7

    def decide(self, soc, hist: History, E_max, params) -> Offer:
        prices = hist.prices
        if len(prices) < 8:
            return Offer(-np.inf, np.inf, params.p_bar)
        window = prices[-self.lookback:]
        return Offer(p_charge_below=float(np.quantile(window, self.q_low)),
                     p_discharge_above=float(np.quantile(window, self.q_high)),
                     cap=params.p_bar)


@dataclass
class MPCPolicy(Policy):
    """The causal MPC. At interval t: forecast the next `horizon` prices (and
    reserve MCPCs, if selling reserves) from the realised past, solve the
    perfect-foresight LP over that window from the current SOC (with a terminal
    value so a short horizon does not distort the first action), and COMMIT the
    LP's planned first-interval energy action + reserve commitments. Re-solve every
    interval. The forecast is the only thing Stage 3 changes."""

    forecaster: Forecaster = None
    horizon: int = 96
    terminal_lookback: int = 96
    product_set: dict = field(default_factory=lambda: oracle.ENERGY_ONLY)
    mcpc_forecaster: Forecaster = None

    def __post_init__(self):
        if self.mcpc_forecaster is None:
            self.mcpc_forecaster = SeasonalNaiveForecaster(period=96 * 7)

    def decide(self, soc, hist: History, E_max, params) -> CommittedDispatch:
        prices = hist.prices
        if self.forecaster is None or len(prices) < 4:
            return CommittedDispatch(0.0, 0.0)
        fc = self.forecaster.predict(prices, self.horizon)
        mcpc_fc = {}
        for k in self.product_set["up"] + self.product_set["dn"]:
            hk = np.asarray(hist.mcpc.get(k, []), float)
            mcpc_fc[k] = (self.mcpc_forecaster.predict(hk, self.horizon)
                          if len(hk) else np.zeros(self.horizon))
        tv = float(np.median(prices[-self.terminal_lookback:]))
        res = oracle.solve(fc, mcpc_fc, E_max, params, self.product_set,
                           s_init=float(soc), cyclic=False, terminal_value=tv)
        u0 = {k: float(res.u[k][0]) for k in res.u}
        return CommittedDispatch(float(res.c[0]), float(res.d[0]), u0,
                                 float(res.psi_up[0]))
