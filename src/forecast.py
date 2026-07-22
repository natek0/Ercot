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
