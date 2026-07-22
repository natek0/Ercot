"""
Stage 3 tests — the learned price model, its scoring rules, the transition matrices,
and (the load-bearing ones) the walk-forward discipline: no fold leakage and
publication-timestamp adaptedness.

Most tests are synthetic and run in CI. Two are gated on the real cached panel
(skipif on the parquet cache), like the rest of the suite.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

from src import features as F
from src import markov, walkforward as WF
from src.price_model import (
    LEVELS, EmpiricalCond, MeanRevertJump, QuantileGBT,
    crps_from_quantiles, pinball_loss, pit_values, rearrange,
)

CACHE = "data/raw/energy_HB_NORTH_2025-12-05_2026-06-20.parquet"
has_cache = pytest.mark.skipif(not os.path.exists(CACHE), reason="no cached ERCOT panel")


# --------------------------------------------------------------------------- #
# Synthetic panel: a diurnal + weekend price with occasional spikes           #
# --------------------------------------------------------------------------- #
def _synth_panel(n_days: int = 120, start: str = "2026-01-01", seed: int = 0) -> pd.DataFrame:
    """Diurnal + weekend price with an AR(1) residual whose volatility AND spike
    intensity are HOUR-DEPENDENT (evenings are wild). Hour-conditioning models
    (the GBT, which sees hour) can exploit this; the pooled parametric jump model
    (no hour) cannot — so on this DGP the learned model has real signal to win on."""
    n = n_days * 96
    ts = pd.date_range(start, periods=n, freq="15min")
    q = np.arange(n) % 96
    hour = q // 4
    evening = ((hour >= 17) & (hour <= 21)).astype(float)
    dow = (ts.dayofweek + 1) % 7
    weekend = np.isin(dow, [0, 6]).astype(float)
    rng = np.random.RandomState(seed)
    base = 30 + 20 * np.sin((q - 40) / 96 * 2 * np.pi) - 8 * weekend
    resid = np.zeros(n)
    for t in range(1, n):                              # AR(1) residual + hour-driven spikes
        sd = 2.0 + 5.0 * evening[t]                    # evenings much noisier
        resid[t] = 0.6 * resid[t - 1] + rng.randn() * sd
        if rng.rand() < (0.002 + 0.03 * evening[t]):   # spikes cluster in the evening
            resid[t] += rng.rand() * 200
    price = base + resid
    return pd.DataFrame({"ts": ts, "price": price})


@pytest.fixture(scope="module")
def synth_feat():
    return F.build_features(_synth_panel())


# --------------------------------------------------------------------------- #
# Scoring rules (§V.25) — proper-scoring-rule properties                       #
# --------------------------------------------------------------------------- #
def test_pinball_recovers_the_quantile():
    """The pinball minimiser is the quantile (§V.24 theorem). On an i.i.d. sample,
    the empirical quantile beats any offset quantile in mean pinball at that level."""
    rng = np.random.RandomState(1)
    y = rng.randn(20000)
    for a in (0.1, 0.5, 0.9):
        truth = np.quantile(y, a)
        q_true = np.full((len(y), 1), truth)
        q_off = np.full((len(y), 1), truth + 0.5)
        assert pinball_loss(y, q_true, np.array([a])) < pinball_loss(y, q_off, np.array([a]))


def test_crps_zero_for_a_point_mass_at_y():
    y = np.array([3.0, -1.0])
    q = np.repeat(y[:, None], len(LEVELS), axis=1)     # all quantiles == y
    assert np.allclose(crps_from_quantiles(y, q), 0.0)


def test_crps_nonneg_and_worse_when_biased():
    rng = np.random.RandomState(2)
    y = rng.randn(500)
    q_good = np.quantile(y, LEVELS)[None, :].repeat(len(y), axis=0)
    q_bad = q_good + 5.0
    assert (crps_from_quantiles(y, q_good) >= -1e-12).all()
    assert crps_from_quantiles(y, q_bad).mean() > crps_from_quantiles(y, q_good).mean()


def test_pit_uniform_when_calibrated():
    """If the predicted quantiles are the TRUE marginal quantiles, the PIT is
    Uniform(0,1): a flat histogram (§V.25)."""
    rng = np.random.RandomState(3)
    y = rng.randn(30000)
    q = np.quantile(y, LEVELS)[None, :].repeat(len(y), axis=0)
    u = pit_values(y, q)
    counts, ks = WF.pit_histogram(u, n_bins=10)
    assert ks < 0.03                                   # close to uniform
    assert counts.min() > 0.7 * counts.mean()          # roughly flat


def test_isotonic_rearrangement_is_monotone_and_no_worse():
    """Rearrangement makes quantiles non-crossing and does not increase pinball (§V.24)."""
    rng = np.random.RandomState(4)
    y = rng.randn(1000)
    q = rng.randn(1000, len(LEVELS)) * 2 + np.linspace(-2, 2, len(LEVELS))  # noisy, crosses
    qr = rearrange(q)
    assert (np.diff(qr, axis=1) >= -1e-9).all()        # non-decreasing in level
    assert pinball_loss(y, qr) <= pinball_loss(y, q) + 1e-9


# --------------------------------------------------------------------------- #
# Walk-forward discipline (§VIII.3 fold intersection, §VIII.1 adaptedness)     #
# --------------------------------------------------------------------------- #
def test_month_folds_are_expanding_and_disjoint(synth_feat):
    folds = WF.month_folds(synth_feat["ts"], min_train_months=2)
    assert len(folds) >= 2
    for train, evalu in folds:
        WF.assert_no_fold_leak(train, evalu, synth_feat["ts"])   # raises on any leak

def test_fold_leak_assertion_fires_on_overlap(synth_feat):
    ts = synth_feat["ts"]
    with pytest.raises(AssertionError):
        WF.assert_no_fold_leak(np.array([0, 1, 2, 5]), np.array([4, 5, 6]), ts)  # shares idx 5
    with pytest.raises(AssertionError):
        WF.assert_no_fold_leak(np.array([10, 11]), np.array([0, 1]), ts)         # eval before train


def test_conditioning_excludes_current_price_features():
    """(§VIII.1) The conditioning set must not contain any feature that reads the
    interval's own not-yet-cleared price."""
    WF.assert_pit_adapted(pd.DataFrame())              # invariant on CONDITIONING itself
    for col in ("price", "price_z_1d", "is_scarcity", "resid", "seasonal"):
        assert col not in F.CONDITIONING


