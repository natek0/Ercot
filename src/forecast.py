"""
Price forecasters for the Stage 2 MPC (docs plan Part XIV Stage 2).

An MPC controller needs a *view of the future* to plan against. Stage 2 starts
with simple, transparent forecasts on purpose — so when the controller misbehaves
we are debugging one thing (the controller), not a controller tangled with a
fancy model. Stage 3 swaps in the learned quantile model behind the same
interface without touching the controller.

THE load-bearing property is causality: a forecast made to plan interval t may
use ONLY prices strictly before t. Every forecaster here takes `history` =
prices[:t] (the realised past) and returns a length-`horizon` prediction for
intervals t, t+1, ..., t+horizon-1. It never sees the present or future. The
backtest enforces this by construction (it only ever hands over prices[:t]); the
tests verify a forecast at t is unchanged when prices[t:] are perturbed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DAY = 96          # 15-minute intervals per day
WEEK = 7 * DAY    # 672


class Forecaster:
    """Interface: predict the next `horizon` prices from the realised past."""

    def predict(self, history: np.ndarray, horizon: int) -> np.ndarray:
        raise NotImplementedError


@dataclass
class PersistenceForecaster(Forecaster):
    """Flat forecast at the last observed price. The crudest honest baseline."""

    def predict(self, history: np.ndarray, horizon: int) -> np.ndarray:
        last = history[-1] if len(history) else 0.0
        return np.full(horizon, float(last))


@dataclass
class SeasonalNaiveForecaster(Forecaster):
    """Forecast interval t+k as the price at the same 15-minute slot one `period`
    ago (t+k-period). period=WEEK captures ERCOT's day-of-week + time-of-day shape;
    period=DAY captures just the daily shape. Zero fitting, strictly causal for any
    horizon < period (t+k-period is always in the realised past). Falls back to
    persistence before `period` intervals of history exist."""

    period: int = WEEK
    fallback: Forecaster = None

    def __post_init__(self):
        if self.fallback is None:
            self.fallback = PersistenceForecaster()

    def predict(self, history: np.ndarray, horizon: int) -> np.ndarray:
        n = len(history)
        if n < self.period:
            return self.fallback.predict(history, horizon)
        out = np.empty(horizon)
        for k in range(horizon):
            idx = n + k - self.period      # same slot one period before interval t+k
            out[k] = history[idx] if idx < n else history[-1]
        return out


def SameHourLastWeekForecaster() -> SeasonalNaiveForecaster:
    """The Stage 2 default forecast: same 15-minute slot one week ago."""
    return SeasonalNaiveForecaster(period=WEEK)


@dataclass
class PerfectForecaster(Forecaster):
    """CEILING REFERENCE ONLY — it sees the future (NOT causal, never a real
    policy). Fed to the MPC, it yields the profit a perfect forecast achieves
    under the SAME realistic causal execution as the live MPC, which isolates the
    execution + startup cost (ceiling - clairvoyant-MPC) from the forecast-error
    cost (clairvoyant-MPC - naive-MPC = the pure value of a better forecast)."""

    full: np.ndarray

    def predict(self, history: np.ndarray, horizon: int) -> np.ndarray:
        n = len(history)
        fut = np.asarray(self.full[n:n + horizon], float)
        if len(fut) < horizon:                      # pad past the end of the series
            pad = fut[-1] if len(fut) else (history[-1] if len(history) else 0.0)
            fut = np.concatenate([fut, np.full(horizon - len(fut), pad)])
        return fut


@dataclass
class LearnedForecaster(Forecaster):
    """Stage 3's forecast: the learned conditional price model behind the SAME
    .predict(history, horizon) contract the MPC already consumes. The point path is

        P̂_{t+ℓ} = m(t+ℓ)  +  phi^ℓ · r̂_t ,    ℓ = 0 .. horizon-1

    the deseasonalised seasonal mean m at the (known) future calendar cell, plus the
    GBT-median one-step residual r̂_t = q̂_0.5(f_t) decaying at the residual's AR(1)
    rate phi. The certainty-equivalent MPC consumes only this mean; the FULL predictive
    distribution (all quantiles) is scored in src/walkforward and feeds the Stage 4 DP.

    CAUSALITY — two layers, both leak-free:
      * The model is RE-FIT ONLINE by calendar month (walk-forward, §VIII.3): at row t
        it is trained only on COMPLETE months strictly before t's month, cached per
        cutoff. So every prediction in a full-window backtest is out-of-sample and
        directly comparable to the Stage-2 naive-MPC number.
      * Conditioning features at t are strictly-past (src/features.CONDITIONING), read
        from a feature frame precomputed on the full panel — legitimate because each
        feature row depends only on rows <= its own index (a test asserts the frame's
        row t equals the frame rebuilt from prices[:t]).

    Constructed with the panel's own `ts` and `prices` (like PerfectForecaster holds
    `full`); n = len(history) is the absolute row index. Falls back to a seasonal-naive
    forecast until `min_train_months` of history exist.
    """

    ts: object                        # (T,) panel timestamps (np.datetime64 or pandas)
    prices: np.ndarray                # (T,) panel prices — SAME array the backtest marches
    min_train_months: int = 2
    fallback: Forecaster = None
    _feat: object = None              # precomputed full-panel feature frame (lazy)
    _cache: dict = None               # training-cutoff Period -> (seasonal, q50_model, phi)

    def __post_init__(self):
        import pandas as pd
        from src import features as F
        self._pd = pd
        self._F = F
        self.ts = pd.to_datetime(pd.Series(self.ts)).reset_index(drop=True)
        self.prices = np.asarray(self.prices, float)
        if self.fallback is None:
            self.fallback = SeasonalNaiveForecaster(period=WEEK)
        self._ym = self.ts.dt.to_period("M")
        self._months = list(self._ym.drop_duplicates())
        self._feat = F.build_features(
            pd.DataFrame({"ts": self.ts, "price": self.prices}))
        self._cache = {}

    def _fit_cutoff(self, cutoff_period):
        """Fit (seasonal, q50 model, phi) on all rows in months strictly before
        `cutoff_period`. Cached — refits only when the month boundary advances."""
        if cutoff_period in self._cache:
            return self._cache[cutoff_period]
        F = self._F
        train_mask = (self._ym < cutoff_period).to_numpy()
        seasonal = F.fit_seasonal(self._feat.iloc[train_mask])
        fr = F.add_residual_features(self._feat, seasonal)
        tr = fr.iloc[train_mask].dropna(subset=F.CONDITIONING + ["resid"])
        from src.price_model import QuantileGBT, fit_ar1_phi
        q50 = QuantileGBT(levels=np.array([0.5])).fit(
            F.conditioning_matrix(tr), tr["resid"].to_numpy(float))
        phi = fit_ar1_phi(tr)
        self._cache[cutoff_period] = (seasonal, fr, q50, phi)
        return self._cache[cutoff_period]

    def predict(self, history: np.ndarray, horizon: int) -> np.ndarray:
        n = len(history)
        # not enough complete months of history yet -> seasonal-naive fallback
        if n == 0 or self._ym.iloc[n] < self._months[self.min_train_months]:
            return self.fallback.predict(history, horizon)

        cutoff = self._ym.iloc[n]                      # train on months strictly before this
        seasonal, fr, q50, phi = self._fit_cutoff(cutoff)

        # anchor residual forecast r̂_t from the strictly-past features at row n
        X = self._F.conditioning_matrix(fr.iloc[[n]])
        if not np.isfinite(X).all():                  # a lag not yet available
            return self.fallback.predict(history, horizon)
        r_hat = float(q50.models[0.5].predict(X)[0])

        # future calendar: use the panel's real ts where available (gap-aware), then
        # extrapolate a regular 15-min grid past the panel's end.
        idx = np.arange(n, n + horizon)
        in_range = idx < len(self.ts)
        fut_ts = np.empty(horizon, dtype="datetime64[ns]")
        fut_ts[in_range] = self.ts.to_numpy()[idx[in_range]]
        if (~in_range).any():
            last = self.ts.iloc[-1]
            k = (idx[~in_range] - (len(self.ts) - 1))
            fut_ts[~in_range] = (last + self._pd.to_timedelta(k * 15, unit="m")).to_numpy()

        m = seasonal.eval_ts(fut_ts)
        decay = phi ** np.arange(horizon)
        return m + decay * r_hat
