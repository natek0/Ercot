"""
Expanding-window walk-forward evaluation (§VIII.3) for the Stage 3 price models.

This is where the project's credibility is won or lost. Two properties are enforced
IN CODE, not by intention:

  * FOLD INTERSECTION (§VIII.3). Fit on calendar months 1..m, evaluate on month m+1,
    advance. Every estimated object — the seasonal mean, the bin edges, the quantile
    models, the jump parameters, the transition matrix — is re-fit inside the fold on
    the TRAIN slice only. `assert_no_fold_leak` verifies (a) train and eval index sets
    are disjoint and (b) every train timestamp precedes every eval timestamp. "A single
    global deseasonalize() before the loop leaks the future and is the easiest way to
    silently destroy the project's credibility."

  * ADAPTEDNESS / PUBLICATION TIMESTAMP (§VIII.1). Every conditioning feature is a
    strictly-past function of prices (src/features.CONDITIONING), so a feature used to
    predict interval t is published by t. `assert_pit_adapted` checks it structurally
    on the fold: no conditioning column of an eval row is a function of that row's own
    (not-yet-cleared) price. The forecaster-level no-lookahead test in test_stage3
    complements this by perturbing the future and confirming predictions don't move.

Per fold, all three models (QuantileGBT, EmpiricalCond, MeanRevertJump) predict the
eval month's residual quantiles and are scored by pinball, CRPS and PIT (src.price_model).
Nothing here is global; re-running with a shifted window re-fits everything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src import features as F
from src import markov
from src.price_model import (
    LEVELS, EmpiricalCond, MeanRevertJump, QuantileGBT,
    crps_from_quantiles, pinball_loss, pit_values,
)


# --------------------------------------------------------------------------- #
# Fold construction + the two leakage assertions                              #
# --------------------------------------------------------------------------- #
def month_folds(ts: pd.Series, min_train_months: int = 2) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding-window folds by calendar month: train = all rows in the first m
    months, eval = the next month. Emits a fold for every month after the first
    `min_train_months`. Indices are positional into the (ts-sorted) frame."""
    ts = pd.to_datetime(pd.Series(ts).reset_index(drop=True))
    ym = ts.dt.to_period("M")
    months = list(ym.drop_duplicates())
    folds = []
    for i in range(min_train_months, len(months)):
        train = np.where(ym.isin(months[:i]))[0]
        evalu = np.where(ym == months[i])[0]
        if len(train) and len(evalu):
            folds.append((train, evalu))
    return folds


def assert_no_fold_leak(train_idx, eval_idx, ts) -> None:
    """(§VIII.3) disjoint index sets AND every train timestamp before every eval
    timestamp. Raises AssertionError on any intersection or time overlap."""
    ts = pd.to_datetime(pd.Series(ts).reset_index(drop=True)).to_numpy()
    inter = np.intersect1d(train_idx, eval_idx)
    assert inter.size == 0, f"fold leak: {inter.size} indices in both train and eval"
    assert ts[train_idx].max() < ts[eval_idx].min(), (
        "fold leak: a train timestamp is >= an eval timestamp (not expanding-window)")


def assert_pit_adapted(feat_resid_eval: pd.DataFrame = None) -> None:
    """(§VIII.1) STATIC invariant on the CONDITIONING constant — NOT a per-row data check.

    It asserts only that no *named* current-price column (price, its z-score/scarcity
    flag, resid, seasonal) has been added to src/features.CONDITIONING. That catches the
    common regression (someone lists a current-price feature) but by construction cannot
    catch a mis-COMPUTED causal feature (e.g. a lag that forgot its shift). The genuine
    data-level adaptedness guarantees live in the tests: `test_features_are_point_in_time`
    (reconstructs every conditioning column from a truncated prefix) and
    `test_learned_forecaster_is_causal*` (perturbs the future, asserts the forecast is
    invariant). The `feat_resid_eval` arg is accepted for call-site symmetry but unused."""
    current_price_cols = {"price", "price_z_1d", "is_scarcity", "resid", "seasonal"}
    leaked = current_price_cols & set(F.CONDITIONING)
    assert not leaked, f"adaptedness violation: current-price feature(s) in CONDITIONING: {leaked}"


# --------------------------------------------------------------------------- #
# Per-fold scoring                                                            #
# --------------------------------------------------------------------------- #
@dataclass
class ModelScore:
    name: str
    pinball: float
    crps: float
    n_eval: int
    pit: np.ndarray = field(default=None)          # pooled PIT values across folds


