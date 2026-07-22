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
class DPCurve:
    """A pre-committed DP offer curve for one interval (§IV.6). At the realised price
    it dispatches the grid-aligned action m*(P) = argmax_m [ reward(P,m) + Ṽ(S⁺_m) ],
    where Ṽ = EK is the DP's post-decision continuation value for the (known) time-of-day
    and last-observed residual bin. This is the F_t-measurable execution of the DP's bid
    curve — the offer is built from state known at t; the realised price clears it."""

    EK: np.ndarray           # (N_S+1,) post-decision continuation value at (h, b_prev)
    E_max: float
    N_S: int
    psi_up: float = 0.0
    u_plan: dict = field(default_factory=dict)

    def dispatch(self, price, soc, params, E_max):
        dS = self.E_max / self.N_S
        j = int(min(max(round(soc / dS), 0), self.N_S))
        eta_c, eta_d, c_deg, dt, p = params.eta_c, params.eta_d, params.c_deg, params.dt, params.p_bar
        m_ch = int(np.floor(p * eta_c * dt / dS + 1e-9))
        m_di = int(np.floor(p * eta_d * dt / dS + 1e-9))
        best_val, best_m = -np.inf, 0
        for m in range(-m_di, m_ch + 1):
            jp = j + m
            if jp < 0 or jp > self.N_S:
                continue
            if m > 0:
                r = -(price + c_deg) * (m * dS / eta_c)      # charge (dt cancels)
            elif m < 0:
                r = (price - c_deg) * (-m * dS * eta_d)      # discharge
            else:
                r = 0.0
            val = r + self.EK[jp]
            if val > best_val:
                best_val, best_m = val, m
        if best_m > 0:
            c, d = best_m * dS / (eta_c * dt), 0.0
        elif best_m < 0:
            c, d = 0.0, -best_m * dS * eta_d / dt
        else:
            c = d = 0.0
        return _clip_charge(c, soc, params, E_max), _clip_discharge(d, soc, params, E_max)


