"""
DuckDB price + MCPC warehouse (Stage 1).

Loads the 15-minute energy-price + ancillary-MCPC panel into a DuckDB database
and exposes the feature pipeline as SQL views, so Stage 2's forecast and every
downstream query read from one governed, asserted source instead of re-deriving
features in ad-hoc pandas.

Scope note (honest): this warehouse covers the two series Stage 0 used — energy
price (NP6-905-CD) and RT MCPC (NP6-796-ER) at one settlement point. The plan's
full §IX.3 star schema (awards, dispatch, forecasts, day-ahead) is deferred to
the stages that actually consume those tables (Stage 2/3); building empty fact
tables now would be decoration, not evidence. The schema here is shaped so those
fact tables slot in later by joining on `ts` + `settlement_point`.

Tables / views:
  price_mcpc   base fact: one row per (settlement_point, 15-min interval)
  v_calendar   + calendar features (hour-of-day, quarter-of-day, dow, month,
               weekend flag) and the AS reserve-price aggregates
  v_features   + point-in-time lags (15-min, 1-day, 1-week — the last is Stage 2's
               "same-hour-last-week" naive forecast), trailing-day rolling mean/std,
               a z-score, and a scarcity flag
  v_daily      per-day rollup for exploratory analysis (spike frequency, ranges)

Lags are computed by an exact TIMESTAMP self-join (ts - INTERVAL ...), not a row
offset, so they stay correct across the real data gaps (DST spring-forward, the
early-May outage) rather than silently pointing 96 rows back into a gap.

Regenerate: `python -m src.warehouse` (reads cached raw data via src.ingest,
writes data/warehouse.duckdb, runs the assertions, prints a summary).
"""

from __future__ import annotations

import os

import duckdb
import pandas as pd

from src import ingest

DB_PATH = "data/warehouse.duckdb"
DATE_FROM, DATE_TO = "2025-12-05", "2026-06-20"

# ERCOT real-time price sanity bounds ($/MWh): system-wide offer cap is $5000,
# the floor is about -$251. Give margin; a value outside this is a parse error.
PRICE_LO, PRICE_HI = -500.0, 6000.0
INTERVALS_PER_DAY = 96  # a clean 15-minute day; DST/outage days have fewer


# --------------------------------------------------------------------------- #
# Build                                                                        #
# --------------------------------------------------------------------------- #
def _load_panel(date_from, date_to, settlement_point) -> pd.DataFrame:
    panel = ingest.build_panel(date_from, date_to, settlement_point, dedup=True)
    df = panel[["ts", "date", "hour", "interval", "price"] + ingest.AS_TYPES].copy()
    df["settlement_point"] = settlement_point
    return df


def build(db_path: str = DB_PATH, date_from: str = DATE_FROM, date_to: str = DATE_TO,
          settlement_point: str = "HB_NORTH", panel: pd.DataFrame | None = None) -> duckdb.DuckDBPyConnection:
    """Build (or rebuild) the warehouse and return an open connection.

    Pass `panel` to load a pre-built DataFrame (used by tests); otherwise it is
    read from cached raw data via src.ingest.
    """
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    if panel is None:
        panel = _load_panel(date_from, date_to, settlement_point)

    con = duckdb.connect(db_path)
    con.register("panel_df", panel)
    con.execute(
        """
        CREATE OR REPLACE TABLE price_mcpc AS
        SELECT
            ts::TIMESTAMP        AS ts,
            date::DATE           AS date,
            hour::SMALLINT       AS hour,
            interval::SMALLINT   AS interval,
            settlement_point::VARCHAR AS settlement_point,
            price::DOUBLE        AS price,
            ECRS::DOUBLE         AS ECRS,
            NSPIN::DOUBLE        AS NSPIN,
            REGDN::DOUBLE        AS REGDN,
            REGUP::DOUBLE        AS REGUP,
            RRS::DOUBLE          AS RRS
        FROM panel_df
        ORDER BY settlement_point, ts
        """
    )
    con.unregister("panel_df")
    _create_views(con)
    return con


