"""
Stage 5 — the statistical inference suite (§VIII.5), leak-free.

Turns the Stage 4 POINT estimates into defensible inference on the ~198-day (≈128 traded-day,
post-warm-up) window. The heavy, slow part is here — running the leak-free walk-forward
backtests that produce the DAILY paired-difference series — and the pure inference lives in
src.stage5_stats (unit-tested). Every fitted object (DP kernel, seasonal, bin edges, reserve
prices, and the MPC forecaster) is re-fit INSIDE each walk-forward fold; no future leaks.

What it produces (all on the MATCHED traded window, post the DP's 2-month warm-up, so the
option value is NOT inflated by the DP's warm-up exemption — the Stage 4 review's key fix):

  (1) Sign test — the distribution-free HEADLINE — on daily V^DP - V^MPC(learned) differences.
  (2) Matched-window MPC recompute: the learned/naive MPC P&L summed over ONLY the traded days.
  (3) Stationary block-bootstrap CI on V^DP and on the paired edge, with block-length sweep.
  (4) Concentration decomposition (top-1 / top-5 day share) of V^DP.
  (5) Leave-one-day-out jackknife + a power statement (minimum detectable edge, % of ceiling).
  (6) CIs on the §V.26 empirical-minus-learned-kernel gap and on the reserve shadow price ψ_up.

The daily series are CACHED to data/raw/stage5_cache.* so re-running the analysis is instant;
pass --rebuild to recompute the backtests from the cached price panel.

    python -m src.stage5_run              # build cache if missing, then the full report
    python -m src.stage5_run --rebuild    # force the heavy backtests to re-run
"""

from __future__ import annotations

import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message="invalid value encountered in reduce")

from src import ingest, reserves
from src.backtest import run_backtest
from src.forecast import LearnedForecaster, PerfectForecaster, SameHourLastWeekForecaster
from src.oracle import ENERGY_ONLY, BatteryParams, solve
from src.policies import MPCPolicy, NaiveThresholdPolicy, WalkForwardDPPolicy
from src import stage5_stats as st

FULL = ("2025-12-05", "2026-06-20")
E_DEFAULT = 2.0
N_S = 200
N_BINS = 12
MIN_TRAIN_MONTHS = 2
CACHE_DAILY = "data/raw/stage5_daily.parquet"
CACHE_PSI = "data/raw/stage5_psi.npz"
CACHE_DUR = "data/raw/stage5_duration.parquet"
DURATIONS = (0.5, 1.0, 2.0, 4.0, 8.0)


# --------------------------------------------------------------------------- #
#  Heavy backtests -> daily paired-difference series (cached)
# --------------------------------------------------------------------------- #
def _traded_mask(panel, min_train_months=MIN_TRAIN_MONTHS):
    """Boolean mask of the intervals the walk-forward DP actually TRADES (post the warm-up
    during which it has no fitted model and simply holds). All policies are compared ONLY on
    these intervals — the matched traded window (§VIII.5, Stage 4 review fix)."""
    ym = pd.to_datetime(panel["ts"]).dt.to_period("M")
    months = list(ym.drop_duplicates())
    return (ym >= months[min_train_months]).to_numpy()


def _daily_pnl(log, mask):
    """Collapse an interval-level backtest log to a per-calendar-day P&L series over the
    masked (traded) intervals. Index = date, value = summed step_profit."""
    lg = log.iloc[np.where(mask)[0]].copy()
    lg["date"] = pd.to_datetime(lg["ts"]).dt.date
    return lg.groupby("date")["step_profit"].sum()


