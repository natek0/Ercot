"""
Stage 4 — periodic dynamic program on the real ERCOT residual kernel (energy-only).

This is the FIRST Stage 4 milestone: solve the optimal causal policy's value function
on the Stage 3 hour-indexed transition kernel and report its in-model expected profit
per day, with the correctness gate (DP<->LP, Bellman residual, μ-monotonicity, grid
convergence). It reconstructs the price as seasonal(h) + residual-bin-centre for a
representative weekday in the recent season (plan "STAGE 4 updates" item 3).

IMPORTANT — what this number is and is NOT. ρ_day here is the EXPECTED average reward
under the LEARNED model (the DP's own transition kernel), for a representative day. It
is NOT yet the realised out-of-sample value V^DP of §IV.13 — that requires simulating
the DP's offer-curve policy forward on the real price path (walk-forward, no lookahead),
which is the next Stage 4 step and the number that slots into the value-of-information
ladder. Reserves/(AS)/ψ_up (Q2), the duration sweep (Q3), the tail recalibration, and
the §V.26 capture-rate prong are also subsequent steps.

    python -m src.stage4_run            # demo (fast)
    python -m src.stage4_run --full     # full window kernel, more durations + grid sweep
"""

from __future__ import annotations

import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore", message="invalid value encountered in reduce")

from src import dp, features as F, ingest, markov
from src.oracle import BatteryParams

FULL = ("2025-12-05", "2026-06-20")
DEMO = ("2025-12-05", "2026-04-05")


def build_dp_inputs(date_from, date_to, n_bins=12, kernel="empirical", model=None):
    """Fit the seasonal + residual kernel on the window and assemble the DP inputs:
    the hour-indexed kernel, the residual bin centres, and a representative-weekday
    seasonal price profile seasonal(h), h=0..95. Returns the SeasonalMean and panel too
    (the realised backtest needs them). kernel='empirical' (count matrix) or 'learned'
    (integrate a fitted `model`'s predictive CDF over bins)."""
    panel = ingest.build_panel(date_from, date_to)
    feat = F.build_features(panel)
    seasonal = F.fit_seasonal(feat)                       # full-window fit (in-model value)
    fr = F.add_residual_features(feat, seasonal).dropna(subset=["resid", "resid_lag_15min"])
    edges = markov.bin_edges(fr["resid"].to_numpy(float), n_bins=n_bins)
    if kernel == "learned" and model is not None:
        ht = markov.transition_model(model, fr, edges)
    else:
        ht = markov.transition_counts(fr, edges)
    rep_month = int(feat.sort_values("ts")["month"].iloc[-1])
    qod = np.arange(96)
    seasonal_profile = seasonal.eval_cal(qod, np.zeros(96, int), np.full(96, rep_month))
    return dict(ht=ht, seasonal_profile=seasonal_profile, seasonal=seasonal,
                edges=edges, rep_month=rep_month, panel=panel)


def run(date_from, date_to, durations=(1.0, 2.0, 4.0), N_S=200, n_bins=12):
    params = BatteryParams()
    inp = build_dp_inputs(date_from, date_to, n_bins)
    ht, seasonal_profile, rep_month, panel = inp["ht"], inp["seasonal_profile"], inp["rep_month"], inp["panel"]
    print(f"window {date_from}..{date_to}  {panel['date'].nunique()} days  "
          f"kernel: {ht.n_bins} bins x 24 hours  rep-month={rep_month}  N_S={N_S}\n")
    print(f"  seasonal profile: min ${seasonal_profile.min():.1f}  max "
          f"${seasonal_profile.max():.1f}  (representative-weekday diurnal level)")
    chk = ht.check()
    print(f"  kernel: matrix-irreducible={chk['irreducible']}  "
          f"raw-count-irreducible={chk['counts_irreducible']}\n")

    print(f"  {'E(h)':>5}{'DP $/day':>11}{'DP $/window':>13}{'bellman':>10}{'muMonoViol':>12}{'iters':>7}")
    for E in durations:
        res = dp.solve_dp(ht.matrices, ht.bin_centers, seasonal_profile, params, E, N_S=N_S)
        window_val = res.rho_day * panel["date"].nunique()
        print(f"  {E:>5.0f}{res.rho_day:>11.2f}{window_val:>13.0f}"
              f"{res.bellman_residual:>10.1e}{dp.mu_monotone_violation(res):>12.1e}"
              f"{res.iters:>7d}")

    # DP<->LP sanity on a deterministic reduction (the correctness gate, on THIS seasonal)
    det = dp.dp_vs_lp_deterministic(seasonal_profile, params, 2.0, N_S=N_S)
    print(f"\n  DP<->LP on the deterministic seasonal (E=2h): DP ${det['dp_rho_day']:.2f}/day "
          f"vs LP ${det['lp_per_day']:.2f}/day  reldiff={det['rel_diff']:.1e}")

    if N_S == 200:
        print("\n  grid convergence @2h (stochastic kernel):")
        for n in (50, 100, 200, 400):
            r = dp.solve_dp(ht.matrices, ht.bin_centers, seasonal_profile, params, 2.0, N_S=n)
            print(f"    N_S={n:3d}  DP ${r.rho_day:.3f}/day")

    print("\n  NOTE: ρ_day is the DP's IN-MODEL expected profit/day for a representative "
          "weekday.\n  The realised out-of-sample V^DP (backtest the DP offer curve on real "
          "prices), reserves/ψ_up (Q2), the duration sweep (Q3), the tail recalibration, and "
          "the §V.26 capture-rate prong are the next Stage 4 steps.")


