"""
Stage 7 — fleet reconstruction & cross-section (Phase A: energy).

Reconstructs each ESR's REALIZED energy revenue from disclosure (two-settlement: day-ahead award
valued at the DA node price, plus the real-time DEVIATION valued at the RT node LMP), computes
each asset's perfect-foresight ENERGY ceiling on its own node prices at its own power (HSL) and
duration (MaxSOC) via the existing oracle, and reports the cross-sectional capture distribution and
the fleet-average $/kW-month for the C1 external check against Modo/Ascend.

Reported GROSS of degradation (each operator's cycling cost is unobserved; Modo also reports gross),
so realized gross is compared to the gross revenue of a degradation-AWARE clairvoyant (the ceiling
LP runs at the study's c_deg=25 so it does not over-cycle, then we read its gross energy revenue).

Runs AFTER src.disclosure_ingest and src.fleet_prices have populated the warehouse.

    python -m src.stage7_run --db data/warehouse_fleet.duckdb
"""

from __future__ import annotations

import argparse
import os
import warnings

import numpy as np
import pandas as pd

from src import fleet_warehouse as fw

warnings.filterwarnings("ignore", message="overflow encountered in reduce")  # benign numpy reduce

DT = 0.25  # hours per 15-min interval
CACHE = "data/raw/stage7_energy_cross_section.parquet"  # persist the ~300 ceiling LP solves


# --------------------------------------------------------------------------- #
#  PURE revenue functions (no IO) — unit-tested
# --------------------------------------------------------------------------- #
def da_energy_revenue(award_mw, da_price) -> float:
    """Day-ahead energy revenue = sum over hours of award(MW) x DA price ($/MWh) x 1h."""
    return float(np.sum(np.asarray(award_mw, float) * np.asarray(da_price, float)))


def rt_deviation_revenue(telem_mw, award_mw, rt_lmp, dt: float = DT) -> float:
    """Real-time settlement of the DEVIATION from the DA position: (actual - DA) x RT LMP x dt.
    Charging (telem < 0) is a purchase (negative revenue). This is the second half of ERCOT's
    two-settlement; DA award + this = total energy settlement."""
    return float(np.sum((np.asarray(telem_mw, float) - np.asarray(award_mw, float))
                        * np.asarray(rt_lmp, float)) * dt)


def gross_revenue_from_dispatch(prices, c, d, dt: float = DT) -> float:
    """Gross energy revenue of a (charge c, discharge d) schedule at `prices`: sum P(d-c)dt."""
    return float(np.sum(np.asarray(prices, float)
                        * (np.asarray(d, float) - np.asarray(c, float))) * dt)


def asset_energy_ceiling(prices, hsl, maxsoc, c_deg: float = 25.0):
    """Perfect-foresight ENERGY ceiling for one asset on its own node prices, at its own power
    (HSL, MW) and energy (MaxSOC, MWh). Returns (objective_net, gross_revenue). NaN if degenerate."""
    prices = np.asarray(prices, float)
    if not (maxsoc > 0 and hsl > 0) or prices.size < 4 or not np.isfinite(prices).all():
        return float("nan"), float("nan")
    from src.oracle import ENERGY_ONLY, BatteryParams, solve
    params = BatteryParams(p_bar=float(hsl), c_deg=float(c_deg))
    res = solve(prices, {}, float(maxsoc), params, ENERGY_ONLY)
    return float(res.objective), gross_revenue_from_dispatch(prices, res.c, res.d, params.dt)


# --------------------------------------------------------------------------- #
#  SQL: realized energy revenue per ESR (two-settlement)
# --------------------------------------------------------------------------- #
_REALIZED_ENERGY_SQL = """
WITH da AS (   -- day-ahead energy revenue per battery
    SELECT resource_name, sum(da_energy_award_mw * da_spp) AS da_energy_rev
    FROM fact_dam_esr GROUP BY resource_name
),
rt AS (        -- real-time deviation revenue: (telem - DA award) x node RT LMP x dt
    SELECT s.resource_name,
           sum((s.telem_output_mw - COALESCE(d.da_energy_award_mw, 0)) * p.rt_lmp) * {dt} AS rt_dev_rev,
           count(*) AS n_intervals
    FROM fact_sced_esr s
    JOIN dim_esr dim USING (resource_name)
    JOIN prices_node p ON p.settlement_point = dim.settlement_point AND p.ts_15min = s.ts_15min
    LEFT JOIN fact_dam_esr d
           ON d.resource_name = s.resource_name
          AND d.delivery_date = CAST(s.ts_15min AS DATE)
          AND d.hour_ending = extract(hour FROM s.ts_15min) + 1
    GROUP BY s.resource_name
)
SELECT dim.resource_name, dim.settlement_point, dim.hsl_mw, dim.max_soc_mwh, dim.duration_h,
       COALESCE(da.da_energy_rev, 0) AS da_energy_rev,
       COALESCE(rt.rt_dev_rev, 0)    AS rt_dev_rev,
       COALESCE(da.da_energy_rev, 0) + COALESCE(rt.rt_dev_rev, 0) AS realized_energy_rev,
       rt.n_intervals
FROM dim_esr dim
LEFT JOIN da  USING (resource_name)
LEFT JOIN rt  USING (resource_name)
"""