def _create_views(con: duckdb.DuckDBPyConnection) -> None:
    # Calendar + AS reserve-price aggregates. hour_of_day/quarter_of_day are
    # derived from ts (0-based, canonical), independent of ERCOT's 1..24 hour-
    # ending / 1..4 interval labelling.
    con.execute(
        """
        CREATE OR REPLACE VIEW v_calendar AS
        SELECT
            ts, date, hour, interval, settlement_point, price,
            ECRS, NSPIN, REGDN, REGUP, RRS,
            RRS + ECRS + NSPIN          AS mcpc_up_contingency,  -- Kup = {RRS,ECRS,NSPIN}
            RRS + ECRS + NSPIN + REGUP  AS mcpc_up_all,          -- Kup + Reg-Up
            REGDN                       AS mcpc_dn,              -- Kdn = {Reg-Down}
            hour(ts)                              AS hour_of_day,     -- 0..23
            (hour(ts) * 4 + minute(ts) / 15)::INT AS quarter_of_day,  -- 0..95
            dayofweek(ts)                         AS dow,             -- 0=Sun .. 6=Sat
            CASE WHEN dayofweek(ts) IN (0, 6) THEN 1 ELSE 0 END AS is_weekend,
            month(ts)                             AS month
        FROM price_mcpc
        """
    )

    # Feature pipeline. Lags via exact timestamp self-join (gap-safe); rolling
    # stats over the trailing 96 rows (~1 day). price_lag_1w is the Stage 2
    # "same-hour-last-week" naive forecast target.
    con.execute(
        """
        CREATE OR REPLACE VIEW v_features AS
        WITH base AS (
            SELECT
                c.*,
                l15.price AS price_lag_15min,
                l1d.price AS price_lag_1d,
                l1w.price AS price_lag_1w,
                AVG(c.price)         OVER w AS price_roll_mean_1d,
                STDDEV_SAMP(c.price) OVER w AS price_roll_std_1d,
                CASE WHEN c.price > 100 THEN 1 ELSE 0 END AS is_scarcity  -- $100/MWh marker
            FROM v_calendar c
            LEFT JOIN price_mcpc l15 ON l15.settlement_point = c.settlement_point
                                     AND l15.ts = c.ts - INTERVAL 15 MINUTE
            LEFT JOIN price_mcpc l1d ON l1d.settlement_point = c.settlement_point
                                     AND l1d.ts = c.ts - INTERVAL 1 DAY
            LEFT JOIN price_mcpc l1w ON l1w.settlement_point = c.settlement_point
                                     AND l1w.ts = c.ts - INTERVAL 7 DAY
            WINDOW w AS (ORDER BY c.ts ROWS BETWEEN 96 PRECEDING AND 1 PRECEDING)
        )
        SELECT *,
            CASE WHEN price_roll_std_1d > 0
                 THEN (price - price_roll_mean_1d) / price_roll_std_1d END AS price_z_1d
        FROM base
        """
    )

    # Per-day rollup for exploratory analysis (spike frequency/clustering, ranges).
    con.execute(
        """
        CREATE OR REPLACE VIEW v_daily AS
        SELECT
            date,
            count(*)                               AS n_intervals,
            min(price)                             AS price_min,
            avg(price)                             AS price_mean,
            quantile_cont(price, 0.5)              AS price_median,
            max(price)                             AS price_max,
            max(price) - min(price)                AS price_range,
            sum(CASE WHEN price > 100 THEN 1 ELSE 0 END) AS n_scarcity_intervals,
            avg(mcpc_up_contingency)               AS mcpc_up_contingency_mean
        FROM v_calendar
        GROUP BY date
        ORDER BY date
        """
    )