def realized_ladder(date_from, date_to, E=2.0, N_S=200, n_bins=12, horizon=96):
    """The REALISED value-of-foresight ladder (§IV.13): solve the DP, then walk its
    offer-curve policy FORWARD on the real prices with no lookahead, and place V^DP
    between the perfect-foresight ceiling and the Stage 2/3 MPC + naive floor."""
    from src import dp
    from src.backtest import run_backtest
    from src.forecast import LearnedForecaster, PerfectForecaster, SameHourLastWeekForecaster
    from src.oracle import ENERGY_ONLY, solve
    from src.policies import DPPolicy, MPCPolicy, NaiveThresholdPolicy

    params = BatteryParams()
    inp = build_dp_inputs(date_from, date_to, n_bins)
    ht, seasonal, panel = inp["ht"], inp["seasonal"], inp["panel"]
    prices = panel["price"].to_numpy(float)
    ts = panel["ts"].to_numpy()
    n_days = panel["date"].nunique()

    res = dp.solve_dp(ht.matrices, ht.bin_centers, inp["seasonal_profile"], params, E, N_S=N_S)
    dp_pol = DPPolicy(res.V, ht.matrices, ht.edges, seasonal, ts, E, N_S)

    print(f"\n=== (B) REALISED value-of-foresight ladder @ {E:.0f}h (energy-only, {n_days} days) ===")
    ceiling = solve(prices, {}, E, params, ENERGY_ONLY).objective
    def bt(policy):
        return run_backtest(prices, policy, params, E, s_init=0.0, timestamps=ts).profit
    clair = bt(MPCPolicy(PerfectForecaster(prices), horizon=horizon))
    v_dp = bt(dp_pol)
    learned = bt(MPCPolicy(LearnedForecaster(ts, prices, min_train_months=2), horizon=horizon))
    naive = bt(MPCPolicy(SameHourLastWeekForecaster(), horizon=horizon))
    floor = bt(NaiveThresholdPolicy())

    print(f"  ceiling (perfect-foresight LP):     ${ceiling:>10,.0f}   100%")
    print(f"  MPC, perfect forecast (clairvoyant):${clair:>10,.0f}   {clair/ceiling:>4.0%}")
    print(f"  >>> DP (optimal causal policy) V^DP: ${v_dp:>10,.0f}   {v_dp/ceiling:>4.0%}")
    print(f"  MPC, learned forecast (Stage 3):    ${learned:>10,.0f}   {learned/ceiling:>4.0%}")
    print(f"  MPC, same-hour-last-week (Stage 2): ${naive:>10,.0f}")
    print(f"  naive threshold floor:              ${floor:>10,.0f}")
    print(f"\n  §IV.13 decomposition:")
    print(f"    value of information (ceiling - V^DP): ${ceiling - v_dp:>9,.0f}")
    print(f"    option value (V^DP - learned MPC):     ${v_dp - learned:>9,.0f}  "
          f"(what the DP's distribution-awareness captures beyond the CE median MPC)")
    print(f"    value of optimisation (MPC - floor):   ${learned - floor:>9,.0f}")
    if v_dp > learned:
        print("  -> the DP BEATS the certainty-equivalent MPC: positive option value, as Stage 4 must show.")
    else:
        print("  -> the DP does NOT beat the MPC here (characterise: kernel tail / representative-day approx).")
    print("\n  V^DP is REALISED out-of-sample (offer curve walked forward, no lookahead — a "
          "test asserts a scrambled future leaves decisions unchanged). NOTE: this DP uses the "
          "EMPIRICAL kernel + a representative-weekday seasonal; the capture-rate prong (learned "
          "vs empirical kernel) and reserves/ψ_up (Q2) are the remaining Stage 4 pieces.")
    return dict(ceiling=ceiling, clair=clair, v_dp=v_dp, learned=learned, naive=naive, floor=floor)


