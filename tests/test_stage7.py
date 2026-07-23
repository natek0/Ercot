"""
Stage 7 — tests for the disclosure ingest (pure parsers + warehouse plumbing).

The parsers are PURE (raw DataFrame in → tidy DataFrame out; no network, no DuckDB), so we test
them on synthetic ERCOT-shaped rows with known answers — CI-safe, no ESR credentials, no download.
The warehouse tests use an in-memory DuckDB. Includes a regression test for the append() column-
name bug (PRAGMA table_info row[0] is the column id, not the name) found during the A0 build.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src import disclosure_ingest as di
from src import fleet_warehouse as fw


# --------------------------------------------------------------------------- #
#  Synthetic ERCOT-shaped raw rows
# --------------------------------------------------------------------------- #
def _sced_raw():
    """Two ESRs, three 5-min SCED rows in the 00:00 15-min bin + one in 00:15, all as strings."""
    def row(ts, name, out, soc, hsl, mx, mn, pfr=0, ffr=0, ufr=0, ecrs=0, nspin=0, regup=0, regdn=0):
        return {"Resource Type": "ESR", "SCED Time Stamp": ts, "Resource Name": name,
                "Telemetered Net Output": str(out), "State of Charge": str(soc), "HSL": str(hsl),
                "Maximum SOC": str(mx), "Minimum SOC": str(mn),
                "AS Awards RRSPFR": str(pfr), "AS Awards RRSFFR": str(ffr), "AS Awards RRSUFR": str(ufr),
                "AS Awards ECRS": str(ecrs), "AS Awards NSPIN": str(nspin),
                "AS Awards REGUP": str(regup), "AS Awards REGDN": str(regdn)}
    # AS awards are constant across the SCED runs within an hour (as in real data), so all three
    # rows of the 00:00 bin carry the same RRS legs; the 15-min mean of the sum is then 6.
    rows = [
        row("05/24/2026 00:00:17", "A_ESR1", 10, 20, 30, 40, 0, pfr=1, ffr=2, ufr=3),  # RRS=6
        row("05/24/2026 00:05:20", "A_ESR1", 20, 21, 30, 40, 0, pfr=1, ffr=2, ufr=3),
        row("05/24/2026 00:10:11", "A_ESR1", 30, 22, 30, 40, 0, pfr=1, ffr=2, ufr=3),  # mean out=20, last soc=22
        row("05/24/2026 00:15:09", "A_ESR1", -8, 25, 30, 40, 0),                        # next bin
        row("05/24/2026 00:00:30", "B_ESR1", 5, 10, 12, 20, 1, ecrs=4, nspin=5),
        # a non-ESR row that must be dropped:
        {"Resource Type": "PWRSTR", "SCED Time Stamp": "05/24/2026 00:00:00", "Resource Name": "X",
         "Telemetered Net Output": "999", "State of Charge": "0", "HSL": "0", "Maximum SOC": "0",
         "Minimum SOC": "0", "AS Awards RRSPFR": "0", "AS Awards RRSFFR": "0", "AS Awards RRSUFR": "0",
         "AS Awards ECRS": "0", "AS Awards NSPIN": "0", "AS Awards REGUP": "0", "AS Awards REGDN": "0"},
    ]
    return pd.DataFrame(rows)


def _dam_raw():
    def row(name, he, award, sp, price, pfr=0, ffr=0, ufr=0, ecrs=0, nspin=0):
        return {"Resource Type": "ESR", "Resource Name": name, "Delivery Date": "05/24/2026",
                "Hour Ending": str(he), "Awarded Quantity": str(award), "Settlement Point Name": sp,
                "Energy Settlement Point Price": str(price),
                "RegUp Awarded": "0", "RegUp MCPC": "0", "RegDown Awarded": "0", "RegDown MCPC": "0",
                "RRSPFR Awarded": str(pfr), "RRSFFR Awarded": str(ffr), "RRSUFR Awarded": str(ufr),
                "RRS MCPC": "5", "ECRSSD Awarded": str(ecrs), "ECRS MCPC": "7",
                "NonSpin Awarded": str(nspin), "NonSpin MCPC": "3"}
    return pd.DataFrame([row("A_ESR1", 1, -1.0, "A_RN", 25.0, ffr=6),
                         row("A_ESR1", 2, 5.0, "A_RN", 30.0, nspin=4)])


# --------------------------------------------------------------------------- #
#  Pure parser tests
# --------------------------------------------------------------------------- #
def test_parse_sced_drops_non_esr_and_bins_to_15min():
    df15, phys = di.parse_sced_esr(_sced_raw())
    assert "X" not in set(phys["resource_name"])          # non-ESR dropped
    a0 = df15[(df15.resource_name == "A_ESR1") & (df15.ts_15min == pd.Timestamp("2026-05-24 00:00"))].iloc[0]
    assert a0.telem_output_mw == pytest.approx(20.0)      # mean of 10,20,30
    assert a0.soc_mwh == pytest.approx(22.0)              # last in the bin
    assert a0.as_rrs_mw == pytest.approx(6.0)             # PFR+FFR+UFR = 1+2+3
    # two 15-min bins for A_ESR1 (00:00 and 00:15) + one for B_ESR1
    assert len(df15) == 3


def test_parse_sced_physical_params():
    _, phys = di.parse_sced_esr(_sced_raw())
    a = phys[phys.resource_name == "A_ESR1"].iloc[0]
    assert (a.hsl_mw, a.max_soc_mwh, a.min_soc_mwh) == (30.0, 40.0, 0.0)  # HSL=30, MaxSOC=40, MinSOC=0
    assert phys["operating_day"].iloc[0] == pd.Timestamp("2026-05-24").date()


def test_parse_dam_columns_and_rrs_sum():
    dfh = di.parse_dam_esr(_dam_raw())
    assert list(dfh.columns) == ["resource_name", "delivery_date", "hour_ending",
        "da_energy_award_mw", "settlement_point", "da_spp", "da_regup_mw", "da_regup_mcpc",
        "da_regdn_mw", "da_regdn_mcpc", "da_rrs_mw", "da_rrs_mcpc", "da_ecrs_mw", "da_ecrs_mcpc",
        "da_nspin_mw", "da_nspin_mcpc"]
    h1 = dfh[dfh.hour_ending == 1].iloc[0]
    assert h1.da_rrs_mw == pytest.approx(6.0) and h1.settlement_point == "A_RN"
    assert h1.da_spp == pytest.approx(25.0) and h1.da_energy_award_mw == pytest.approx(-1.0)


# --------------------------------------------------------------------------- #
#  Warehouse plumbing tests
# --------------------------------------------------------------------------- #
def test_append_matches_by_column_NAME_not_id():
    """Regression: append must map DataFrame columns to table columns by NAME. The original bug
    used PRAGMA table_info row[0] (the integer column id), which matched nothing and silently
    dropped every column. Here we append a df whose columns are REORDERED + have an extra column."""
    con = fw.connect(":memory:")
    df = pd.DataFrame({"soc_mwh": [1.0], "extra_ignored": [9], "resource_name": ["Z_ESR1"],
                       "ts_15min": [pd.Timestamp("2026-05-24 00:00")]})
    n = fw.append(con, "fact_sced_esr", df)
    assert n == 1
    got = con.execute("SELECT resource_name, soc_mwh FROM fact_sced_esr").fetchone()
    assert got == ("Z_ESR1", 1.0)


def test_rebuild_dim_derives_duration_and_node():
    con = fw.connect(":memory:")
    fw.append(con, "stg_esr_physical", pd.DataFrame({
        "resource_name": ["A_ESR1", "A_ESR1"], "operating_day": [pd.Timestamp("2026-05-23").date(),
        pd.Timestamp("2026-05-24").date()], "hsl_mw": [10.0, 10.0], "max_soc_mwh": [20.0, 25.0],
        "min_soc_mwh": [0.0, 0.0]}))
    fw.append(con, "fact_dam_esr", pd.DataFrame({
        "resource_name": ["A_ESR1", "A_ESR1"], "delivery_date": [pd.Timestamp("2026-05-24").date()] * 2,
        "hour_ending": [1, 2], "settlement_point": ["A_RN", "A_RN"]}))
    n = fw.rebuild_dim_esr(con)
    assert n == 1
    d = con.execute("SELECT settlement_point, hsl_mw, max_soc_mwh, duration_h FROM dim_esr").fetchone()
    assert d[0] == "A_RN" and d[1] == 10.0 and d[2] == 25.0          # max over days
    assert d[3] == pytest.approx(2.5)                                 # 25 / 10


def test_manifest_resume_marks_done():
    con = fw.connect(":memory:")
    assert not fw.is_done(con, 123)
    fw.mark(con, 123, "NP3-965-ER", pd.Timestamp("2026-05-24").date(), 100, "done", "now")
    assert fw.is_done(con, 123)
