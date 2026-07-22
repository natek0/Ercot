"""
Point-in-time feature construction for the Stage 3 learned price model.

WHY THIS EXISTS SEPARATELY FROM THE WAREHOUSE. Stage 1 defines the feature
contract as SQL views in `src/warehouse.py` (v_features). But the Stage 2 backtest
hands a forecaster only a bare `prices[:t]` array — no DuckDB handle — so the live
MPC cannot read v_features at decision time. This module recomputes *exactly the
v_features columns* in pandas/numpy, giving ONE feature code-path usable both for
training (the fold harness) and for causal inference inside the MPC. A test
(`test_stage3.py::test_features_match_warehouse`) asserts the two agree row-for-row
on the real panel, so "quantile regression on the warehouse features" is honoured
literally, not just in spirit.

TWO NON-NEGOTIABLE PROPERTIES, both enforced by tests:

  1. Gap-safe lags. Real ERCOT data has holes (DST spring-forward, the early-May
     outage). Lags are computed by EXACT TIMESTAMP self-join (ts - INTERVAL), never
     a row offset, so a lag never silently points across a gap. This mirrors
     v_features (which uses the same timestamp join) rather than the row-offset
     shortcut SeasonalNaiveForecaster took in Stage 2.

  2. Adaptedness / publication timestamp (§VIII.1). Every CONDITIONING feature used
     to decide at interval t depends only on prices strictly BEFORE t. The interval's
     own price P_t has not cleared when the decision is made, so P_t may appear only
     in the TARGET, never in a conditioning feature. Concretely: the lag, rolling,
     residual-signal and scarcity features are all shifted to be as-of the previous
     interval; only the calendar of t itself (deterministic, known in advance) uses t.

HONEST SCOPE. The plan's feature vector f_t (§V.23) also names exogenous NWP
features — load / wind / solar forecasts and their vintages, reserve margin. Stage 1
ingested only the two price series, so those are NOT available here and are a named
deferral, not a silent omission. The feature set is: calendar + price lags
(15-min / 1-day / 1-week) + trailing 1-day rolling mean/std/z + a scarcity flag +
the deseasonalised residual signal. All are pure functions of past prices + the
known calendar, so the whole design matrix is point-in-time by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DAY = 96           # 15-minute intervals per day
WEEK = 7 * DAY     # 672
SCARCITY_LEVEL = 100.0   # $/MWh marker, matches warehouse v_features


# --------------------------------------------------------------------------- #
# Calendar (deterministic function of the timestamp — known in advance)       #
# --------------------------------------------------------------------------- #
def calendar_frame(ts: pd.Series) -> pd.DataFrame:
    """Calendar features from a timestamp series, matching warehouse v_calendar.

    dow uses DuckDB's convention (0=Sunday .. 6=Saturday) so it lines up with the
    warehouse; pandas' `dayofweek` is Monday=0, hence the (+1) % 7 shift.
    """
    ts = pd.to_datetime(ts)
    qod = ts.dt.hour * 4 + ts.dt.minute // 15          # 0..95
    dow_duckdb = (ts.dt.dayofweek + 1) % 7             # 0=Sun..6=Sat
    return pd.DataFrame({
        "hour_of_day": ts.dt.hour.astype(int),
        "quarter_of_day": qod.astype(int),
        "dow": dow_duckdb.astype(int),
        "is_weekend": dow_duckdb.isin([0, 6]).astype(int),
        "month": ts.dt.month.astype(int),
        # smooth periodic encodings so the trees can split time-of-day cheaply
        "qod_sin": np.sin(2 * np.pi * qod / DAY),
        "qod_cos": np.cos(2 * np.pi * qod / DAY),
    })


# --------------------------------------------------------------------------- #
# The full point-in-time feature frame                                        #
# --------------------------------------------------------------------------- #
def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """One row per interval with calendar, timestamp-keyed price lags, and trailing
    rolling stats — exactly the v_features columns (verified equal by a test).

    Input: DataFrame with columns `ts` (datetime) and `price`, one settlement point,
    sorted ascending. Output preserves that order and adds:
      price_lag_15min, price_lag_1d, price_lag_1w   (exact-timestamp lags; NaN in gaps)
      price_roll_mean_1d, price_roll_std_1d         (trailing 96 rows, EXCLUDING current)
      price_z_1d                                    ((price - mean)/std; uses current price)
      is_scarcity                                   (price > 100; uses current price)
    plus the calendar_frame columns. `price_z_1d`/`is_scarcity` reference the current
    price and are therefore TARGET-side (see conditioning_matrix, which excludes them).
    """
    df = df[["ts", "price"]].copy()
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.sort_values("ts").reset_index(drop=True)

    # exact-timestamp lags (gap-safe): merge price onto (ts - delta)
    price_at = df.set_index("ts")["price"]
    # np.timedelta64 (not pd.Timedelta) to dodge a pandas 2.3 / numpy 2.5 construction
    # deprecation; the arithmetic below is identical.
    for name, delta in (("price_lag_15min", np.timedelta64(15, "m")),
                        ("price_lag_1d", np.timedelta64(1, "D")),
                        ("price_lag_1w", np.timedelta64(7, "D"))):
        keys = df["ts"] - delta
        df[name] = keys.map(price_at)     # NaN where the lagged timestamp is absent

    # trailing 1-day rolling over the previous 96 rows (shift(1) => strictly past),
    # matching v_features' "ROWS BETWEEN 96 PRECEDING AND 1 PRECEDING".
    prev = df["price"].shift(1)
    df["price_roll_mean_1d"] = prev.rolling(DAY, min_periods=1).mean()
    df["price_roll_std_1d"] = prev.rolling(DAY, min_periods=2).std(ddof=1)

    # current-price-referencing columns (TARGET-side; excluded from conditioning)
    std = df["price_roll_std_1d"]
    df["price_z_1d"] = np.where(std > 0, (df["price"] - df["price_roll_mean_1d"]) / std, np.nan)
    df["is_scarcity"] = (df["price"] > SCARCITY_LEVEL).astype(int)

    cal = calendar_frame(df["ts"])
    return pd.concat([df, cal], axis=1)


# Conditioning features: everything the model may read at decision time t. Strictly
# past + calendar-of-t. Deliberately EXCLUDES price_z_1d and is_scarcity (they use the
# not-yet-cleared current price) and the raw current price.
CONDITIONING = [
    "hour_of_day", "quarter_of_day", "dow", "is_weekend", "month", "qod_sin", "qod_cos",
    "price_lag_15min", "price_lag_1d", "price_lag_1w",
    "price_roll_mean_1d", "price_roll_std_1d",
    "resid_lag_15min", "resid_roll_mean_1d", "scarcity_recent",
]


# --------------------------------------------------------------------------- #
# Seasonal component m(quarter_of_day, is_weekend), fit per fold               #
# --------------------------------------------------------------------------- #
@dataclass
class SeasonalMean:
    """Deseasonaliser m(quarter_of_day, is_weekend, month), per plan §V.26 step 1 /
    §V.24 m(h, daytype, month). Robust (median) so a single spike day does not distort
    the profile. FIT ON TRAINING ROWS ONLY — a global fit before the walk-forward loop
    leaks the future (§VIII.3).

    THE MONTH TERM AND WHY IT IS A *LEVEL EXTRAPOLATION*, NOT A groupby(month). The
    obvious implementation — grouping on month alongside qod/weekend — silently makes
    things WORSE under expanding-window folds: the evaluation month is by construction
    never in the training slice, so every eval cell misses and falls back to the global
    median, discarding the intra-day shape. Instead the model is separable:

        m(qod, weekend, month) = shape(qod, weekend)  +  level(month)

    where `shape` is the (month-detrended) intra-day/weekend profile and `level(month)`
    is a per-month price level. For an unseen future month, `level` is EXTRAPOLATED as
    the most recent training month's level (persistence) — so the residual it produces
    stays centred instead of drifting up over the warming season (which was mischaracter-
    ised as under-dispersion before this fix). Verified a strict improvement in held-out
    CRPS and PIT-KS over the month-free variant."""

    shape: dict           # (quarter_of_day, is_weekend) -> intra-day/weekend offset
    month_level: dict     # month (1..12) -> price level, TRAINING months only
    persist_level: float  # most recent training month's level (unseen-month fallback)
    global_median: float

    def _level(self, month: int) -> float:
        return self.month_level.get(int(month), self.persist_level)

    def eval_cal(self, quarter_of_day, is_weekend, month) -> np.ndarray:
        q = np.asarray(quarter_of_day, int)
        w = np.asarray(is_weekend, int)
        mo = np.asarray(month, int)
        return np.array([self.shape.get((qi, wi), 0.0) + self._level(mi)
                         for qi, wi, mi in zip(q, w, mo)], float)

    def eval_ts(self, ts) -> np.ndarray:
        cal = calendar_frame(pd.Series(pd.to_datetime(ts)))
        return self.eval_cal(cal["quarter_of_day"].to_numpy(),
                             cal["is_weekend"].to_numpy(), cal["month"].to_numpy())


def fit_seasonal(feat_train: pd.DataFrame) -> SeasonalMean:
    """Fit m on a TRAINING slice of build_features() output. Separable month level +
    intra-day shape (see SeasonalMean); the unseen-month fallback is the latest training
    month's level, found by timestamp (correct across the Dec→Jan year boundary)."""
    df = feat_train
    ml = df.groupby("month")["price"].median()
    month_level = {int(m): float(v) for m, v in ml.items()}
    latest_month = int(df.sort_values("ts")["month"].iloc[-1])   # newest by calendar
    gmed = float(df["price"].median())
    persist_level = month_level.get(latest_month, gmed)
    # intra-day/weekend shape on the MONTH-DETRENDED price
    detrended = df["price"] - df["month"].map(month_level)
    g = detrended.groupby([df["quarter_of_day"], df["is_weekend"]]).median()
    shape = {(int(q), int(w)): float(v) for (q, w), v in g.items()}
    return SeasonalMean(shape=shape, month_level=month_level,
                        persist_level=float(persist_level), global_median=gmed)