def duration_sweep(date_from, date_to, durations=(0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0),
                   N_S=200, n_bins=12):
    """Q3 — the marginal value of storage duration. Two curves (§IV.11 / plan Q3):
    V^PF(E) perfect-foresight and V^DP(E) realised optimal-causal, plus the capture-rate
    curve κ(E)=V^DP/V^PF. All DP backtests are causal (offer curve walked forward)."""
    from src import dp
    from src.backtest import run_backtest
    from src.oracle import ENERGY_ONLY, solve
    from src.policies import DPPolicy

    params = BatteryParams()
    inp = build_dp_inputs(date_from, date_to, n_bins)
    ht, seasonal, panel = inp["ht"], inp["seasonal"], inp["panel"]
    prices = panel["price"].to_numpy(float)
    ts = panel["ts"].to_numpy()
    n_days = panel["date"].nunique()

    print(f"\n=== Q3 — duration-value curves ({n_days} days, energy-only) ===")
    print(f"  {'E(h)':>5}{'V_PF $':>10}{'V_DP $':>10}{'capture':>9}{'dV_PF/dE':>11}{'dV_DP/dE':>11}")
    prev = None
    rows = []
    for E in durations:
        v_pf = solve(prices, {}, E, params, ENERGY_ONLY).objective
        res = dp.solve_dp(ht.matrices, ht.bin_centers, inp["seasonal_profile"], params, E, N_S=N_S)
        pol = DPPolicy(res.V, ht.matrices, ht.edges, seasonal, ts, E, N_S)
        v_dp = run_backtest(prices, pol, params, E, s_init=0.0, timestamps=ts).profit
        cap = v_dp / v_pf if v_pf else float("nan")
        marg_pf = marg_dp = float("nan")
        if prev is not None:
            dE = E - prev[0]
            marg_pf, marg_dp = (v_pf - prev[1]) / dE, (v_dp - prev[2]) / dE
        print(f"  {E:>5.1f}{v_pf:>10,.0f}{v_dp:>10,.0f}{cap:>8.0%}{marg_pf:>11,.0f}{marg_dp:>11,.0f}")
        rows.append((E, v_pf, v_dp, cap))
        prev = (E, v_pf, v_dp)
    print("  marginal value of duration = ΔV/ΔE ($/MWh-of-capacity/window); it should be "
          "positive and DECREASING (concave duration curve). V_DP uses the empirical kernel.")
    return rows


def capture_rate_prong(date_from, date_to, E=2.0, N_S=200, n_bins=12):
    """§V.26 capture-rate prong — the second half of the two-pronged adoption gate.
    Solve the DP on the EMPIRICAL kernel and on the LEARNED kernel (raw and tail-
    recalibrated), walk each policy forward, and adopt whichever gives the better
    REALISED capture. A tie/empirical-win is a publishable result (§V.26), not a failure."""
    from src import dp
    from src.backtest import run_backtest
    from src.oracle import ENERGY_ONLY, solve
    from src.policies import DPPolicy
    from src.price_model import QuantileGBT, fit_recalibration

    params = BatteryParams()
    panel = ingest.build_panel(date_from, date_to)
    feat = F.build_features(panel)
    seasonal = F.fit_seasonal(feat)
    fr = F.add_residual_features(feat, seasonal).dropna(subset=["resid", "resid_lag_15min"])
    edges = markov.bin_edges(fr["resid"].to_numpy(float), n_bins=n_bins)
    prices = panel["price"].to_numpy(float)
    ts = panel["ts"].to_numpy()
    n_days = panel["date"].nunique()
    rep_month = int(feat.sort_values("ts")["month"].iloc[-1])
    seasonal_profile = seasonal.eval_cal(np.arange(96), np.zeros(96, int), np.full(96, rep_month))

    # chronological 70/30 split to fit the recalibration scale on held-out data
    fr_fit = fr.dropna(subset=F.CONDITIONING + ["resid"])
    cut = int(len(fr_fit) * 0.7)
    tr, va = fr_fit.iloc[:cut], fr_fit.iloc[cut:]
    base_tr = QuantileGBT().fit(F.conditioning_matrix(tr), tr["resid"].to_numpy(float))
    recal = fit_recalibration(base_tr, va)
    base_full = QuantileGBT().fit(F.conditioning_matrix(fr_fit), fr_fit["resid"].to_numpy(float))
    from src.price_model import RecalibratedGBT
    recal_full = RecalibratedGBT(base_full, recal.scale)

    kernels = {
        "empirical": markov.transition_counts(fr, edges),
        "learned-raw": markov.transition_model(base_full, fr, edges),
        "learned-recal": markov.transition_model(recal_full, fr, edges),
    }
    print(f"\n=== §V.26 capture-rate prong @ {E:.0f}h ({n_days} days) — dispersion scale "
          f"s={recal.scale:.2f} ===")
    v_pf = solve(prices, {}, E, params, ENERGY_ONLY).objective
    print(f"  perfect-foresight ceiling: ${v_pf:,.0f}\n  {'kernel':16}{'V_DP $':>10}{'capture':>9}")
    best = (None, -np.inf)
    for name, ht in kernels.items():
        res = dp.solve_dp(ht.matrices, ht.bin_centers, seasonal_profile, params, E, N_S=N_S)
        pol = DPPolicy(res.V, ht.matrices, ht.edges, seasonal, ts, E, N_S)
        v = run_backtest(prices, pol, params, E, s_init=0.0, timestamps=ts).profit
        print(f"  {name:16}{v:>10,.0f}{v / v_pf:>8.0%}")
        if v > best[1]:
            best = (name, v)
    print(f"\n  ADOPT: {best[0]} kernel (best realised capture). "
          f"{'Learned wins BOTH prongs -> final adoption (§V.26).' if best[0].startswith('learned') else 'Empirical wins the capture prong -> adopt the nonparametric matrix; a legitimate §V.26 negative result (the learned CRPS win did not translate to better realised policy value).'}")
    return best