def test_features_are_point_in_time(synth_feat):
    """Feature row n computed from the full panel equals the row computed from only
    prices[:n+1] — proof the frame carries no future information (the no-lookahead
    property the LearnedForecaster relies on to read a precomputed frame causally)."""
    panel = _synth_panel()
    full = F.build_features(panel)
    lag_roll = ["price_lag_15min", "price_lag_1d", "price_lag_1w",
                "price_roll_mean_1d", "price_roll_std_1d"]
    for n in (700, 3000, 8000):
        truncated = F.build_features(panel.iloc[: n + 1])
        a = full.iloc[n][lag_roll].to_numpy(float)
        b = truncated.iloc[n][lag_roll].to_numpy(float)
        assert np.allclose(np.nan_to_num(a), np.nan_to_num(b), atol=1e-9)


# --------------------------------------------------------------------------- #
# Models fit + predict on synthetic; learned beats the baselines out of sample #
# --------------------------------------------------------------------------- #
def test_models_fit_predict_shapes(synth_feat):
    folds = WF.month_folds(synth_feat["ts"], min_train_months=2)
    train, evalu = folds[-1]
    seasonal = F.fit_seasonal(synth_feat.iloc[train])
    fr = F.add_residual_features(synth_feat, seasonal)
    tr = fr.iloc[train].dropna(subset=F.CONDITIONING + ["resid"])
    ev = fr.iloc[evalu].dropna(subset=F.CONDITIONING + ["resid"])
    for model in (QuantileGBT(max_iter=40), EmpiricalCond(), MeanRevertJump()):
        if isinstance(model, QuantileGBT):
            model.fit(F.conditioning_matrix(tr), tr["resid"].to_numpy(float))
        else:
            model.fit(tr)
        q = model.predict_quantiles(ev)
        assert q.shape == (len(ev), len(LEVELS))
        assert np.isfinite(q).all()


def test_learned_wins_or_ties_on_synthetic(synth_feat):
    """A held-out CRPS comparison on synthetic data where the signal is learnable:
    the GBT should not be worse than the parametric/empirical baselines."""
    res = WF.run_walkforward(synth_feat, min_train_months=2, n_bins=10)
    crps = {k: v.crps for k, v in res.scores.items()}
    # hour-driven spikes => the pooled parametric jump model is misspecified; the
    # hour-aware GBT should beat it, and be no worse than the empirical matrix.
    assert crps["learned_gbt"] < crps["jump"]
    assert crps["learned_gbt"] <= 1.02 * crps["empirical"]


