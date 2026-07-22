"""
Stage 3 — learned conditional price distribution: the two headline outputs.

  (A) MODEL QUALITY. Walk-forward CRPS / pinball / PIT for the learned quantile GBT
      vs the two baselines it must beat (empirical count matrix, mean-reverting jump).
      The learned model is ADOPTED only on a held-out CRPS win (§V.26). Prints the
      PIT histogram (the Stage 3 gate reads on calibration) and validates the
      hour-indexed transition matrices Stage 4 will consume.

  (B) DOLLAR VALUE. Swap the learned forecast into the SAME MPC and re-run the
      value-of-foresight ladder from Stage 2. The number that matters is how much of
      the $16,300 forecast-error cost the learned forecast recovers vs the
      same-hour-last-week naive forecast — measured leak-free, because the forecaster
      re-fits online by month (walk-forward), so every prediction is out-of-sample.

    python -m src.stage3_run            # demo window (scoring only, fast)
    python -m src.stage3_run --full     # full window: scoring + the MPC ladder (~min)
"""

from __future__ import annotations

import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore", message="invalid value encountered in reduce")

from src import features as F
from src import ingest, walkforward as WF
from src.backtest import run_backtest
from src.forecast import LearnedForecaster, PerfectForecaster, SameHourLastWeekForecaster
from src.oracle import ENERGY_ONLY, BatteryParams, solve
from src.policies import MPCPolicy, NaiveThresholdPolicy

FULL = ("2025-12-05", "2026-06-20")
DEMO = ("2025-12-05", "2026-04-05")   # 4 months: >=2 folds so learned engages, faster


def score_models(feat, min_train_months=2, n_bins=12):
    print("=== (A) walk-forward price-model scoring (held-out, expanding window) ===")
    res = WF.run_walkforward(feat, min_train_months=min_train_months, n_bins=n_bins,
                             verbose=True)
    print(f"\n  pooled over {res.n_folds} folds ({res.scores['learned_gbt'].n_eval} eval intervals):")
    print(f"  {'model':14s}{'CRPS':>9}{'pinball':>9}{'PIT-KS':>9}   (lower CRPS/pinball better)")
    ranked = sorted(res.scores.items(), key=lambda kv: kv[1].crps)
    for name, s in ranked:
        _, ks = WF.pit_histogram(s.pit)
        print(f"  {name:14s}{s.crps:9.3f}{s.pinball:9.3f}{ks:9.3f}")
    winner = ranked[0][0]
    learned = res.scores["learned_gbt"]
    beats = all(learned.crps < res.scores[b].crps for b in ("empirical", "jump"))
    print(f"\n  winner on held-out CRPS: {winner}. "
          f"Learned beats BOTH baselines: {beats} "
          f"({'ADOPT learned (§V.26)' if beats else 'keep baseline — a negative result is a result'}).")

    # PIT histogram of the learned model (the calibration gate)
    counts, ks = WF.pit_histogram(learned.pit, n_bins=10)
    print(f"\n  learned-model PIT histogram (flat => calibrated; KS={ks:.3f} vs Uniform):")
    peak = counts.max()
    for i, c in enumerate(counts):
        bar = "#" * int(round(40 * c / peak))
        print(f"    [{i/10:.1f},{(i+1)/10:.1f})  {bar} {c}")
    tilt = "under-dispersed (U-shape: too confident, tails too often)" if counts[0] + counts[-1] > 2.6 * np.mean(counts[1:-1]) \
        else "roughly flat / mild" if ks < 0.05 else "characterised deviation — see notes"
    print(f"    read: {tilt}")

    # transition-matrix validity (Stage 4 input)
    he = res.last_transitions["empirical"].check()
    hl = res.last_transitions["learned"].check()
    print(f"\n  hour-indexed transition matrices (last fold): "
          f"empirical rowsum_err={he['max_rowsum_err']:.1e} irreducible={he['irreducible']}; "
          f"learned rowsum_err={hl['max_rowsum_err']:.1e} irreducible={hl['irreducible']}")
    return res


def mpc_ladder(prices, ts, E=2.0, horizon=96):
    print(f"\n=== (B) value-of-foresight ladder with the LEARNED forecast @ {E:.0f}h "
          f"(energy-only, full window) ===")
    params = BatteryParams()
    ceiling = solve(prices, {}, E, params, ENERGY_ONLY).objective
    def bt(fc):
        return run_backtest(prices, MPCPolicy(fc, horizon=horizon), params, E,
                            s_init=0.0, timestamps=ts).profit
    clair = bt(PerfectForecaster(prices))
    naive = bt(SameHourLastWeekForecaster())
    learned = bt(LearnedForecaster(ts, prices, min_train_months=2))
    floor = run_backtest(prices, NaiveThresholdPolicy(), params, E, s_init=0.0,
                         timestamps=ts).profit

    fore_err_naive = clair - naive
    fore_err_learned = clair - learned
    recovered = naive_to_learned = learned - naive
    print(f"  ceiling (clairvoyant LP):        ${ceiling:>10,.0f}")
    print(f"  MPC, perfect forecast:           ${clair:>10,.0f}  ({clair/ceiling:.0%} of ceiling)")
    print(f"  MPC, LEARNED forecast:           ${learned:>10,.0f}")
    print(f"  MPC, same-hour-last-week (naive):${naive:>10,.0f}")
    print(f"  naive threshold floor:           ${floor:>10,.0f}")
    print(f"\n  forecast-error cost, naive  (ceiling-clair excluded): ${fore_err_naive:>10,.0f}")
    print(f"  forecast-error cost, learned:                         ${fore_err_learned:>10,.0f}")
    print(f"  >>> learned recovers ${recovered:,.0f} of the forecast-error gap "
          f"({recovered/fore_err_naive*100:.0f}% of it) — MPC profit ${naive:,.0f} -> ${learned:,.0f}")
    print("\n  Note: the learned forecaster falls back to seasonal-naive for the first 2 "
          "months (warm-up), so it and the naive MPC differ only on months 3-6; the full-"
          "window difference is therefore a conservative read of the learned model's value.")
    print("  The certainty-equivalent MPC consumes only the learned MEDIAN. The learned "
          "DISTRIBUTION's tail — its true prize — is realised by the Stage 4 DP, not here.")


def main():
    full = "--full" in sys.argv
    date_from, date_to = FULL if full else DEMO
    if not full:
        print("(demo window — scoring only; pass --full for the whole window + the MPC ladder)\n")
    panel = ingest.build_panel(date_from, date_to)
    prices = panel["price"].to_numpy(float)
    ts = panel["ts"].to_numpy()
    feat = F.build_features(panel)
    print(f"window {date_from}..{date_to}  T={len(prices)} intervals  "
          f"{panel['date'].nunique()} days\n")
    score_models(feat)
    if full:
        mpc_ladder(prices, ts)


if __name__ == "__main__":
    main()
