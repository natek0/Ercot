"""
Warehouse integrity + feature-pipeline tests.

Core tests build an in-memory synthetic warehouse (no ERCOT data needed, so they
run in CI). One skipif test exercises the real cached panel locally.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

from src import warehouse

REAL_PANEL = "data/raw/energy_HB_NORTH_2025-12-05_2026-06-20.parquet"


def _wh(tmp_path, df, name="w.duckdb"):
    return warehouse.build(db_path=str(tmp_path / name), panel=df)


# --- happy path ------------------------------------------------------------ #
def test_build_and_assert_clean(tmp_path, make_panel):
    con = _wh(tmp_path, make_panel(8))
    stats = warehouse.assert_warehouse(con)
    assert stats["n_rows"] == 8 * 96
    assert stats["n_days"] == 8
    assert stats["n_short_days"] == 0
    assert stats["n_settlement_points"] == 1


def test_views_exist_and_columns(tmp_path, make_panel):
    con = _wh(tmp_path, make_panel(9))
    cols = {r[0] for r in con.execute("DESCRIBE v_features").fetchall()}
    for c in ("hour_of_day", "quarter_of_day", "dow", "is_weekend", "month",
              "mcpc_up_contingency", "price_lag_15min", "price_lag_1d",
              "price_lag_1w", "price_roll_mean_1d", "price_roll_std_1d",
              "price_z_1d", "is_scarcity"):
        assert c in cols, f"missing feature column {c}"


def test_quarter_of_day_range(tmp_path, make_panel):
    con = _wh(tmp_path, make_panel(3))
    lo, hi = con.execute("SELECT min(quarter_of_day), max(quarter_of_day) FROM v_calendar").fetchone()
    assert lo == 0 and hi == 95


# --- feature correctness --------------------------------------------------- #
def test_lag_1w_is_exactly_one_week_back(tmp_path, make_panel):
    """price_lag_1w on each row equals the price at exactly ts - 7 days."""
    con = _wh(tmp_path, make_panel(9))
    # Independently re-derive the 1-week lag by a timestamp self-join and confirm
    # it matches the view's column for every row that has one.
    mismatches = con.execute(
        """
        SELECT count(*) FROM v_features f
        JOIN price_mcpc b ON b.settlement_point = f.settlement_point
                          AND b.ts = f.ts - INTERVAL 7 DAY
        WHERE f.price_lag_1w IS NULL OR abs(f.price_lag_1w - b.price) > 1e-9
        """
    ).fetchone()[0]
    assert mismatches == 0


def test_first_week_has_null_lag(tmp_path, make_panel):
    """No fabricated history: the first week has no 1-week lag."""
    con = _wh(tmp_path, make_panel(9))
    n_null = con.execute(
        "SELECT count(*) FROM v_features WHERE price_lag_1w IS NULL"
    ).fetchone()[0]
    assert n_null == 96 * 7  # exactly the first 7 days


def test_daily_rollup_counts(tmp_path, make_panel):
    con = _wh(tmp_path, make_panel(4))
    rows = con.execute("SELECT date, n_intervals FROM v_daily ORDER BY date").fetchall()
    assert len(rows) == 4
    assert all(n == 96 for _, n in rows)


# --- assertions must FIRE on bad data -------------------------------------- #
def test_duplicate_key_assertion_fires(tmp_path, make_panel):
    df = make_panel(3)
    bad = pd.concat([df, df.iloc[[10]]], ignore_index=True)  # exact dup key
    con = _wh(tmp_path, bad, "dup.duckdb")
    with pytest.raises(AssertionError, match="duplicate"):
        warehouse.assert_warehouse(con)


def test_null_price_assertion_fires(tmp_path, make_panel):
    df = make_panel(3)
    df.loc[5, "price"] = np.nan
    con = _wh(tmp_path, df, "null.duckdb")
    with pytest.raises(AssertionError, match="NULL"):
        warehouse.assert_warehouse(con)


def test_price_out_of_bounds_assertion_fires(tmp_path, make_panel):
    df = make_panel(3)
    df.loc[5, "price"] = 1e9
    con = _wh(tmp_path, df, "oob.duckdb")
    with pytest.raises(AssertionError, match="outside"):
        warehouse.assert_warehouse(con)


def test_negative_mcpc_assertion_fires(tmp_path, make_panel):
    df = make_panel(3)
    df.loc[5, "RRS"] = -1.0
    con = _wh(tmp_path, df, "neg.duckdb")
    with pytest.raises(AssertionError, match="negative MCPC"):
        warehouse.assert_warehouse(con)


def test_over_96_intervals_assertion_fires(tmp_path, make_panel):
    """A day with > 96 intervals (bad parse / mislabelled intervals) must be
    fatal, distinct from a benign short day."""
    df = make_panel(1)  # 96 rows on one date
    d0 = df["date"].iloc[0]
    extra = df.iloc[:4].copy()
    extra["interval"] = [5, 6, 7, 8]          # unique keys, same date -> 100 rows
    extra["ts"] = df["ts"].iloc[-1] + pd.to_timedelta([15, 30, 45, 60], unit="min")
    extra["date"] = d0                         # keep them on day 0
    bad = pd.concat([df, extra], ignore_index=True)
    con = _wh(tmp_path, bad, "over.duckdb")
    with pytest.raises(AssertionError, match="> 96"):
        warehouse.assert_warehouse(con)


def test_clean_panel_has_no_gaps(tmp_path, make_panel):
    con = _wh(tmp_path, make_panel(3))
    stats = warehouse.assert_warehouse(con)
    assert stats["n_gaps"] == 0
    assert stats["total_missing_intervals"] == 0


def test_audit_gaps_finds_and_sizes_a_hole(tmp_path, make_panel):
    """Punch a 5-interval hole in the middle; the audit must find exactly one
    gap and count 5 missing intervals."""
    df = make_panel(3)
    df = df.drop(index=range(100, 105)).reset_index(drop=True)  # remove 5 interior rows
    con = _wh(tmp_path, df, "hole.duckdb")
    gaps = warehouse.audit_gaps(con)
    assert len(gaps) == 1
    assert gaps[0]["missing_intervals"] == 5
    assert gaps[0]["gap_minutes"] == 6 * 15  # 5 missing + 1 real step


def test_sub_interval_step_assertion_fires(tmp_path, make_panel):
    """A step SMALLER than one interval (time-axis misalignment / DST double-
    count) must be fatal — this is the check that guards the DST boundary."""
    df = make_panel(2, start="2026-01-05")  # rows at 02:30 and 02:45 exist
    extra = pd.DataFrame([{
        "ts": pd.Timestamp("2026-01-05 02:35:00"),  # 5-min sub-step between them
        "date": "2026-01-05", "hour": 3, "interval": 5,  # unique key
        "price": 30.0, "ECRS": 1.0, "NSPIN": 1.0, "REGDN": 1.0,
        "REGUP": 1.0, "RRS": 1.0, "settlement_point": "HB_NORTH",
    }])
    bad = pd.concat([df, extra], ignore_index=True)
    con = _wh(tmp_path, bad, "sub.duckdb")
    with pytest.raises(AssertionError, match="sub-15-minute"):
        warehouse.assert_warehouse(con)


def test_short_day_is_soft_not_fatal(tmp_path, make_panel):
    """A day with FEWER than 96 intervals is real ERCOT data (DST/outage) and
    must be reported, not fatal."""
    df = make_panel(3)
    df = df.iloc[:-5].reset_index(drop=True)  # drop 5 intervals from the last day
    con = _wh(tmp_path, df, "short.duckdb")
    stats = warehouse.assert_warehouse(con)   # must NOT raise
    assert stats["n_short_days"] == 1
    assert stats["short_days"][0][1] == 91


# --- real cached panel (local only) ---------------------------------------- #
@pytest.mark.skipif(not os.path.exists(REAL_PANEL), reason="cached panel not present (CI)")
def test_real_warehouse_builds_and_asserts(tmp_path):
    con = warehouse.build(db_path=str(tmp_path / "real.duckdb"))
    stats = warehouse.assert_warehouse(con)
    assert stats["n_rows"] > 18_000
    assert stats["n_days"] == 198