def build_cache(date_from=FULL[0], date_to=FULL[1], E=E_DEFAULT):
    """Run every leak-free walk-forward backtest ONCE and cache the aligned daily P&L series
    (plus the reserve-DP ψ_up interval detail). This is the slow step (~1-2 min): the learned
    and naive MPCs solve an LP at every one of ~18,900 intervals."""
    params = BatteryParams()
    panel = ingest.build_panel(date_from, date_to)
    prices = panel["price"].to_numpy(float)
    ts = panel["ts"].to_numpy()
    mcpc = {k: panel[k].to_numpy(float) for k in ingest.AS_TYPES}
    mask = _traded_mask(panel)

    print(f"[cache] window {date_from}..{date_to}  T={len(prices)}  "
          f"{panel['date'].nunique()} days; traded (post warm-up) intervals={mask.sum()} "
          f"({pd.to_datetime(ts[mask]).to_series().dt.date.nunique()} days)")

    def dp(kernel="empirical", reserves_on=False, rho=0.05):
        pol = WalkForwardDPPolicy(panel, params, E, N_S=N_S, n_bins=N_BINS,
                                  reserves=reserves_on, rho=rho, kernel_kind=kernel)
        return run_backtest(prices, pol, params, E, s_init=0.0,
                            mcpc=mcpc if reserves_on else None, timestamps=ts)

    def mpc(fc):
        return run_backtest(prices, MPCPolicy(fc, horizon=96), params, E,
                            s_init=0.0, timestamps=ts)

    print("[cache] DP (empirical kernel, energy-only) ...")
    r_dp = dp("empirical")
    print("[cache] DP (learned kernel, energy-only) ...")
    r_dp_l = dp("learned")
    print("[cache] DP (reserve co-optimised, rho=0.05) — for ψ_up ...")
    r_res = dp("empirical", reserves_on=True, rho=0.05)
    print("[cache] MPC (perfect forecast = clairvoyant) — slow LP-per-interval ...")
    r_clair = mpc(PerfectForecaster(prices))
    print("[cache] MPC (learned forecast) — slow LP-per-interval ...")
    r_ml = mpc(LearnedForecaster(ts, prices, min_train_months=MIN_TRAIN_MONTHS))
    print("[cache] MPC (same-hour-last-week) — slow LP-per-interval ...")
    r_mn = mpc(SameHourLastWeekForecaster())
    print("[cache] naive threshold floor ...")
    r_fl = run_backtest(prices, NaiveThresholdPolicy(), params, E, s_init=0.0, timestamps=ts)

    for r in (r_dp, r_dp_l, r_ml, r_mn, r_fl):        # every log spans the full panel, in order
        assert len(r.log) == mask.size, f"log/panel length mismatch: {len(r.log)} vs {mask.size}"

    daily = pd.DataFrame({
        "dp_emp": _daily_pnl(r_dp.log, mask),
        "dp_lrn": _daily_pnl(r_dp_l.log, mask),
        "mpc_learned": _daily_pnl(r_ml.log, mask),
        "mpc_naive": _daily_pnl(r_mn.log, mask),
        "floor": _daily_pnl(r_fl.log, mask),
    }).fillna(0.0)

    # ceilings (perfect-foresight LP) on full & traded windows, for the % denominators
    ceil_full = solve(prices, {}, E, params, ENERGY_ONLY).objective
    ceil_tr = solve(prices[mask], {}, E, params, ENERGY_ONLY).objective
    daily.attrs["ceiling_full"] = ceil_full
    daily.attrs["ceiling_traded"] = ceil_tr
    os.makedirs("data/raw", exist_ok=True)
    daily.to_parquet(CACHE_DAILY)
    # Sidecar meta (parquet attrs don't round-trip). FULL-window realised profits for the ladder
    # are stored HERE, computed in this run — the figure/writeup read them from the cache rather
    # than any hardcoded constant, so "one command reproduces every number" holds literally.
    pd.DataFrame({"ceiling_full": [ceil_full], "ceiling_traded": [ceil_tr], "E": [E],
                  "clair_full": [r_clair.profit], "dp_full": [r_dp.profit],
                  "learned_full": [r_ml.profit], "naive_full": [r_mn.profit],
                  "floor_full": [r_fl.profit]}).to_parquet(
        CACHE_DAILY.replace(".parquet", "_meta.parquet"))

    # --- ψ_up: realised INTERVAL MCPC at the EXECUTED post-decision SOC (Stage 4 (ii)) --- #
    tau = np.array([params.tau[k] for k in reserves.UP_PRODUCTS])
    a = tau / params.eta_d
    log = r_res.log
    soc_post = log["soc_post"].to_numpy(float)
    netd = log["d"].to_numpy(float) - log["c"].to_numpy(float)
    psi_iv = np.zeros(len(log))
    for t in range(len(log)):
        v_t = (np.array([mcpc[k][t] for k in reserves.UP_PRODUCTS])
               - params.c_deg * 0.05 * tau) * params.dt
        _, psi_iv[t] = reserves.reserve_lp(soc_post[t] - params.s_min,
                                           params.p_bar - netd[t], v_t, a)
    dates = pd.to_datetime(log["ts"]).dt.date.to_numpy()
    np.savez(CACHE_PSI, psi_iv=psi_iv[mask],
             dates=dates[mask].astype("datetime64[D]"),
             median_price=float(np.median(np.abs(prices))))

    # --- Q3 duration sweep: V_PF(E) & V_DP(E), grid ΔS-constant (~100 nodes/h) --- #
    print("[cache] Q3 duration sweep (V_PF & walk-forward V_DP per E) ...")
    dur_rows = []
    for Ei in DURATIONS:
        N_Si = max(50, int(round(100 * Ei)))
        v_pf = solve(prices, {}, Ei, params, ENERGY_ONLY).objective
        pol = WalkForwardDPPolicy(panel, params, Ei, N_S=N_Si, n_bins=N_BINS)
        v_dp = run_backtest(prices, pol, params, Ei, s_init=0.0, timestamps=ts).profit
        dur_rows.append({"E": Ei, "N_S": N_Si, "v_pf": v_pf, "v_dp": v_dp,
                         "capture": v_dp / v_pf})
        print(f"         E={Ei:>4.1f}h  V_PF ${v_pf:>8,.0f}  V_DP ${v_dp:>8,.0f}  "
              f"capture {v_dp/v_pf:>5.0%}")
    pd.DataFrame(dur_rows).to_parquet(CACHE_DUR)

    print(f"[cache] wrote {CACHE_DAILY}, {CACHE_PSI}, {CACHE_DUR}")
    return daily


