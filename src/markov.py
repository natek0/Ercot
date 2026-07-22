"""
Hour-indexed transition matrices on the deseasonalised residual (§V.26).

The Stage 4 dynamic program's Bellman equation needs E[V_{h+1} | x_t], i.e. a
transition kernel P(x_{t+1} | x_t) on the TABULATED price state, not the raw
predictive distribution F̂. This module turns either a fitted price model
(src/price_model) or raw counts into that kernel:

  1. Bin the residual with NON-UNIFORM edges that are dense in the right tail
     (§V.26 step 2). Uniform bins would collapse the whole spike region into one
     cell and the DP would never see the option value it exists to capture. Edges
     are empirical quantiles of the training residual, refined above the 95th pct.
  2. Build ONE transition matrix per hour-of-day (§V.26 step 4): residual volatility
     and spike intensity are strongly hour-dependent, so a pooled matrix is
     misspecified in exactly the evening-peak region that matters.
  3. Verify every row sums to one and the chain is irreducible (assumption [A2]).

Two constructors, matching the two comparators of §V.26:
  transition_counts(...)  — the empirical count-based matrix (the baseline).
  transition_model(...)   — integrate a fitted predictive distribution over the
                            successor bins (the learned matrix).

Both are FIT PER FOLD (edges included) by src/walkforward — a global fit leaks.
Consumed by Stage 4; built and validated here so that stage inherits a checked object.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.price_model import LEVELS


@dataclass
class HourlyTransition:
    edges: np.ndarray               # (n_bins+1,) residual bin edges, ends at ±inf
    matrices: np.ndarray            # (24, n_bins, n_bins) row-stochastic per hour
    bin_centers: np.ndarray         # (n_bins,) representative residual per bin
    counts: np.ndarray = None       # (24, n_bins, n_bins) raw counts, if available

    @property
    def n_bins(self) -> int:
        return len(self.edges) - 1

    def bin_of(self, resid) -> np.ndarray:
        return np.clip(np.digitize(resid, self.edges[1:-1]), 0, self.n_bins - 1)

    def check(self, tol: float = 1e-9) -> dict:
        """Row-sum-to-one and irreducibility (§V.26 step 5), reported as TWO things:

          `irreducible`        — strong connectivity of the actual MATRIX support
                                 (rows with mass > tol). This is the property the DP
                                 needs; the small smoothing prior guarantees it.
          `counts_irreducible` — strong connectivity of the UNSMOOTHED count support
                                 (empirical matrix only; None for the model matrix). This
                                 is the honest statement about the *observed process* —
                                 if it is False, the smoothing prior is doing load-bearing
                                 work and the DP result on thin hours should be read with
                                 that in mind. Reporting both avoids the trap where a
                                 smoothing prior makes `irreducible` vacuously true."""
        row_sums = self.matrices.sum(axis=2)
        max_rowsum_err = float(np.max(np.abs(row_sums - 1.0)))
        matrix_irr = all(_strongly_connected(self.matrices[h] > tol) for h in range(24))
        counts_irr = (all(_strongly_connected(self.counts[h] > 0) for h in range(24))
                      if self.counts is not None else None)
        return {"max_rowsum_err": max_rowsum_err, "irreducible": bool(matrix_irr),
                "counts_irreducible": counts_irr}


def bin_edges(resid_train: np.ndarray, n_bins: int = 12, tail_from: float = 0.95) -> np.ndarray:
    """Empirical-quantile edges, REFINED above `tail_from` so the right tail gets
    extra resolution (§V.26 step 2). Ends are ±inf so every value lands in a bin.

    ~70% of the interior edges are placed on the body (0..tail_from) and the rest
    packed into the tail, which is where the DP's hold-for-a-spike decision is made.
    """
    resid_train = np.asarray(resid_train, float)
    n_tail = max(2, n_bins // 4)
    n_body = n_bins - n_tail
    body = np.quantile(resid_train, np.linspace(0.0, tail_from, n_body, endpoint=False))
    tail = np.quantile(resid_train, np.linspace(tail_from, 1.0, n_tail + 1))
    interior = np.unique(np.concatenate([body[1:], tail]))   # drop the 0-pct duplicate
    edges = np.concatenate([[-np.inf], interior[:-1], [np.inf]])
    return edges


def _bin_centers(resid_train: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Representative residual per bin = mean of training residuals in the bin
    (finite proxy for the ±inf end bins), so Stage 4 can price each state."""
    n_bins = len(edges) - 1
    b = np.clip(np.digitize(resid_train, edges[1:-1]), 0, n_bins - 1)
    centers = np.empty(n_bins)
    for j in range(n_bins):
        m = b == j
        centers[j] = resid_train[m].mean() if m.any() else 0.5 * (
            edges[max(j, 1) if np.isinf(edges[j]) else j]
            + edges[min(j + 1, n_bins - 1) if np.isinf(edges[j + 1]) else j + 1])
    return centers