# --------------------------------------------------------------------------- #
# Assemble the model design matrix + residual target from a fitted seasonal    #
# --------------------------------------------------------------------------- #
def add_residual_features(feat: pd.DataFrame, seasonal: SeasonalMean) -> pd.DataFrame:
    """Attach the deseasonalised residual and its strictly-past derived signals.

    resid          = price - m(t)                    (TARGET-side: uses current price)
    resid_lag_15min = price_{t-1} - m(t-1)           (conditioning: strictly past)
    resid_roll_mean_1d = trailing mean of resid      (conditioning: shift(1), strictly past)
    scarcity_recent = 1{price_{t-1} > 100}           (conditioning: strictly past)
    """
    out = feat.copy()
    m_now = seasonal.eval_cal(out["quarter_of_day"].to_numpy(),
                              out["is_weekend"].to_numpy(), out["month"].to_numpy())
    out["seasonal"] = m_now
    out["resid"] = out["price"].to_numpy() - m_now
    # resid_lag_15min is built from the GAP-SAFE price lag (not a row shift): it is
    # price_{t-1} - m(t-1), and is NaN exactly where price_lag_15min is NaN (a data
    # gap), so cross-gap pairs never enter the AR/jump fit or the transition counts.
    m_prev = seasonal.eval_ts((out["ts"] - np.timedelta64(15, "m")).to_numpy())
    out["resid_lag_15min"] = out["price_lag_15min"].to_numpy() - m_prev
    out["resid_roll_mean_1d"] = out["resid"].shift(1).rolling(DAY, min_periods=1).mean()
    out["scarcity_recent"] = (out["price_lag_15min"] > SCARCITY_LEVEL).astype(float)
    return out


def conditioning_matrix(feat_resid: pd.DataFrame) -> np.ndarray:
    """The (n, p) float design matrix X of conditioning features, in CONDITIONING order.
    Rows with any NaN (early history before lags exist) are the caller's to mask."""
    return feat_resid[CONDITIONING].to_numpy(float)