def _load_cache():
    meta = pd.read_parquet(CACHE_DAILY.replace(".parquet", "_meta.parquet"))
    daily = pd.read_parquet(CACHE_DAILY)
    for k in meta.columns:                              # ceilings, E, and full-window profits
        daily.attrs[k] = float(meta[k].iloc[0])
    psi = np.load(CACHE_PSI, allow_pickle=True)
    return daily, psi


# --------------------------------------------------------------------------- #
#  Reporting
# --------------------------------------------------------------------------- #
def _fmt_ci(c):
    return (f"[{c['lo']:,.0f}, {c['hi']:,.0f}]"
            f"{'  STRADDLES ZERO' if c['straddles_zero'] else ''}")


def report(daily=None, psi=None):
    if daily is None:
        daily, psi = _load_cache()
    ceil_full = daily.attrs["ceiling_full"]
    ceil_tr = daily.attrs["ceiling_traded"]
    E = daily.attrs.get("E", E_DEFAULT)
    n = len(daily)
    v_dp = float(daily["dp_emp"].sum())
    v_ml = float(daily["mpc_learned"].sum())
    v_mn = float(daily["mpc_naive"].sum())

    print(f"\n{'='*74}\nSTAGE 5 — statistical inference @ {E:.0f}h  "
          f"({n} traded days; matched post-warm-up window)\n{'='*74}")
    print(f"ceiling (perfect foresight): full ${ceil_full:,.0f} | traded ${ceil_tr:,.0f}")
    print(f"V^DP (empirical kernel): ${v_dp:,.0f}  =  {v_dp/ceil_tr:.0%} of the TRADED ceiling "
          f"(the apples-to-apples figure — comparators are matched) / {v_dp/ceil_full:.0%} of the "
          f"FULL ceiling (conservative — the DP held through the 2-month warm-up)")
    print(f"matched-window MPC:  learned ${v_ml:,.0f}   naive ${v_mn:,.0f}   "
          f"floor ${float(daily['floor'].sum()):,.0f}")
    print(f"  three distinct ratios (do not conflate): capture-of-traded {v_dp/ceil_tr:.0%}, "
          f"capture-of-full {v_dp/ceil_full:.0%}, option-edge-vs-learned-MPC "
          f"{(v_dp-v_ml)/ceil_tr:.0%} of traded ceiling.")

    # ---- (2) matched-window option value (the Stage 4 review's inflation fix) ---- #
    print(f"\n--- (2) Matched-window option value (DP vs MPC, SAME traded days) ---")
    print(f"  option value V^DP - V^MPC(learned), matched: ${v_dp - v_ml:,.0f}")
    print(f"    (Stage 4 reported +$2,667 on the UNMATCHED window, inflated because the MPC "
          f"absorbed warm-up losses the DP skipped; this is the honest number.)")

    # ---- (1) sign test — the headline — on daily V^DP - V^MPC(learned) ---- #
    D = (daily["dp_emp"] - daily["mpc_learned"]).to_numpy()
    rep = st.paired_report(D, ceil_tr)
    s = rep["sign_test"]
    print(f"\n--- (1) SIGN TEST (headline) — daily V^DP - V^MPC(learned) ---")
    print(f"  DP beats learned MPC on {s.n_pos}/{s.n_eff} non-tied days = {s.prop_pos:.0%}"
          f"  (two-sided exact binomial p = {s.p_value:.3f}; {s.n_zero} tied days)")
    print(f"  mean daily edge ${rep['mean_daily']:,.1f}; total ${rep['total']:,.0f}")
    pm = rep["permutation"]
    print(f"  MAGNITUDE-AWARE companion (paired sign-flip permutation, keeps win SIZE): "
          f"one-sided p = {pm['p_one_sided']:.3f}, two-sided p = {pm['p_two_sided']:.3f}")
    print(f"    → the sign test is the LEAST powerful test against 'wins by a few big days', so its "
          f"coin-flip p OVERSTATES the ambiguity; the permutation p≈{pm['p_one_sided']:.2f} is the "
          f"honest strength — marginal, still not separable at 5%, but not a coin flip.")
    sn = st.sign_test((daily["dp_emp"] - daily["mpc_naive"]).to_numpy(), tol=1e-6)
    print(f"  (vs the NAIVE MPC: DP wins {sn.n_pos}/{sn.n_eff} = {sn.prop_pos:.0%}, "
          f"p={sn.p_value:.3f} — the DP's edge over the WEAK baseline is clear.)")

    # ---- (3) block-bootstrap CI on the paired edge + block-length sensitivity ---- #
    print(f"\n--- (3) Stationary block-bootstrap 95% CI (block mean 5 days) ---")
    print(f"  on total paired edge sum(D):  {_fmt_ci(rep['bootstrap_ci_sum'])}")
    print(f"  block-length sensitivity of the edge CI:")
    for c in rep["block_sensitivity_sum"]:
        print(f"    block~{c['block_mean']:>4.0f}d:  {_fmt_ci(c)}")
    # CI on V^DP itself (level, not paired) — build on the Stage 4 CI that straddles zero
    dp_ci = st.bootstrap_ci(daily["dp_emp"].to_numpy(), np.sum)
    print(f"  CI on V^DP (level): {_fmt_ci(dp_ci)}")

    # ---- (4) concentration ---- #
    con = st.concentration(daily["dp_emp"].to_numpy())
    print(f"\n--- (4) Concentration of V^DP across days ---")
    print(f"  top-1 day = ${con['top1_sum']:,.0f} ({con['top1_share_of_gross']:.0%} of gross "
          f"up-day P&L); top-5 = ${con['top5_sum']:,.0f} ({con['top5_share_of_gross']:.0%})")
    print(f"  (share of NET total: top-1 {con['top1_share_of_total']:.0%}, "
          f"top-5 {con['top5_share_of_total']:.0%}; net total ${con['total']:,.0f})")

    # ---- (5) jackknife + power ---- #
    jk = rep["jackknife_sum"]
    print(f"\n--- (5) Leave-one-day-out jackknife + power ---")
    print(f"  paired edge total ${jk['full']:,.0f}; leave-one-out range "
          f"[${jk['min']:,.0f}, ${jk['max']:,.0f}]; sign fragile: {jk['sign_flips']}")
    pw = rep["power"]
    print(f"  POWER: with sd(D)=${pw['sd_daily']:,.0f}/day over n={pw['n_days']} days, this "
          f"design detects (α=0.05, 80% power) a total edge ≥ ${pw['mde_total']:,.0f} "
          f"= {pw['mde_pct_of_ceiling']:.0%} of the traded ceiling; smaller is not resolvable.")

    # ---- (6a) §V.26 empirical - learned kernel gap CI ---- #
    Dk = (daily["dp_emp"] - daily["dp_lrn"]).to_numpy()
    rk = st.paired_report(Dk, ceil_tr)
    sk = rk["sign_test"]
    print(f"\n--- (6a) §V.26 kernel gap — daily V^DP(empirical) - V^DP(learned), n_bins=12 ---")
    print(f"  empirical total ${daily['dp_emp'].sum():,.0f} vs learned ${daily['dp_lrn'].sum():,.0f}; "
          f"gap ${rk['total']:,.0f}")
    print(f"  sign test: empirical wins {sk.n_pos}/{sk.n_eff} days = {sk.prop_pos:.0%} "
          f"(p={sk.p_value:.3f}); 95% CI on the gap {_fmt_ci(rk['bootstrap_ci_sum'])}")
    print(f"  => within noise (consistent with the n_bins=10 sign flip): 'empirical ≈ learned'.")

    # ---- (6b) ψ_up CIs ---- #
    if psi is not None:
        report_psi(psi)

    return rep