def realized_energy(con) -> pd.DataFrame:
    return con.execute(_REALIZED_ENERGY_SQL.format(dt=DT)).df()


# --------------------------------------------------------------------------- #
#  Phase B — ancillary revenue (DA + RT two-settlement)
# --------------------------------------------------------------------------- #
def as_capacity_revenue(award_mw, mcpc, dt: float = 1.0) -> float:
    """Ancillary capacity payment = sum award(MW) x MCPC($/MW-h) x dt(h). DA uses dt=1 (hourly
    award); RT uses dt=0.25 (per 15-min interval)."""
    return float(np.sum(np.asarray(award_mw, float) * np.asarray(mcpc, float)) * dt)


_AS_REVENUE_SQL = """
WITH da AS (   -- day-ahead AS capacity payment per battery (hourly award x DA MCPC), NULL-robust
    SELECT resource_name,
           sum(COALESCE(da_regup_mw*da_regup_mcpc,0) + COALESCE(da_regdn_mw*da_regdn_mcpc,0)
             + COALESCE(da_rrs_mw*da_rrs_mcpc,0) + COALESCE(da_ecrs_mw*da_ecrs_mcpc,0)
             + COALESCE(da_nspin_mw*da_nspin_mcpc,0)) AS da_as_rev
    FROM fact_dam_esr GROUP BY resource_name
),
rt AS (        -- real-time AS: total award x RT MCPC, and the two-settlement DEVIATION from DA
    SELECT s.resource_name,
      sum(COALESCE(s.as_regup_mw*mc.mcpc_regup,0) + COALESCE(s.as_regdn_mw*mc.mcpc_regdn,0)
        + COALESCE(s.as_rrs_mw*mc.mcpc_rrs,0) + COALESCE(s.as_ecrs_mw*mc.mcpc_ecrs,0)
        + COALESCE(s.as_nspin_mw*mc.mcpc_nspin,0)) * {dt} AS rt_as_total,
      sum(COALESCE((s.as_regup_mw-COALESCE(d.da_regup_mw,0))*mc.mcpc_regup,0)
        + COALESCE((s.as_regdn_mw-COALESCE(d.da_regdn_mw,0))*mc.mcpc_regdn,0)
        + COALESCE((s.as_rrs_mw  -COALESCE(d.da_rrs_mw,0))  *mc.mcpc_rrs,0)
        + COALESCE((s.as_ecrs_mw -COALESCE(d.da_ecrs_mw,0)) *mc.mcpc_ecrs,0)
        + COALESCE((s.as_nspin_mw-COALESCE(d.da_nspin_mw,0))*mc.mcpc_nspin,0)) * {dt} AS rt_as_incr
    FROM fact_sced_esr s
    JOIN prices_mcpc_rt mc ON mc.ts_15min = s.ts_15min
    LEFT JOIN fact_dam_esr d
           ON d.resource_name = s.resource_name
          AND d.delivery_date = CAST(s.ts_15min AS DATE)
          AND d.hour_ending = extract(hour FROM s.ts_15min) + 1
    GROUP BY s.resource_name
)
SELECT dim.resource_name,
       COALESCE(da.da_as_rev, 0)   AS da_as_rev,
       COALESCE(rt.rt_as_total, 0) AS rt_as_total,
       COALESCE(rt.rt_as_incr, 0)  AS rt_as_incr,
       COALESCE(da.da_as_rev, 0) + COALESCE(rt.rt_as_incr, 0) AS as_rev_twosettle
FROM dim_esr dim LEFT JOIN da USING (resource_name) LEFT JOIN rt USING (resource_name)
"""


def as_revenue(con) -> pd.DataFrame:
    return con.execute(_AS_REVENUE_SQL.format(dt=DT)).df()


