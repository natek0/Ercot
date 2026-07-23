"""
Stage 7 — node price ingest. Each ESR settles energy at its OWN resource-node RT LMP (not the
hub), so realized energy revenue and each asset's perfect-foresight ceiling must be priced on the
asset's node. We pull NP6-905-CD (the queryable settlement-point-price API, reusing
`ingest.fetch_energy`) for the distinct nodes in `dim_esr` over the window, into `prices_node`.

Runs AFTER the disclosure ingest (dim_esr must exist so we know which nodes to fetch). DuckDB is
single-writer, so this and the disclosure ingest run sequentially, not concurrently.

    python -m src.fleet_prices --from 2025-12-05 --to 2026-05-24
"""

from __future__ import annotations

import argparse

import pandas as pd

from src import ercot_api as api
from src import fleet_warehouse as fw


def _to_ts15(df: pd.DataFrame) -> pd.DataFrame:
    """ERCOT (date, hour-ending 1..24, interval 1..4) → interval-BEGINNING 15-min timestamp."""
    ts = (pd.to_datetime(df["date"])
          + pd.to_timedelta(df["hour"].astype(int) - 1, unit="h")
          + pd.to_timedelta((df["interval"].astype(int) - 1) * 15, unit="m"))
    return pd.DataFrame({"ts_15min": ts, "rt_lmp": df["price"].astype(float)})


def fetch_one_node(sp: str, date_from: str, date_to: str, page_size: int = 100000) -> pd.DataFrame:
    """Node RT price series for one settlement point → (settlement_point, ts_15min, rt_lmp).
    Uses a LARGE page size so the whole window arrives in one request (a full window is ~16k rows),
    which keeps us far under ERCOT's per-request rate limit — the default 1000-row paging turned one
    node into ~17 requests and exhausted the quota."""
    body = api.get_report(
        "/np6-905-cd/spp_node_zone_hub",
        {"deliveryDateFrom": date_from, "deliveryDateTo": date_to, "settlementPoint": sp},
        page_size=page_size,
    )
    cols = [f["name"] for f in body["fields"]]
    df = pd.DataFrame(body["data"], columns=cols).rename(columns={
        "deliveryDate": "date", "deliveryHour": "hour",
        "deliveryInterval": "interval", "settlementPointPrice": "price"})
    out = _to_ts15(df[["date", "hour", "interval", "price"]])
    out.insert(0, "settlement_point", sp)
    return out


def ingest_node_prices(date_from, date_to, path=fw.DEFAULT_PATH, nodes=None, verbose=True):
    """Fetch RT prices for every node in dim_esr (or an explicit `nodes` list) over the window."""
    con = fw.connect(path)
    if nodes is None:
        nodes = [r[0] for r in con.execute(
            "SELECT DISTINCT settlement_point FROM dim_esr WHERE settlement_point IS NOT NULL").fetchall()]
    done = {r[0] for r in con.execute("SELECT DISTINCT settlement_point FROM prices_node").fetchall()}
    todo = [n for n in nodes if n not in done]
    print(f"node prices: {len(nodes)} nodes, {len(todo)} to fetch, window [{date_from},{date_to}]")
    done_n = len(done)
    ok = 0
    for i, sp in enumerate(todo):
        try:
            df = fetch_one_node(sp, date_from, date_to)
            n = fw.append(con, "prices_node", df)
            ok += 1; done_n += 1
            if verbose and (i % 25 == 0 or n == 0):
                print(f"  [{i+1}/{len(todo)}] {sp}: {n} rows", flush=True)
        except Exception as e:                              # noqa: BLE001
            print(f"  {sp}: SKIP ({type(e).__name__}: {e})", flush=True)
        if i % 10 == 0:
            fw.write_status(f"Stage 7 NODE-PRICE ingest\n  nodes: {done_n}/{len(nodes)} fetched\n"
                            f"  last: {sp}\n  in progress...")
        __import__("time").sleep(0.25)                     # proactive pacing under the rate limit
    fw.write_status(f"Stage 7 NODE-PRICE ingest\n  nodes: {done_n}/{len(nodes)} fetched\n"
                    f"  >>> COMPLETE — next: python -m src.stage7_run")
    print(f"done: {ok}/{len(todo)} nodes fetched; "
          f"prices_node now {con.execute('SELECT count(*) FROM prices_node').fetchone()[0]:,} rows")
    con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--to", dest="date_to", required=True)
    ap.add_argument("--db", default=fw.DEFAULT_PATH)
    a = ap.parse_args()
    ingest_node_prices(a.date_from, a.date_to, path=a.db)


if __name__ == "__main__":
    main()