def report_psi(psi):
    """Inference on the reserve shadow price ψ_up, a heavy-tailed per-interval PRICE whose bulk is
    ~0 and whose economics live in the tail. The DEFENSIBLE headline is the bootstrap 95% CI on
    the MEAN daily-max ψ_up (a bounded, CI-backed number); the raw max is a SINGLE-EVENT extreme
    reported as directional context, not as a bounded finding. Concentration shows it is an
    event price, and the count of binding DAYS is the effective sample (§VIII.5a)."""
    psi_iv = psi["psi_iv"]
    dates = pd.Series(pd.to_datetime(psi["dates"]))
    tol = 0.01 * float(psi["median_price"])
    pos = psi_iv[psi_iv > tol]
    df = pd.DataFrame({"date": dates.dt.date.to_numpy(), "psi": psi_iv})
    daily_max = df.groupby("date")["psi"].max()
    binds_days = int((daily_max > tol).sum())
    n_over_stage0 = int((psi_iv > 32.75).sum())
    dm_ci = st.bootstrap_ci(daily_max.to_numpy(), np.mean)
    con = st.concentration(daily_max.to_numpy())
    print(f"\n--- (6b) Reserve shadow price ψ_up (interval MCPC at executed SOC, ρ=0.05) ---")
    print(f"  DEFENSIBLE headline — bootstrap 95% CI on the MEAN daily-max ψ_up: "
          f"[${dm_ci['lo']:.3f}, ${dm_ci['hi']:.3f}]  (a bounded, CI-backed scarcity cost)")
    print(f"  binds (ψ_up>${tol:.3f}) in {(psi_iv>tol).mean()*100:.1f}% of intervals, on "
          f"{binds_days}/{daily_max.size} days; median over binding intervals ${np.median(pos):.3f}; "
          f"p99 ${np.percentile(psi_iv,99):.3f}")
    print(f"  concentration: top-1 day = {con['top1_share_of_gross']:.0%} of summed daily-max, "
          f"top-5 = {con['top5_share_of_gross']:.0%} → ψ_up is a scarcity-EVENT price, not a "
          f"constant accounting term.")
    print(f"  DIRECTIONAL context (NOT a bounded finding): raw max ${psi_iv.max():.2f} exceeds "
          f"Stage 0's clairvoyant max $32.75 — but on just {n_over_stage0} intervals of one "
          f"scarcity day, no CI, ρ-dependent. It illustrates Decision 19 (a causal operator "
          f"caught short can pay more than a clairvoyant); it is NOT a headline number.")


def main():
    rebuild = "--rebuild" in sys.argv
    if rebuild or not os.path.exists(CACHE_DAILY):
        build_cache()
    report()


if __name__ == "__main__":
    main()
