"""
Stage 7 — the fleet DuckDB warehouse (schema + connection + dim rebuild).

DuckDB is an embedded, column-oriented analytical SQL database — it runs inside this Python
process (no server), stores everything in one file on disk, and is built for scanning/aggregating
many rows fast. We use it because the whole fleet-benchmark reconstruction is joins + group-bys
over millions of disclosure rows, which is exactly what SQL is for (plan §IX.4: "SQL as evidence,
not decoration"). This module owns the star schema; `src/disclosure_ingest.py` fills it.

Schema (star): two fact tables (RT SCED per-15-min, DA hourly), a per-day physical staging table,
a dimension table (one row per battery, with duration), and a manifest for resume-safe ingest.
"""

from __future__ import annotations

import duckdb

DEFAULT_PATH = "data/warehouse_fleet.duckdb"

# Upward AS products we track (RRS is the sum of its PFR/FFR/UFR sub-products).
AS_PRODUCTS = ["regup", "regdn", "rrs", "ecrs", "nspin"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fact_sced_esr (
    resource_name   VARCHAR,
    ts_15min        TIMESTAMP,
    telem_output_mw DOUBLE,      -- mean telemetered net output over the 15-min bin (>0 discharge)
    soc_mwh         DOUBLE,      -- state of charge at the bin
    as_regup_mw     DOUBLE, as_regdn_mw DOUBLE, as_rrs_mw DOUBLE,
    as_ecrs_mw      DOUBLE, as_nspin_mw DOUBLE
);

CREATE TABLE IF NOT EXISTS fact_dam_esr (
    resource_name       VARCHAR,
    delivery_date       DATE,
    hour_ending         INTEGER,
    da_energy_award_mw  DOUBLE,
    settlement_point    VARCHAR,
    da_spp              DOUBLE,      -- day-ahead settlement point price at the node
    da_regup_mw DOUBLE, da_regup_mcpc DOUBLE,
    da_regdn_mw DOUBLE, da_regdn_mcpc DOUBLE,
    da_rrs_mw   DOUBLE, da_rrs_mcpc   DOUBLE,
    da_ecrs_mw  DOUBLE, da_ecrs_mcpc  DOUBLE,
    da_nspin_mw DOUBLE, da_nspin_mcpc DOUBLE
);

-- one row per (battery, operating day): the physical parameters read off the SCED telemetry
CREATE TABLE IF NOT EXISTS stg_esr_physical (
    resource_name VARCHAR,
    operating_day DATE,
    hsl_mw        DOUBLE,       -- max sustained (discharge) limit
    max_soc_mwh   DOUBLE,
    min_soc_mwh   DOUBLE
);

-- one row per battery: physical params + node + derived duration (rebuilt from the facts)
CREATE TABLE IF NOT EXISTS dim_esr (
    resource_name    VARCHAR PRIMARY KEY,
    settlement_point VARCHAR,
    hsl_mw           DOUBLE,
    max_soc_mwh      DOUBLE,
    min_soc_mwh      DOUBLE,
    duration_h       DOUBLE
);

-- real-time settlement-point (node) prices, 15-min, for the ESR universe's nodes
CREATE TABLE IF NOT EXISTS prices_node (
    settlement_point VARCHAR,
    ts_15min         TIMESTAMP,
    rt_lmp           DOUBLE
);

-- resume bookkeeping: one row per downloaded archive bundle
CREATE TABLE IF NOT EXISTS manifest (
    docid         BIGINT,
    product       VARCHAR,
    operating_day DATE,
    rows          INTEGER,
    status        VARCHAR,
    fetched_at    VARCHAR
);
"""


def connect(path: str = DEFAULT_PATH) -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) the fleet warehouse and ensure the schema exists."""
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = duckdb.connect(path)
    con.execute(_SCHEMA)
    return con


def append(con, table: str, df) -> int:
    """Append a pandas DataFrame to a table by column name (order-independent)."""
    if df is None or len(df) == 0:
        return 0
    cols = [r[1] for r in con.execute(f"PRAGMA table_info('{table}')").fetchall()]  # r[1]=name (r[0]=cid)
    df = df[[c for c in cols if c in df.columns]]
    con.register("_incoming", df)
    con.execute(f"INSERT INTO {table} ({','.join(df.columns)}) SELECT {','.join(df.columns)} FROM _incoming")
    con.unregister("_incoming")
    return len(df)


def is_done(con, docid: int) -> bool:
    """Has this archive bundle already been ingested? (resume-safety)."""
    r = con.execute("SELECT 1 FROM manifest WHERE docid=? AND status='done' LIMIT 1", [docid]).fetchone()
    return r is not None


def mark(con, docid, product, operating_day, rows, status, fetched_at) -> None:
    con.execute("INSERT INTO manifest VALUES (?,?,?,?,?,?)",
                [docid, product, operating_day, rows, status, fetched_at])


def rebuild_dim_esr(con) -> int:
    """Rebuild dim_esr from the facts: physical params from the SCED staging (robust across
    resumed runs, since it reads the persisted facts), node from the DAM side, duration derived."""
    con.execute("DELETE FROM dim_esr")
    con.execute("""
        INSERT INTO dim_esr
        WITH phys AS (
            SELECT resource_name,
                   max(hsl_mw)      AS hsl_mw,
                   max(max_soc_mwh) AS max_soc_mwh,
                   min(min_soc_mwh) AS min_soc_mwh
            FROM stg_esr_physical GROUP BY resource_name
        ),
        node AS (   -- most-frequent settlement point per resource (guards rare relabels)
            SELECT resource_name, settlement_point FROM (
                SELECT resource_name, settlement_point,
                       row_number() OVER (PARTITION BY resource_name
                                          ORDER BY count(*) DESC) AS rk
                FROM fact_dam_esr WHERE settlement_point IS NOT NULL
                GROUP BY resource_name, settlement_point
            ) WHERE rk = 1
        )
        SELECT p.resource_name, n.settlement_point, p.hsl_mw, p.max_soc_mwh, p.min_soc_mwh,
               CASE WHEN p.hsl_mw > 0 THEN p.max_soc_mwh / p.hsl_mw END AS duration_h
        FROM phys p LEFT JOIN node n USING (resource_name)
    """)
    return con.execute("SELECT count(*) FROM dim_esr").fetchone()[0]


def summary(con) -> dict:
    """Quick warehouse census for smoke-checks."""
    q = lambda s: con.execute(s).fetchone()[0]
    return {
        "n_esr_dim": q("SELECT count(*) FROM dim_esr"),
        "sced_rows": q("SELECT count(*) FROM fact_sced_esr"),
        "dam_rows": q("SELECT count(*) FROM fact_dam_esr"),
        "days_done": q("SELECT count(DISTINCT operating_day) FROM manifest WHERE status='done'"),
        "sced_span": con.execute(
            "SELECT min(ts_15min), max(ts_15min) FROM fact_sced_esr").fetchone(),
    }