@dataclass
class DPPolicy(Policy):
    """The optimal causal policy: execute the Stage 4 DP's offer curve (§IV.6), walked
    forward with NO lookahead. At interval t it reads the time-of-day and the LAST
    observed residual bin (both known at t), forms the DP continuation value Ṽ_h(·,b),
    and submits the implied offer curve; the realised price clears it (DPCurve). The
    realised profit is the value-of-information number V^DP of §IV.13."""

    V: np.ndarray                       # (H, N_S+1, N_b) DP value function
    kernel_matrices: np.ndarray         # (24, N_b, N_b) hour-indexed residual kernel
    edges: np.ndarray                   # residual bin edges
    seasonal: object                    # features.SeasonalMean
    ts: np.ndarray                      # panel timestamps
    E_max: float
    N_S: int
    product_set: dict = field(default_factory=lambda: oracle.ENERGY_ONLY)
    _m: np.ndarray = None               # precomputed seasonal per interval
    _qod: np.ndarray = None             # precomputed quarter-of-day per interval

    def __post_init__(self):
        import pandas as pd
        tsi = pd.to_datetime(pd.Series(self.ts))
        self._qod = (tsi.dt.hour * 4 + tsi.dt.minute // 15).to_numpy()
        self._m = self.seasonal.eval_ts(self.ts)
        self._H = self.V.shape[0]
        self._N_b = self.V.shape[2]

    def decide(self, soc, hist: History, E_max, params) -> DPCurve:
        t = len(hist.prices)
        h = int(self._qod[t]) if t < len(self._qod) else 0
        if t == 0:
            b = self._N_b // 2                          # neutral prior at the start
        else:
            resid_prev = hist.prices[t - 1] - self._m[t - 1]
            b = int(np.clip(np.digitize(resid_prev, self.edges[1:-1]), 0, self._N_b - 1))
        hour = h * 24 // self._H
        EK = self.V[(h + 1) % self._H] @ self.kernel_matrices[hour][b]   # (N_S+1,)
        return DPCurve(EK, self.E_max, self.N_S)


@dataclass
class WalkForwardDPPolicy(Policy):
    """The optimal causal policy, made LEAK-FREE (§VIII.3): the transition kernel, seasonal,
    bin edges, reserve prices and the DP solve are ALL re-fit online by calendar month on
    strictly-prior data (expanding window), exactly like the LearnedForecaster. So V^DP is
    genuinely out-of-sample (no in-sample kernel). During the warm-up (first `min_train_months`)
    it holds. With reserves on, it co-optimises energy + reserves and logs the causal ψ_up
    (Q2) along the trajectory via the DPCurve's `psi_up`."""

    panel: object                       # DataFrame with ts, price, and MCPC columns
    params: object
    E_max: float
    N_S: int = 200
    min_train_months: int = 2
    n_bins: int = 12
    reserves: bool = False
    rho: float = 0.05
    kernel_kind: str = "empirical"      # 'empirical' (count matrix) or 'learned' (GBT-integrated)
    product_set: dict = field(default_factory=lambda: oracle.ENERGY_ONLY)
    _cache: dict = None

    def __post_init__(self):
        import pandas as pd
        from src import features as F
        self._pd, self._F = pd, F
        self.ts = pd.to_datetime(self.panel["ts"]).reset_index(drop=True)
        self._qod = (self.ts.dt.hour * 4 + self.ts.dt.minute // 15).to_numpy()
        self._ym = self.ts.dt.to_period("M")
        self._months = list(self._ym.drop_duplicates())
        self._feat = F.build_features(self.panel)
        self._prices = self.panel["price"].to_numpy(float)
        self._cache = {}
        if self.reserves:
            self.product_set = oracle.CONTINGENCY

    def _fit_cutoff(self, cutoff):
        if cutoff in self._cache:
            return self._cache[cutoff]
        from src import dp, markov, reserves
        F = self._F
        train = (self._ym < cutoff).to_numpy()
        seasonal = F.fit_seasonal(self._feat.iloc[train])
        fr = F.add_residual_features(self._feat, seasonal)
        tr = fr.iloc[train].dropna(subset=["resid", "resid_lag_15min"])
        edges = markov.bin_edges(tr["resid"].to_numpy(float), n_bins=self.n_bins)
        if self.kernel_kind == "learned":
            from src.price_model import QuantileGBT
            gbt = QuantileGBT().fit(F.conditioning_matrix(tr), tr["resid"].to_numpy(float))
            ht = markov.transition_model(gbt, tr, edges)
        else:
            ht = markov.transition_counts(tr, edges)
        rep_month = int(self._feat.iloc[train].sort_values("ts")["month"].iloc[-1])
        prof = seasonal.eval_cal(np.arange(96), np.zeros(96, int), np.full(96, rep_month))
        rtabs = None
        if self.reserves:
            rp = reserves.hour_reserve_prices(self.panel.iloc[train])
            rtabs = reserves.build_reserve_tables(rp, self.params, self.E_max, self.rho)
        res = dp.solve_dp(ht.matrices, ht.bin_centers, prof, self.params, self.E_max,
                          N_S=self.N_S, reserve_tables=rtabs)
        art = (seasonal, ht.matrices, edges, res.V, res.reserve_psi)
        self._cache[cutoff] = art
        return art

    def decide(self, soc, hist: History, E_max, params) -> DPCurve:
        t = len(hist.prices)
        if t == 0 or self._ym.iloc[t] < self._months[self.min_train_months]:
            return CommittedDispatch(0.0, 0.0)          # warm-up: hold
        seasonal, K, edges, V, rpsi = self._fit_cutoff(self._ym.iloc[t])
        H, N_b = V.shape[0], V.shape[2]
        h = int(self._qod[t])
        m_prev = seasonal.eval_ts([self.ts.iloc[t - 1]])[0]
        b = int(np.clip(np.digitize(self._prices[t - 1] - m_prev, edges[1:-1]), 0, N_b - 1))
        hour = h * 24 // H
        EK = V[(h + 1) % H] @ K[hour][b]
        psi = 0.0
        if rpsi is not None:
            j = int(min(max(round(soc / (self.E_max / self.N_S)), 0), self.N_S))
            psi = float(rpsi[h, j, b])
        return DPCurve(EK, self.E_max, self.N_S, psi_up=psi)


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