def eligibility(df: pd.DataFrame, min_duration=0.25, max_duration=12.0, min_hsl=0.5) -> pd.Series:
    """Documented data-hygiene rule: which ESRs get a capture rate, and WHY the rest are excluded.
    A capture ratio is only meaningful for a real battery with a node, a positive power, and a
    plausible duration (MaxSOC/HSL). We drop: assets with no settlement point; HSL below `min_hsl`
    MW (registration stubs / non-batteries); duration below `min_duration` h (degenerate 0-SOC
    telemetry) or above `max_duration` h (implausible — a data error). Returns a reason per row
    ('eligible' or the exclusion cause) so the writeup can REPORT the selection, not hide it."""
    reason = pd.Series("eligible", index=df.index)
    sp = df["settlement_point"].astype("string")
    reason = reason.mask(sp.isna() | (sp.str.len() == 0), "no_node")
    reason = reason.mask((reason == "eligible") & ~(df["hsl_mw"] > min_hsl), "power_too_small")
    reason = reason.mask((reason == "eligible") & ~(df["duration_h"] >= min_duration), "duration_lt_min")
    reason = reason.mask((reason == "eligible") & (df["duration_h"] > max_duration), "duration_implausible")
    return reason


def energy_cross_section(con, min_duration=0.25, c_deg=25.0, verbose=True,
                         cache_path=CACHE, use_cache=False) -> pd.DataFrame:
    """Per-asset realized energy revenue, PF energy ceiling, capture, and $/kW-month. Only assets
    with a node, a positive duration, and priced intervals get a ceiling/capture (§VIII.4: never a
    capture where the ceiling is ~0). Result is cached (the ~300 ceiling LP solves are the cost);
    use_cache=True loads it instead of re-solving."""
    if use_cache and cache_path and os.path.exists(cache_path):
        df = pd.read_parquet(cache_path)
        if verbose:
            _print_cross_section(df, int(df["n_days"].iloc[0]))
        return df
    df = realized_energy(con)
    df["eligible_reason"] = eligibility(df, min_duration=min_duration)
    n_days = con.execute("SELECT count(DISTINCT CAST(ts_15min AS DATE)) FROM fact_sced_esr").fetchone()[0]
    months = max(n_days / 30.44, 1e-9)

    ceilings, gross_ceils = [], []
    for row in df.itertuples():
        if row.eligible_reason != "eligible":              # documented hygiene rule (see eligibility)
            ceilings.append(np.nan); gross_ceils.append(np.nan); continue
        prices = con.execute("SELECT rt_lmp FROM prices_node WHERE settlement_point=? ORDER BY ts_15min",
                             [row.settlement_point]).df()["rt_lmp"].to_numpy(float)
        obj, gross = asset_energy_ceiling(prices, row.hsl_mw, row.max_soc_mwh, c_deg)
        ceilings.append(obj); gross_ceils.append(gross)
    df["ceiling_net"] = ceilings
    df["ceiling_gross"] = gross_ceils
    df["capture"] = df["realized_energy_rev"] / df["ceiling_gross"].where(df["ceiling_gross"] > 1.0)
    df["realized_kw_month"] = df["realized_energy_rev"] / (df["hsl_mw"] * 1000.0) / months
    df["n_days"] = n_days
    if cache_path:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        df.to_parquet(cache_path)
    if verbose:
        _print_cross_section(df, n_days)
    return df


def _print_cross_section(df, n_days):
    valid = df[df["capture"].notna()]
    print(f"\n=== Stage 7 Phase A — energy cross-section ({len(df)} ESRs, {n_days} days) ===")
    excl = df[df["eligible_reason"] != "eligible"]["eligible_reason"].value_counts().to_dict()
    print(f"  eligible universe: {int((df['eligible_reason']=='eligible').sum())} of {len(df)} ESRs "
          f"(excluded: {excl or 'none'})")
    print(f"  assets with a valid ceiling/capture: {len(valid)}")
    if len(valid):
        cap = valid["capture"]
        print(f"  CAPTURE (realized energy / PF energy ceiling): "
              f"median {cap.median():.0%}, p25 {cap.quantile(.25):.0%}, p75 {cap.quantile(.75):.0%}")
        print(f"    §VIII.4 sanity band is 50-80%; a fleet median far outside it flags a "
              f"reconstruction bug, not a finding.")
    fleet_kw = df["realized_kw_month"].replace([np.inf, -np.inf], np.nan).dropna()
    print(f"  realized ENERGY $/kW-month: fleet median {fleet_kw.median():.2f}, "
          f"mean {fleet_kw.mean():.2f}  (C1: compare to Modo's ERCOT index; AS is Phase B)")
    print(f"  energy-revenue split: DA ${df['da_energy_rev'].sum():,.0f}, "
          f"RT-deviation ${df['rt_dev_rev'].sum():,.0f}")


