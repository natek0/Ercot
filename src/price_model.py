"""
Stage 3 learned conditional price distribution + the two baselines it must beat.

We predict not a point but a CONDITIONAL PREDICTIVE DISTRIBUTION of the next
interval's deseasonalised residual r_t = P_t - m(t) given the point-in-time feature
vector f_t (§V.23). Working on the residual (rather than raw price) keeps the target
roughly stationary across hours, so one set of models serves every horizon and the
same object drops straight into the hour-indexed transition matrix (src/markov.py).

Three models, all exposing `.predict_quantiles(feat_resid) -> (n, n_levels)` so they
score head-to-head on identical held-out folds (§V.26 "adopt the learned model only
if it wins on held-out CRPS"):

  QuantileGBT        gradient-boosted trees, one per quantile level, pinball loss
                     (§V.24), isotonic-rearranged so quantiles never cross (§V.24
                     monotonicity). THE learned model.
  EmpiricalCond      the count-based conditional distribution — the nonparametric
                     baseline of §V.26: the empirical next-residual distribution
                     conditioned on (hour, current-residual bin). Robust, and "may
                     well be adequate"; a tie is a publishable finding, not a failure.
  MeanRevertJump     the parametric baseline of §V.24: AR(1) mean reversion on the
                     residual + a 2-component Gaussian-mixture innovation (the "jump").

Scoring (§V.25): pinball loss, CRPS (= pinball integrated over levels, computed here
by trapezoid over the level grid), and the PIT for calibration. All proper /
distribution-free; propriety is what stops a model gaming the metric.

Fitting discipline (§VIII.3): every object here is fit on a TRAINING slice only and
re-fit inside each walk-forward fold by src/walkforward.py. Nothing here fits globally.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.mixture import GaussianMixture

from src import features as F

# Quantile grid. Denser in the tails, where the option value lives (§V.26); the
# extreme 0.005/0.995 knots resolve the spike tail the DP holds charge against and
# push the PIT-clamp boundary further out.
LEVELS = np.array([0.005, 0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99, 0.995])


# --------------------------------------------------------------------------- #
# Scoring rules (§V.25)                                                        #
# --------------------------------------------------------------------------- #
def pinball_loss(y: np.ndarray, q: np.ndarray, levels=LEVELS) -> float:
    """Mean pinball loss over samples and levels. q is (n, n_levels)."""
    y = np.asarray(y, float)[:, None]
    q = np.asarray(q, float)
    u = y - q
    return float(np.mean(np.maximum(levels * u, (levels - 1) * u)))


def crps_from_quantiles(y: np.ndarray, q: np.ndarray, levels=LEVELS) -> np.ndarray:
    """Per-sample CRPS via the identity CRPS = 2 ∫_0^1 ρ_α(y - q_α) dα (§V.25),
    trapezoid-integrated over the FULL [0, 1] level range. Returns (n,).

    The grid is padded with α=0 and α=1 (holding the extreme modelled quantiles flat),
    so the tail slabs [0, levels[0]] and [levels[-1], 1] are integrated rather than
    dropped — a truncated grid silently under-penalises under-dispersed tails, exactly
    the heavy-tail regime this project scores in. At α=0, ρ_0(u)=(-u)^+; at α=1,
    ρ_1(u)=u^+; both use the outermost modelled quantile as the endpoint value."""
    y = np.asarray(y, float)[:, None]
    q = np.asarray(q, float)
    ext_levels = np.concatenate(([0.0], levels, [1.0]))
    ext_q = np.concatenate((q[:, :1], q, q[:, -1:]), axis=1)   # flat-extend the tails
    u = y - ext_q
    rho = np.maximum(ext_levels * u, (ext_levels - 1) * u)      # (n, L+2)
    return 2.0 * np.trapezoid(rho, ext_levels, axis=1)


def pit_values(y: np.ndarray, q: np.ndarray, levels=LEVELS) -> np.ndarray:
    """Probability integral transform u_t = F̂(y_t), by interpolating the level as a
    function of the predicted quantile value. Flat histogram of u => calibrated
    (§V.25). Quantiles are rearranged per row first so the interpolation is monotone."""
    y = np.asarray(y, float)
    q = np.sort(np.asarray(q, float), axis=1)
    out = np.empty(len(y))
    for i in range(len(y)):
        out[i] = np.interp(y[i], q[i], levels, left=0.0, right=1.0)
    return out


def rearrange(q: np.ndarray, levels=LEVELS) -> np.ndarray:
    """Monotone rearrangement in α at each row: SORT the fitted quantiles ascending.
    This is precisely the rearrangement operator of Chernozhukov–Fernández-Val–Galichon
    whose theorem guarantees the pinball loss does not increase (§V.24) — an earlier
    version used isotonic (PAVA) L2 projection, which is monotone but is a different
    operator the theorem does not cover (and is weakly dominated by the sort)."""
    return np.sort(np.asarray(q, float), axis=1)


# --------------------------------------------------------------------------- #
# Model 1 — the learned quantile GBT                                          #
# --------------------------------------------------------------------------- #
@dataclass
class QuantileGBT:
    """One HistGradientBoostingRegressor per quantile level, pinball loss.
    predict_quantiles rearranges to enforce monotonicity."""

    levels: np.ndarray = field(default_factory=lambda: LEVELS)
    max_iter: int = 200
    max_depth: int = 3
    learning_rate: float = 0.05
    min_samples_leaf: int = 60
    l2_regularization: float = 1.0
    models: dict = field(default_factory=dict)

    def fit(self, X: np.ndarray, y: np.ndarray) -> "QuantileGBT":
        for a in self.levels:
            m = HistGradientBoostingRegressor(
                loss="quantile", quantile=float(a),
                max_iter=self.max_iter, max_depth=self.max_depth,
                learning_rate=self.learning_rate,
                min_samples_leaf=self.min_samples_leaf,
                l2_regularization=self.l2_regularization,
                random_state=0,
            )
            m.fit(X, y)
            self.models[float(a)] = m
        return self

    def predict_quantiles(self, feat_resid: pd.DataFrame) -> np.ndarray:
        X = F.conditioning_matrix(feat_resid)
        cols = [self.models[float(a)].predict(X) for a in self.levels]
        return rearrange(np.column_stack(cols), self.levels)


# --------------------------------------------------------------------------- #
# Model 2 — empirical conditional distribution (§V.26 count-based baseline)   #
# --------------------------------------------------------------------------- #
@dataclass
class EmpiricalCond:
    """The next-residual distribution conditioned on (hour_of_day, current-residual
    bin), estimated by pooling training residuals into cells and reading empirical
    quantiles. This IS the count-based transition matrix, evaluated as a predictive
    CDF. Falls back cell -> hour-marginal -> global when a cell is thin."""

    n_bins: int = 12
    levels: np.ndarray = field(default_factory=lambda: LEVELS)
    edges: np.ndarray = field(default=None)
    cells: dict = field(default_factory=dict)     # (hour, bin) -> quantile vector
    hour_marg: dict = field(default_factory=dict)  # hour -> quantile vector
    global_q: np.ndarray = field(default=None)

    def _bin(self, r):
        return np.clip(np.digitize(r, self.edges[1:-1]), 0, self.n_bins - 1)

    def fit(self, feat_resid: pd.DataFrame) -> "EmpiricalCond":
        df = feat_resid.dropna(subset=["resid", "resid_lag_15min"])
        r = df["resid"].to_numpy(float)
        r_prev = df["resid_lag_15min"].to_numpy(float)
        hour = df["hour_of_day"].to_numpy(int)
        # equal-probability (empirical-quantile) edges on the previous residual; this
        # is the plain baseline binning, NOT the tail-refined markov.bin_edges
        qs = np.linspace(0, 1, self.n_bins + 1)
        self.edges = np.quantile(r_prev, qs)
        self.edges[0], self.edges[-1] = -np.inf, np.inf
        self.global_q = np.quantile(r, self.levels)
        prev_bin = self._bin(r_prev)
        for h in range(24):
            hm = hour == h
            if hm.sum() >= len(self.levels):
                self.hour_marg[h] = np.quantile(r[hm], self.levels)
            for b in range(self.n_bins):
                cm = hm & (prev_bin == b)
                if cm.sum() >= max(len(self.levels), 8):
                    self.cells[(h, b)] = np.quantile(r[cm], self.levels)
        return self

    def predict_quantiles(self, feat_resid: pd.DataFrame) -> np.ndarray:
        hour = feat_resid["hour_of_day"].to_numpy(int)
        r_prev = np.nan_to_num(feat_resid["resid_lag_15min"].to_numpy(float))
        b = self._bin(r_prev)
        out = np.empty((len(feat_resid), len(self.levels)))
        for i in range(len(feat_resid)):
            out[i] = self.cells.get((hour[i], b[i]),
                                    self.hour_marg.get(hour[i], self.global_q))
        return out


# --------------------------------------------------------------------------- #
# Model 3 — parametric mean-reverting jump model (§V.24 baseline)             #
# --------------------------------------------------------------------------- #
@dataclass
class MeanRevertJump:
    """r_t = phi * r_{t-1} + e_t, with e_t a 2-component Gaussian mixture (a calm
    component + a heavy 'jump' component). The classic parametric power-price form,
    retained as a baseline to beat — NOT the model (§V.24). Predictive quantiles at
    r_prev are phi*r_prev shifted by the mixture-innovation quantiles."""

    levels: np.ndarray = field(default_factory=lambda: LEVELS)
    phi: float = 0.0
    gmm: GaussianMixture = None
    _grid: np.ndarray = None
    _cdf: np.ndarray = None

    def fit(self, feat_resid: pd.DataFrame) -> "MeanRevertJump":
        df = feat_resid.dropna(subset=["resid", "resid_lag_15min"])
        r = df["resid"].to_numpy(float)
        r_prev = df["resid_lag_15min"].to_numpy(float)
        denom = float(r_prev @ r_prev)
        self.phi = float(np.clip((r_prev @ r) / denom, 0.0, 0.999)) if denom > 0 else 0.0
        e = (r - self.phi * r_prev).reshape(-1, 1)
        self.gmm = GaussianMixture(n_components=2, covariance_type="full",
                                   random_state=0, n_init=2).fit(e)
        # tabulate the innovation CDF on a fine grid, then invert for quantiles
        lo, hi = np.quantile(e, 0.0005), np.quantile(e, 0.9995)
        pad = 0.5 * (hi - lo) + 1.0
        self._grid = np.linspace(lo - pad, hi + pad, 4000)
        from scipy.stats import norm
        means = self.gmm.means_.ravel()
        sds = np.sqrt(self.gmm.covariances_.ravel())
        self._cdf = sum(wi * norm.cdf(self._grid, mi, si)
                        for wi, mi, si in zip(self.gmm.weights_, means, sds))
        return self

    def _innov_quantiles(self) -> np.ndarray:
        return np.interp(self.levels, self._cdf, self._grid)

    def predict_quantiles(self, feat_resid: pd.DataFrame) -> np.ndarray:
        r_prev = np.nan_to_num(feat_resid["resid_lag_15min"].to_numpy(float))
        innov = self._innov_quantiles()[None, :]
        return self.phi * r_prev[:, None] + innov


# --------------------------------------------------------------------------- #
# AR(1) decay for the MPC point-forecast path                                 #
# --------------------------------------------------------------------------- #
def fit_ar1_phi(feat_resid: pd.DataFrame) -> float:
    """Least-squares AR(1) coefficient of the residual (for the mean-reverting decay
    of the point-forecast path). Clipped to [0, 0.999]."""
    df = feat_resid.dropna(subset=["resid", "resid_lag_15min"])
    r = df["resid"].to_numpy(float)
    rp = df["resid_lag_15min"].to_numpy(float)
    denom = float(rp @ rp)
    return float(np.clip((rp @ r) / denom, 0.0, 0.999)) if denom > 0 else 0.0