# --------------------------------------------------------------------------- #
# Transition matrices (§V.26 steps 2/4/5)                                      #
# --------------------------------------------------------------------------- #
def test_transition_matrices_valid(synth_feat):
    folds = WF.month_folds(synth_feat["ts"], min_train_months=2)
    train, _ = folds[-1]
    seasonal = F.fit_seasonal(synth_feat.iloc[train])
    fr = F.add_residual_features(synth_feat, seasonal).iloc[train].dropna(
        subset=["resid", "resid_lag_15min"])
    edges = markov.bin_edges(fr["resid"].to_numpy(float), n_bins=10)
    assert edges[0] == -np.inf and edges[-1] == np.inf
    ht = markov.transition_counts(fr, edges)
    chk = ht.check()
    assert chk["max_rowsum_err"] < 1e-9                # every row sums to one (step 5)
    assert chk["irreducible"]                          # chain irreducible (assumption A2)
    gbt = QuantileGBT(max_iter=40).fit(F.conditioning_matrix(fr), fr["resid"].to_numpy(float))
    ht_l = markov.transition_model(gbt, fr, edges)
    assert ht_l.check()["max_rowsum_err"] < 1e-9


# --------------------------------------------------------------------------- #
# LearnedForecaster: causal + right interface                                  #
# --------------------------------------------------------------------------- #
def test_learned_forecaster_is_causal():
    """Perturbing the future must not change a forecast made now (§VIII.1). Uses a
    small window so the refit is cheap."""
    from src.forecast import LearnedForecaster
    panel = _synth_panel(n_days=100)
    prices = panel["price"].to_numpy(float)
    ts = panel["ts"].to_numpy()
    n = 90 * 96
    lf1 = LearnedForecaster(ts, prices, min_train_months=2)
    p2 = prices.copy()
    p2[n:] = 9999.0                                    # scramble the future
    lf2 = LearnedForecaster(ts, p2, min_train_months=2)
    f1 = lf1.predict(prices[:n], 48)
    f2 = lf2.predict(p2[:n], 48)
    assert np.allclose(f1, f2)                         # forecast at n unaffected by t>=n


def test_learned_forecaster_interface_and_fallback():
    from src.forecast import LearnedForecaster
    panel = _synth_panel(n_days=100)
    prices = panel["price"].to_numpy(float)
    ts = panel["ts"].to_numpy()
    lf = LearnedForecaster(ts, prices, min_train_months=2)
    early = lf.predict(prices[:500], 96)               # before 2 months -> fallback
    assert early.shape == (96,) and np.isfinite(early).all()
    late = lf.predict(prices[: 80 * 96], 96)           # learned engaged
    assert late.shape == (96,) and np.isfinite(late).all()


# --------------------------------------------------------------------------- #
# Real-data gated: build_features == warehouse v_features                       #
# --------------------------------------------------------------------------- #
@has_cache
def test_features_match_warehouse():
    """build_features reproduces the warehouse v_features columns row-for-row on the
    real panel — so 'quantile regression on the warehouse features' is literal, and
    the gap-safe timestamp lags match the SQL LEFT JOINs (NaN placement included)."""
    from src import ingest, warehouse
    panel = ingest.build_panel("2025-12-05", "2026-02-05")
    feat = F.build_features(panel)
    wpanel = panel[["ts", "date", "hour", "interval", "price"] + ingest.AS_TYPES].copy()
    wpanel["settlement_point"] = "HB_NORTH"
    con = warehouse.build(":memory:", panel=wpanel)
    vf = con.execute(
        "SELECT ts, price_lag_15min, price_lag_1d, price_lag_1w, price_roll_mean_1d, "
        "price_roll_std_1d, is_scarcity, quarter_of_day, dow, is_weekend, month "
        "FROM v_features ORDER BY ts").df()
    con.close()
    m = feat.merge(vf, on="ts", suffixes=("_f", "_w"))
    assert len(m) == len(feat)
    for col in ("price_lag_15min", "price_lag_1d", "price_lag_1w",
                "price_roll_mean_1d", "price_roll_std_1d"):
        a, b = m[col + "_f"].to_numpy(float), m[col + "_w"].to_numpy(float)
        both_nan = np.isnan(a) & np.isnan(b)
        assert np.allclose(np.nan_to_num(a), np.nan_to_num(b), atol=1e-6)
        assert (np.isnan(a) == np.isnan(b)).all()      # NaN in the same gap rows
    for col in ("is_scarcity", "quarter_of_day", "dow", "is_weekend", "month"):
        assert (m[col + "_f"].to_numpy() == m[col + "_w"].to_numpy()).all()


@has_cache
def test_learned_beats_baselines_on_real_crps():
    """The Stage 3 gate's model-selection check on real data: the learned model wins
    held-out CRPS against BOTH baselines, so it is the one adopted (§V.26)."""
    from src import ingest
    panel = ingest.build_panel("2025-12-05", "2026-06-20")
    feat = F.build_features(panel)
    res = WF.run_walkforward(feat, min_train_months=2, n_bins=12)
    crps = {k: v.crps for k, v in res.scores.items()}
    assert crps["learned_gbt"] < crps["empirical"]
    assert crps["learned_gbt"] < crps["jump"]