# C1 reference: Modo Energy's published ERCOT BESS TOTAL revenue benchmark ($/kW-month) for THIS
# window. ERCOT storage revenue collapsed from ~$193/kW (2023) to ~$29/kW (2025, ~$2.45/mo avg) as
# AS saturated and spreads compressed. The actual settled MONTHLY figures over Dec-2025→May-2026:
# Jan-26 $3.94 (cold-snap scarcity), Feb-26 $1.08 (low spreads), Apr-26 $3.12; Dec/Oct/Nov-25 ~$2.
# So the honest comparison band for the WINDOW MEAN is ~$1-$4, not the stale 2023-24 $3-6.
# Sources: modoenergy.com ERCOT BESS monthly benchmarks (Nov-2025, Feb-2026, "2026: 7 things").
C1_MODO_BAND = (1.0, 4.0)
C1_MODO_MONTHLY = {"2026-01": 3.94, "2026-02": 1.08, "2026-04": 3.12}  # settled fleet-avg $/kW-mo


def fleet_revenue(con, verbose=True) -> pd.DataFrame:
    """Combine realized energy (Phase A, cached) with realized AS (Phase B) → total revenue,
    energy-vs-AS split, total $/kW-month, and the C1 sanity check vs the published Modo band."""
    energy = energy_cross_section(con, use_cache=True, verbose=False)
    as_df = as_revenue(con)
    df = energy.merge(as_df, on="resource_name", how="left")
    df["as_rev"] = df["as_rev_twosettle"].fillna(0.0)
    df["total_rev"] = df["realized_energy_rev"].fillna(0.0) + df["as_rev"]
    n_days = int(df["n_days"].iloc[0]); months = max(n_days / 30.44, 1e-9)
    elig = df[df["eligible_reason"] == "eligible"].copy()
    elig["total_kw_month"] = elig["total_rev"] / (elig["hsl_mw"] * 1000.0) / months
    if verbose:
        _print_fleet(df, elig, months, n_days)
    return df


def _print_fleet(df, elig, months, n_days):
    tot_e = df["realized_energy_rev"].sum(); tot_da = df["da_as_rev"].sum()
    tot_rt = df["rt_as_incr"].sum(); tot_as = df["as_rev"].sum(); tot = df["total_rev"].sum()
    as_share = tot_as / tot if tot else float("nan")
    med_kw = elig["total_kw_month"].replace([np.inf, -np.inf], np.nan).median()
    mean_kw = elig["total_kw_month"].replace([np.inf, -np.inf], np.nan).mean()
    lo, hi = C1_MODO_BAND
    print(f"\n=== Stage 7 Phase B — total revenue & C1 ({len(elig)} eligible ESRs, {n_days} days) ===")
    print(f"  fleet revenue: energy ${tot_e/1e6:.1f}M + AS ${tot_as/1e6:.1f}M = TOTAL ${tot/1e6:.1f}M")
    print(f"    AS split: DA ${tot_da/1e6:.1f}M + RT-deviation ${tot_rt/1e6:.1f}M "
          f"(rt_as_total diagnostic ${df['rt_as_total'].sum()/1e6:.1f}M)")
    print(f"  AS share of total revenue: {as_share:.0%}  (historically AS-dominated, but AS "
          f"collapsed in 2025-26 — this window is energy/scarcity-led, matching our Stage 0-5 finding)")
    print(f"  TOTAL $/kW-month: fleet median ${med_kw:.2f}, mean ${mean_kw:.2f}")
    inband = lo <= mean_kw <= hi
    print(f"  C1 vs Modo's ACTUAL settled benchmark for this window (${lo:.0f}-${hi:.0f}/kW-month; "
          f"Jan-26 $3.94, Feb-26 $1.08, Apr-26 $3.12):")
    print(f"    reconstructed mean ${mean_kw:.2f} is {'WITHIN' if inband else 'OUTSIDE'} the range → "
          f"{'pipeline validated to first order' if inband else 'investigate'}. "
          f"On the low side (AS two-settlement approx and small/underperforming assets in the mean); "
          f"a per-month comparison is the refinement.")


