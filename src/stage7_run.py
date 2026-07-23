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

import numpy as np
import pandas as pd

from src import fleet_warehouse as fw

DT = 0.25  # hours per 15-min interval


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


def energy_cross_section(con, min_duration=0.25, c_deg=25.0, verbose=True) -> pd.DataFrame:
    """Per-asset realized energy revenue, PF energy ceiling, capture, and $/kW-month. Only assets
    with a node, a positive duration, and priced intervals get a ceiling/capture (§VIII.4: never a
    capture where the ceiling is ~0)."""
    df = realized_energy(con)
    n_days = con.execute("SELECT count(DISTINCT CAST(ts_15min AS DATE)) FROM fact_sced_esr").fetchone()[0]
    months = max(n_days / 30.44, 1e-9)

    ceilings, gross_ceils = [], []
    for row in df.itertuples():
        if not (row.settlement_point and row.duration_h and row.duration_h >= min_duration):
            ceilings.append(np.nan); gross_ceils.append(np.nan); continue
        prices = con.execute("SELECT rt_lmp FROM prices_node WHERE settlement_point=? ORDER BY ts_15min",
                             [row.settlement_point]).df()["rt_lmp"].to_numpy(float)
        obj, gross = asset_energy_ceiling(prices, row.hsl_mw, row.max_soc_mwh, c_deg)
        ceilings.append(obj); gross_ceils.append(gross)
    df["ceiling_net"] = ceilings
    df["ceiling_gross"] = gross_ceils
    df["capture"] = df["realized_energy_rev"] / df["ceiling_gross"].where(df["ceiling_gross"] > 1.0)
    df["realized_kw_month"] = df["realized_energy_rev"] / (df["hsl_mw"] * 1000.0) / months
    df.attrs["n_days"] = n_days
    df.attrs["months"] = months
    if verbose:
        _print_cross_section(df, n_days)
    return df


def _print_cross_section(df, n_days):
    valid = df[df["capture"].notna()]
    print(f"\n=== Stage 7 Phase A — energy cross-section ({len(df)} ESRs, {n_days} days) ===")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=fw.DEFAULT_PATH)
    a = ap.parse_args()
    con = fw.connect(a.db)
    print("warehouse:", fw.summary(con))
    energy_cross_section(con)
    con.close()


if __name__ == "__main__":
    main()