# --------------------------------------------------------------------------- #
# Assertions                                                                   #
# --------------------------------------------------------------------------- #
def assert_warehouse(con: duckdb.DuckDBPyConnection) -> dict:
    """Run the warehouse integrity gate.

    HARD checks raise AssertionError (uniqueness, nulls, price bounds, no day
    with > 96 intervals, monotone timestamps). SOFT observations (short days
    from DST/outages) are counted and returned, never fatal — those gaps are
    real ERCOT data, and hiding them would be the dishonest move.
    """
    one = lambda q: con.execute(q).fetchone()[0]  # noqa: E731

    n_rows = one("SELECT count(*) FROM price_mcpc")
    assert n_rows > 0, "warehouse is empty"

    # HARD: no null in any measured or key column.
    nulls = con.execute(
        """
        SELECT sum(CASE WHEN ts IS NULL OR date IS NULL OR hour IS NULL
                          OR interval IS NULL OR price IS NULL
                          OR ECRS IS NULL OR NSPIN IS NULL OR REGDN IS NULL
                          OR REGUP IS NULL OR RRS IS NULL THEN 1 ELSE 0 END)
        FROM price_mcpc
        """
    ).fetchone()[0]
    assert nulls == 0, f"{nulls} rows contain a NULL in a key/measure column"

    # HARD: (settlement_point, date, hour, interval) unique, and ts unique.
    dup_key = one(
        """
        SELECT count(*) FROM (
            SELECT 1 FROM price_mcpc
            GROUP BY settlement_point, date, hour, interval HAVING count(*) > 1
        )
        """
    )
    assert dup_key == 0, f"{dup_key} duplicate (settlement_point,date,hour,interval) keys"
    dup_ts = one(
        "SELECT count(*) FROM (SELECT 1 FROM price_mcpc "
        "GROUP BY settlement_point, ts HAVING count(*) > 1)"
    )
    assert dup_ts == 0, f"{dup_ts} duplicate timestamps"

    # HARD: timestamps strictly increasing within a settlement point.
    non_incr = one(
        """
        SELECT count(*) FROM (
            SELECT ts - lag(ts) OVER (PARTITION BY settlement_point ORDER BY ts) AS d
            FROM price_mcpc
        ) WHERE d IS NOT NULL AND d <= INTERVAL 0 SECOND
        """
    )
    assert non_incr == 0, f"{non_incr} non-increasing timestamp steps"

    # HARD: no SUB-interval step (0 < gap < 15 min). A step smaller than one
    # interval means the time axis is misaligned — e.g. a DST hour double-counted
    # or an interval mislabelled. This is the check that closes the DST-boundary
    # risk: at a real transition the axis JUMPS (a >15-min gap, reported softly
    # below), it never compresses.
    sub_interval = one(
        """
        SELECT count(*) FROM (
            SELECT ts - lag(ts) OVER (PARTITION BY settlement_point ORDER BY ts) AS d
            FROM price_mcpc
        ) WHERE d IS NOT NULL AND d > INTERVAL 0 SECOND AND d < INTERVAL 15 MINUTE
        """
    )
    assert sub_interval == 0, (
        f"{sub_interval} sub-15-minute timestamp steps (time axis misaligned)"
    )

    # HARD: prices within sanity bounds; MCPC non-negative.
    oob = one(f"SELECT count(*) FROM price_mcpc WHERE price < {PRICE_LO} OR price > {PRICE_HI}")
    assert oob == 0, f"{oob} prices outside [{PRICE_LO}, {PRICE_HI}] $/MWh"
    neg_mcpc = one(
        "SELECT count(*) FROM price_mcpc "
        "WHERE least(ECRS, NSPIN, REGDN, REGUP, RRS) < -0.01"
    )
    assert neg_mcpc == 0, f"{neg_mcpc} negative MCPC values"

    # HARD: no calendar day carries MORE than 96 intervals (that means a key
    # collision / bad parse, not a real gap).
    over = one(
        f"SELECT count(*) FROM (SELECT date FROM price_mcpc "
        f"GROUP BY settlement_point, date HAVING count(*) > {INTERVALS_PER_DAY})"
    )
    assert over == 0, f"{over} days with > {INTERVALS_PER_DAY} intervals (key collision?)"

    # SOFT: short days (DST spring-forward, outages). Report, do not fail.
    short_days = con.execute(
        f"""
        SELECT date, count(*) AS n
        FROM price_mcpc GROUP BY settlement_point, date
        HAVING count(*) < {INTERVALS_PER_DAY} ORDER BY date
        """
    ).fetchall()
    n_days = one("SELECT count(DISTINCT date) FROM price_mcpc")
    gaps = audit_gaps(con)

    return {
        "n_rows": n_rows,
        "n_days": n_days,
        "n_settlement_points": one("SELECT count(DISTINCT settlement_point) FROM price_mcpc"),
        "ts_min": str(one("SELECT min(ts) FROM price_mcpc")),
        "ts_max": str(one("SELECT max(ts) FROM price_mcpc")),
        "n_short_days": len(short_days),
        "short_days": [(str(d), int(n)) for d, n in short_days],
        "n_gaps": len(gaps),
        "gaps": gaps,
        "total_missing_intervals": sum(g["missing_intervals"] for g in gaps),
        "expected_if_all_full": n_days * INTERVALS_PER_DAY,
    }