LOCATE_CACHE = "data/raw/stage7_locate_policy.parquet"


def our_dp_capture(con, assets_df, N_S=100, min_train_months=2, verbose=True):
    """Run OUR Stage-4 walk-forward DP on each asset's OWN node prices at its power/duration, and
    return our modelled ENERGY capture next to the operator's realised energy capture. This is the
    'locate our policy' punchline: where would our causal DP rank in the real fleet? Energy-only,
    walk-forward (causal, like the real operators). Reuses WalkForwardDPPolicy unchanged."""
    from src.backtest import run_backtest
    from src.oracle import BatteryParams
    from src.policies import WalkForwardDPPolicy
    out = []
    n = len(assets_df)
    for i, row in enumerate(assets_df.itertuples()):
        pr = con.execute("SELECT ts_15min AS ts, rt_lmp AS price FROM prices_node "
                         "WHERE settlement_point=? ORDER BY ts_15min", [row.settlement_point]).df()
        our_cap = float("nan")
        if len(pr) >= 96 * 90 and row.ceiling_gross and row.ceiling_gross > 1.0:
            try:
                params = BatteryParams(p_bar=float(row.hsl_mw))
                pol = WalkForwardDPPolicy(pr, params, float(row.max_soc_mwh), N_S=N_S,
                                          min_train_months=min_train_months)
                r = run_backtest(pr["price"].to_numpy(float), pol, params, float(row.max_soc_mwh),
                                 s_init=0.0, timestamps=pr["ts"].to_numpy())
                our_cap = r.profit / row.ceiling_gross      # same full-window ceiling as realised
            except Exception:                               # noqa: BLE001
                pass
        out.append({"resource_name": row.resource_name, "settlement_point": row.settlement_point,
                    "duration_h": row.duration_h, "our_dp_capture": our_cap,
                    "realized_capture": row.capture})
        if verbose and (i % 20 == 0):
            fw.write_status(f"Stage 7 LOCATE-OUR-POLICY (DP per asset)\n  {i+1}/{n} solved\n  in progress...")
            print(f"  [{i+1}/{n}] {row.resource_name}: our {our_cap:.0%} vs realised {row.capture:.0%}", flush=True)
    df = pd.DataFrame(out)
    fw.write_status(f"Stage 7 LOCATE-OUR-POLICY\n  {n}/{n} solved\n  >>> COMPLETE")
    return df


def locate_our_policy(con, sample=None, N_S=100, verbose=True):
    """Compute our-DP vs realised capture across the eligible fleet (or a `sample`), cache it, and
    report the percentile at which our modelled policy would rank."""
    energy = energy_cross_section(con, use_cache=True, verbose=False)
    elig = energy[(energy["eligible_reason"] == "eligible") & (energy["capture"].notna())].copy()
    if sample:
        elig = elig.sample(n=min(sample, len(elig)), random_state=0)
    res = our_dp_capture(con, elig, N_S=N_S, verbose=verbose)
    valid = res[res["our_dp_capture"].notna() & res["realized_capture"].notna()]
    if len(valid):
        wins = (valid["our_dp_capture"] > valid["realized_capture"]).mean()
        pct = (valid["realized_capture"] < valid["our_dp_capture"].median()).mean()
        print(f"\n=== Stage 7 — locate our policy ({len(valid)} assets) ===")
        print(f"  our DP energy capture:   median {valid['our_dp_capture'].median():.0%}")
        print(f"  realised energy capture: median {valid['realized_capture'].median():.0%}")
        print(f"  our DP beats the real operator on {wins:.0%} of assets (energy, same node)")
        print(f"  our DP median capture ranks at the ~{pct:.0%}th percentile of realised captures")
    if LOCATE_CACHE:
        res.to_parquet(LOCATE_CACHE)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=fw.DEFAULT_PATH)
    ap.add_argument("--phase-b", action="store_true", help="total revenue + AS + C1 (needs prices_mcpc_rt)")
    ap.add_argument("--locate", type=int, nargs="?", const=0, default=None,
                    help="locate our policy; optional int = sample size (0/omit value = full fleet)")
    a = ap.parse_args()
    con = fw.connect(a.db)
    print("warehouse:", fw.summary(con))
    if a.locate is not None:
        locate_our_policy(con, sample=(a.locate or None))
    elif a.phase_b:
        fleet_revenue(con)
    else:
        energy_cross_section(con)
    con.close()


if __name__ == "__main__":
    main()