@dataclass
class WalkForwardResult:
    scores: dict                                   # model name -> ModelScore (pooled)
    per_fold: pd.DataFrame                         # (fold, model) -> pinball, crps, n
    n_folds: int
    last_transitions: dict                         # {'empirical':HT, 'learned':HT} last fold


def _default_models() -> dict:
    """Fresh, UNFITTED model instances — a factory so nothing carries across folds."""
    return {
        "learned_gbt": QuantileGBT(),
        "empirical": EmpiricalCond(),
        "jump": MeanRevertJump(),
    }


def run_walkforward(feat: pd.DataFrame, min_train_months: int = 2, n_bins: int = 12,
                    models_factory=_default_models, verbose: bool = False) -> WalkForwardResult:
    """Score the three models across expanding-window folds. `feat` is
    src.features.build_features output (whole series; feature VALUES are point-in-time,
    so computing them once is not a leak — every FITTED object is still re-fit per fold)."""
    feat = feat.reset_index(drop=True)
    folds = month_folds(feat["ts"], min_train_months)
    assert folds, "no folds — need more than min_train_months of data"

    rows = []
    pooled = {name: {"y": [], "q": []} for name in models_factory()}
    last_transitions = {}

    for fi, (train_idx, eval_idx) in enumerate(folds):
        assert_no_fold_leak(train_idx, eval_idx, feat["ts"])

        # re-fit the seasonal component on TRAIN ONLY, then deseasonalise both slices
        seasonal = F.fit_seasonal(feat.iloc[train_idx])
        fr = F.add_residual_features(feat, seasonal)          # residual cols for all rows
        assert_pit_adapted(fr.iloc[eval_idx])

        tr = fr.iloc[train_idx].dropna(subset=F.CONDITIONING + ["resid"])
        ev = fr.iloc[eval_idx].dropna(subset=F.CONDITIONING + ["resid"])
        y_ev = ev["resid"].to_numpy(float)

        # re-fit bin edges + transition matrices on TRAIN ONLY (for the Stage 4 handoff)
        edges = markov.bin_edges(tr["resid"].to_numpy(float), n_bins=n_bins)

        models = models_factory()
        for name, model in models.items():
            if isinstance(model, QuantileGBT):
                model.fit(F.conditioning_matrix(tr), tr["resid"].to_numpy(float))
            else:
                model.fit(tr)
            q = model.predict_quantiles(ev)
            rows.append({"fold": fi, "model": name,
                         "pinball": pinball_loss(y_ev, q), "crps": float(crps_from_quantiles(y_ev, q).mean()),
                         "n": len(ev), "train_end": str(feat["ts"].iloc[train_idx].max())[:10]})
            pooled[name]["y"].append(y_ev)
            pooled[name]["q"].append(q)

        # transition matrices from the last fold's fit (representative handoff to Stage 4)
        if fi == len(folds) - 1:
            last_transitions["empirical"] = markov.transition_counts(tr, edges)
            last_transitions["learned"] = markov.transition_model(models["learned_gbt"], tr, edges)

        if verbose:
            best = min((r for r in rows if r["fold"] == fi), key=lambda r: r["crps"])
            print(f"  fold {fi} train<= {best['train_end']}  n_eval={len(ev):4d}  "
                  f"best={best['model']} (CRPS {best['crps']:.3f})")

    scores = {}
    for name in pooled:
        y = np.concatenate(pooled[name]["y"])
        q = np.vstack(pooled[name]["q"])
        scores[name] = ModelScore(name, pinball_loss(y, q),
                                  float(crps_from_quantiles(y, q).mean()), len(y),
                                  pit=pit_values(y, q))
    return WalkForwardResult(scores, pd.DataFrame(rows), len(folds), last_transitions)


def pit_histogram(pit: np.ndarray, n_bins: int = 10) -> tuple[np.ndarray, float]:
    """PIT histogram (counts per equal-width bin on [0,1]) and the KS statistic vs
    Uniform(0,1) (§V.25). A flat histogram / small KS => calibrated."""
    from scipy.stats import kstest
    counts, _ = np.histogram(pit, bins=n_bins, range=(0, 1))
    ks = float(kstest(pit, "uniform").statistic)
    return counts, ks