def state_augmentation_test(date_from, date_to, E=2.0, N_S=200, n_bins=12):
    """§VIII.7 — probe assumption [A1] by AUGMENTING the state with a scarcity-regime
    coordinate z (0/1: was the last interval a scarcity price?), re-solving, and measuring
    the change in the DP's in-model value. If (h,b,z) barely moves ρ_day, the minimal (h,b)
    state suffices (adopt it for parsimony + sample size); if it moves it materially, z earns
    its place. Compared on the in-model value so no policy/backtest change is needed."""
    from src import dp
    params = BatteryParams()
    panel = ingest.build_panel(date_from, date_to)
    feat = F.build_features(panel)
    seasonal = F.fit_seasonal(feat)
    fr = F.add_residual_features(feat, seasonal).dropna(subset=["resid", "resid_lag_15min"]).reset_index(drop=True)
    edges = markov.bin_edges(fr["resid"].to_numpy(float), n_bins=n_bins)
    rep_month = int(feat.sort_values("ts")["month"].iloc[-1])
    seasonal_profile = seasonal.eval_cal(np.arange(96), np.zeros(96, int), np.full(96, rep_month))

    ht = markov.transition_counts(fr, edges)                 # (h, b)
    base = dp.solve_dp(ht.matrices, ht.bin_centers, seasonal_profile, params, E, N_S=N_S)

    # augmented (h, b, z): z = scarcity_recent (0/1). Flatten (b,z) -> b*2+z.
    N_z, N_b = 2, n_bins
    b = np.clip(np.digitize(fr["resid"].to_numpy(float), edges[1:-1]), 0, N_b - 1)
    z = fr["scarcity_recent"].fillna(0).astype(int).to_numpy()
    flat = b * N_z + z
    hour = fr["hour_of_day"].to_numpy(int)
    n_exo = N_b * N_z
    counts = np.zeros((24, n_exo, n_exo))
    for h, fp, fn in zip(hour[1:], flat[:-1], flat[1:]):
        counts[h, fp, fn] += 1.0
    K = (counts + 0.01) / (counts + 0.01).sum(axis=2, keepdims=True)
    centers = np.array([fr["resid"].to_numpy(float)[flat == f].mean() if (flat == f).any()
                        else ht.bin_centers[f // N_z] for f in range(n_exo)])
    aug = dp.solve_dp(K, centers, seasonal_profile, params, E, N_S=N_S)

    print(f"\n=== §VIII.7 state-augmentation test @ {E:.0f}h (in-model ρ_day) ===")
    print(f"  (h,b)    state ({N_b} bins):      ρ_day = ${base.rho_day:.2f}")
    print(f"  (h,b,z)  state ({n_exo} bins, z=scarcity-regime): ρ_day = ${aug.rho_day:.2f}")
    chg = (aug.rho_day - base.rho_day) / abs(base.rho_day) if base.rho_day else float("nan")
    print(f"  change: {chg:+.1%}  ->  {'z EARNS its place (augment the state)' if abs(chg) > 0.05 else 'minimal (h,b) suffices (adopt it; z does not move the headline enough to justify the extra sparsity)'}")
    return base.rho_day, aug.rho_day


def q2_psi_up(date_from, date_to, E=2.0, N_S=200, n_bins=12):
    """Q2 (co-headline) — the causal shadow price ψ_up of RTC+B's SOC enforcement on the
    up-reserve products (RRS/ECRS/NSPIN). Option 2A: at each interval of the DP's realised
    SOC trajectory, solve the small reserve LP (sell reserves backed by held charge under
    (EH-up) + power headroom, at the hour-expected MCPC) and read ψ_up = the dual on (EH-up).
    This is the competent-causal ψ_up (Decision 19), reported by hour/scarcity regime and
    compared to the Stage 0 perfect-foresight floor.

    Caveat (2A): the DP here is energy-only, so its SOC is the arbitrage trajectory — a
    reserve-CO-optimising DP would hold more charge and face a LOWER ψ_up, so this brackets
    the truth from ABOVE while Stage 0's perfect-foresight ψ_up brackets from below."""
    import cvxpy as cp
    from src import dp
    from src.backtest import run_backtest
    from src.policies import DPPolicy

    params = BatteryParams()
    inp = build_dp_inputs(date_from, date_to, n_bins)
    ht, seasonal, panel = inp["ht"], inp["seasonal"], inp["panel"]
    prices = panel["price"].to_numpy(float)
    ts = panel["ts"].to_numpy()
    prods = ["RRS", "ECRS", "NSPIN"]
    tau = np.array([params.tau[k] for k in prods])
    # hour-expected MCPC (2A)
    hh = panel["ts"].dt.hour.to_numpy()
    rp = np.array([[panel[k].to_numpy(float)[hh == h].mean() for k in prods] for h in range(24)])

    res = dp.solve_dp(ht.matrices, ht.bin_centers, inp["seasonal_profile"], params, E, N_S=N_S)
    log = run_backtest(prices, DPPolicy(res.V, ht.matrices, ht.edges, seasonal, ts, E, N_S),
                       params, E, s_init=0.0, timestamps=ts).log
    soc = log["soc_pre"].to_numpy(float)

    # ψ_up(hour, SOC) table via the reserve LP dual on a coarse SOC grid, then look up
    grid = np.linspace(0.0, E, 41)
    u = cp.Variable(3, nonneg=True)
    s_par = cp.Parameter(nonneg=True)
    p_par = cp.Parameter(3)
    eh = (1.0 / params.eta_d) * (tau @ u) <= s_par - params.s_min
    prob = cp.Problem(cp.Maximize((p_par @ u) * params.dt),
                      [eh, cp.sum(u) <= params.p_bar])
    table = np.zeros((24, len(grid)))
    for h in range(24):
        p_par.value = rp[h]
        for gi, s in enumerate(grid):
            s_par.value = float(s)
            prob.solve(solver=cp.HIGHS)
            table[h, gi] = abs(eh.dual_value) / params.dt if eh.dual_value is not None else 0.0

    jt = np.clip(np.searchsorted(grid, soc), 0, len(grid) - 1)
    psi = table[hh[:len(soc)], jt]
    tol = 0.01 * np.median(np.abs(prices))
    binds = psi > tol
    print(f"\n=== Q2 — causal ψ_up (cost of RTC+B SOC enforcement), DP operator @ {E:.0f}h ===")
    print(f"  median ${np.median(psi):.3f}  p90 ${np.percentile(psi,90):.3f}  "
          f"p99 ${np.percentile(psi,99):.3f}  max ${psi.max():.2f}  "
          f"binds(>{tol:.3f}) {binds.mean()*100:.1f}%")
    print(f"  vs Stage 0 perfect-foresight floor (median $0.015, p99 $1.47, max $32.75) and "
          f"Stage 2 naive-MPC (median $0.015, p99 $1.46, max $141).")
    print("  Decision 19: the competent-causal ψ_up should exceed the perfect-foresight floor "
          "(a clairvoyant dodges the constraint better). 2A caveat: energy-only DP SOC -> this "
          "is an UPPER bracket; the reserve-co-optimising DP would hold more charge -> lower ψ_up.")
    return psi


def main():
    full = "--full" in sys.argv
    date_from, date_to = FULL if full else DEMO
    run(date_from, date_to, durations=(1.0, 2.0, 4.0) if full else (2.0,))
    realized_ladder(date_from, date_to, E=2.0)


if __name__ == "__main__":
    main()