def audit_gaps(con: duckdb.DuckDBPyConnection, expected_step_min: int = 15) -> list[dict]:
    """List every jump in the time axis larger than one interval.

    A '15-minute series' should step by exactly 15 minutes. Real ERCOT data has
    holes — the DST spring-forward hour, and outages (early May) — so gaps are
    EXPECTED and reported, not fatal (the fatal case, a sub-interval step, is a
    HARD assertion in assert_warehouse). This audit exists so those holes are
    named and eyeballed rather than silently smoothed over: at each gap we can
    confirm the missing-interval count matches a known cause.
    """
    rows = con.execute(
        f"""
        SELECT settlement_point, prev_ts, ts AS next_ts, step
        FROM (
            SELECT settlement_point, ts,
                   lag(ts) OVER (PARTITION BY settlement_point ORDER BY ts) AS prev_ts,
                   ts - lag(ts) OVER (PARTITION BY settlement_point ORDER BY ts) AS step
            FROM price_mcpc
        )
        WHERE step IS NOT NULL AND step > INTERVAL {expected_step_min} MINUTE
        ORDER BY next_ts
        """
    ).fetchall()
    out = []
    for sp, prev_ts, next_ts, step in rows:
        gap_min = step.total_seconds() / 60.0
        out.append({
            "settlement_point": sp,
            "gap_start": str(prev_ts),
            "gap_end": str(next_ts),
            "gap_minutes": gap_min,
            "missing_intervals": int(round(gap_min / expected_step_min)) - 1,
        })
    return out


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def main():
    print(f"Building warehouse at {DB_PATH} for {DATE_FROM}..{DATE_TO} (HB_NORTH)...")
    con = build()
    stats = assert_warehouse(con)
    print("\n=== assertions PASSED ===")
    print(f"  rows                 {stats['n_rows']:,}")
    print(f"  days                 {stats['n_days']}")
    print(f"  settlement points    {stats['n_settlement_points']}")
    print(f"  ts range             {stats['ts_min']} .. {stats['ts_max']}")
    print(f"  full-day ideal       {stats['expected_if_all_full']:,} "
          f"(actual {stats['n_rows']:,}; short by "
          f"{stats['expected_if_all_full'] - stats['n_rows']:,})")
    print(f"  short days (< 96)    {stats['n_short_days']}: {stats['short_days']}")
    print(f"  time-axis gaps       {stats['n_gaps']} "
          f"({stats['total_missing_intervals']} missing intervals total)")
    for g in stats["gaps"]:
        print(f"    gap {g['gap_start']} -> {g['gap_end']}  "
              f"({g['gap_minutes']:.0f} min, {g['missing_intervals']} missing)")

    print("\n=== v_features sample (first non-null-lag rows) ===")
    df = con.execute(
        """
        SELECT ts, price, price_lag_1w, price_roll_mean_1d, price_z_1d, is_scarcity
        FROM v_features WHERE price_lag_1w IS NOT NULL ORDER BY ts LIMIT 5
        """
    ).df()
    print(df.to_string(index=False))

    print("\n=== v_daily: top scarcity days ===")
    df2 = con.execute(
        "SELECT date, n_intervals, price_max, n_scarcity_intervals "
        "FROM v_daily ORDER BY n_scarcity_intervals DESC, price_max DESC LIMIT 5"
    ).df()
    print(df2.to_string(index=False))
    con.close()


if __name__ == "__main__":
    main()