def transition_counts(feat_resid: pd.DataFrame, edges: np.ndarray,
                      smoothing: float = 0.01) -> HourlyTransition:
    """Empirical count-based hour-indexed matrix (the §V.26 baseline).

    A SMALL Laplace prior (default 0.01, i.e. ≈0.01·n_bins ≈ 0.1 pseudo-count per row
    vs hundreds of real counts) keeps the *matrix* strictly positive so the chain the
    DP consumes is irreducible — but is negligible for the CRPS/capture comparison.
    This replaces an earlier prior of 1.0, which put ~20% of a typical row's mass into
    the uniform prior (handicapping the baseline) AND made the irreducibility check
    vacuous. `check()` reads irreducibility off the UNSMOOTHED counts, so it remains a
    genuine statement about the observed process regardless of the prior."""
    df = feat_resid.dropna(subset=["resid", "resid_lag_15min"])
    n_bins = len(edges) - 1
    b_now = np.clip(np.digitize(df["resid"].to_numpy(float), edges[1:-1]), 0, n_bins - 1)
    b_prev = np.clip(np.digitize(df["resid_lag_15min"].to_numpy(float), edges[1:-1]), 0, n_bins - 1)
    hour = df["hour_of_day"].to_numpy(int)
    counts = np.zeros((24, n_bins, n_bins))
    for h, bp, bn in zip(hour, b_prev, b_now):
        counts[h, bp, bn] += 1.0
    smoothed = counts + smoothing
    matrices = smoothed / smoothed.sum(axis=2, keepdims=True)
    centers = _bin_centers(df["resid"].to_numpy(float), edges)
    return HourlyTransition(edges, matrices, centers, counts)


def transition_model(model, feat_resid: pd.DataFrame, edges: np.ndarray) -> HourlyTransition:
    """Learned matrix: integrate a fitted predictive distribution over successor bins
    (§V.26 step 3). For each hour and current bin, average each training row's
    predicted successor-bin probabilities (from the model's quantile CDF) over the
    training observations that fall in that (hour, current-bin) cell."""
    df = feat_resid.dropna(subset=["resid", "resid_lag_15min"]).reset_index(drop=True)
    n_bins = len(edges) - 1
    q = model.predict_quantiles(df)                      # (n, L) residual quantiles
    q = np.sort(q, axis=1)
    # P(next residual <= edge) by interpolating the level onto the quantile grid
    interior = edges[1:-1]
    cdf_at = np.empty((len(df), len(interior)))
    for i in range(len(df)):
        cdf_at[i] = np.interp(interior, q[i], LEVELS, left=0.0, right=1.0)
    probs = np.diff(np.column_stack([np.zeros(len(df)), cdf_at, np.ones(len(df))]), axis=1)
    b_prev = np.clip(np.digitize(df["resid_lag_15min"].to_numpy(float), interior), 0, n_bins - 1)
    hour = df["hour_of_day"].to_numpy(int)
    matrices = np.zeros((24, n_bins, n_bins))
    for h in range(24):
        for b in range(n_bins):
            m = (hour == h) & (b_prev == b)
            row = probs[m].mean(axis=0) if m.any() else np.full(n_bins, 1.0 / n_bins)
            matrices[h, b] = row / row.sum()
    centers = _bin_centers(df["resid"].to_numpy(float), edges)
    return HourlyTransition(edges, matrices, centers)


# --------------------------------------------------------------------------- #
# Irreducibility: strong connectivity of the support digraph (Tarjan-free)    #
# --------------------------------------------------------------------------- #
def _strongly_connected(adj: np.ndarray) -> bool:
    """True iff the directed graph with adjacency `adj` (bool) is strongly connected,
    by reachability from node 0 in the graph and its transpose (Kosaraju's test)."""
    n = len(adj)
    if n == 0:
        return False

    def reach(a):
        seen = np.zeros(n, bool)
        stack = [0]
        seen[0] = True
        while stack:
            u = stack.pop()
            for v in np.nonzero(a[u])[0]:
                if not seen[v]:
                    seen[v] = True
                    stack.append(v)
        return seen.all()

    return reach(adj) and reach(adj.T)
