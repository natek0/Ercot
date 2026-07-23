"""
Stage 7 — 60-Day disclosure ingest (STREAM-AND-DISCARD, no bulk local storage).

For each operating day we download one daily zip bundle straight into memory (io.BytesIO, never
written to disk), extract ONLY the one ESR CSV we need, aggregate it to the compact rows the
warehouse keeps, append them to DuckDB, and let the ~48 MB blob be garbage-collected. Peak local
footprint is one zip in RAM plus the growing (small) warehouse — the ~10 GB of raw disclosure
flows through, it is never stored (plan reports/stage7_plan.md §3).

Layout mirrors the Stage 5 pure/IO split reviewers liked:
  * PURE parsers (`parse_sced_esr`, `parse_dam_esr`) — DataFrame in, tidy DataFrame(s) out; no
    network, no DuckDB → unit-tested on synthetic CSVs (tests/test_stage7.py).
  * IO (`fetch_zip`, `list_day_docids`, `ingest_window`) — the network + warehouse plumbing, with
    retry/backoff and manifest-based resume so a dropped ERCOT connection never restarts the pull.

    python -m src.disclosure_ingest --from 2026-05-18 --to 2026-05-24
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import time
import zipfile

import pandas as pd
import requests

from src import ercot_api, fleet_warehouse as fw

BASE = "https://api.ercot.com/api/public-reports"
SCED_PRODUCT, SCED_MEMBER = "NP3-965-ER", "ESR_Data_in_SCED"
DAM_PRODUCT, DAM_MEMBER = "NP3-966-ER", "DAM_ESR_Data"
LAG_DAYS = 60


# --------------------------------------------------------------------------- #
#  PURE parsers (no IO) — unit-tested
# --------------------------------------------------------------------------- #
def _num(s):
    return pd.to_numeric(s, errors="coerce")


def parse_sced_esr(raw: pd.DataFrame):
    """Raw 60d_ESR_Data_in_SCED rows → (df15, phys). df15 = per-battery 15-min facts (mean
    telemetered output, end-of-bin SOC, mean AS awards); phys = one physical-parameter row per
    battery for the day (HSL, Min/Max SOC). RRS = PFR+FFR+UFR."""
    df = raw[raw["Resource Type"] == "ESR"].copy()
    ts = pd.to_datetime(df["SCED Time Stamp"], format="%m/%d/%Y %H:%M:%S", errors="coerce")
    df = df[ts.notna()].copy()
    df["ts_15min"] = ts[ts.notna()].dt.floor("15min")
    df["telem"] = _num(df["Telemetered Net Output"])
    df["soc"] = _num(df["State of Charge"])
    df["hsl"] = _num(df["HSL"])
    df["maxsoc"] = _num(df["Maximum SOC"])
    df["minsoc"] = _num(df["Minimum SOC"])
    df["as_regup"] = _num(df["AS Awards REGUP"])
    df["as_regdn"] = _num(df["AS Awards REGDN"])
    df["as_rrs"] = (_num(df["AS Awards RRSPFR"]).fillna(0) + _num(df["AS Awards RRSFFR"]).fillna(0)
                    + _num(df["AS Awards RRSUFR"]).fillna(0))
    df["as_ecrs"] = _num(df["AS Awards ECRS"])
    df["as_nspin"] = _num(df["AS Awards NSPIN"])

    g = df.groupby(["Resource Name", "ts_15min"], as_index=False)
    df15 = g.agg(telem_output_mw=("telem", "mean"), soc_mwh=("soc", "last"),
                 as_regup_mw=("as_regup", "mean"), as_regdn_mw=("as_regdn", "mean"),
                 as_rrs_mw=("as_rrs", "mean"), as_ecrs_mw=("as_ecrs", "mean"),
                 as_nspin_mw=("as_nspin", "mean")).rename(columns={"Resource Name": "resource_name"})

    phys = (df.groupby("Resource Name", as_index=False)
              .agg(hsl_mw=("hsl", "max"), max_soc_mwh=("maxsoc", "max"), min_soc_mwh=("minsoc", "min"))
              .rename(columns={"Resource Name": "resource_name"}))
    phys["operating_day"] = df["ts_15min"].dt.date.mode().iloc[0] if len(df) else pd.NaT
    return df15, phys


def parse_dam_esr(raw: pd.DataFrame) -> pd.DataFrame:
    """Raw 60d_DAM_ESR_Data rows → per-battery hourly DA facts (energy award, node, DA price, and
    each AS award + its MCPC). RRS = PFR+FFR+UFR."""
    df = raw[raw.get("Resource Type", "ESR") == "ESR"].copy() if "Resource Type" in raw else raw.copy()
    return pd.DataFrame({
        "resource_name": df["Resource Name"].values,
        "delivery_date": pd.to_datetime(df["Delivery Date"], format="%m/%d/%Y", errors="coerce").dt.date,
        "hour_ending": _num(df["Hour Ending"]).astype("Int64"),
        "da_energy_award_mw": _num(df["Awarded Quantity"]),
        "settlement_point": df["Settlement Point Name"].values,
        "da_spp": _num(df["Energy Settlement Point Price"]),
        "da_regup_mw": _num(df["RegUp Awarded"]), "da_regup_mcpc": _num(df["RegUp MCPC"]),
        "da_regdn_mw": _num(df["RegDown Awarded"]), "da_regdn_mcpc": _num(df["RegDown MCPC"]),
        "da_rrs_mw": (_num(df["RRSPFR Awarded"]).fillna(0) + _num(df["RRSFFR Awarded"]).fillna(0)
                      + _num(df["RRSUFR Awarded"]).fillna(0)),
        "da_rrs_mcpc": _num(df["RRS MCPC"]),
        "da_ecrs_mw": _num(df["ECRSSD Awarded"]), "da_ecrs_mcpc": _num(df["ECRS MCPC"]),
        "da_nspin_mw": _num(df["NonSpin Awarded"]), "da_nspin_mcpc": _num(df["NonSpin MCPC"]),
    })


# --------------------------------------------------------------------------- #
#  IO — archive listing, streaming download, ingest loop
# --------------------------------------------------------------------------- #
def _hdr():
    import os
    return {"Authorization": f"Bearer {ercot_api._current_token()}",
            "Ocp-Apim-Subscription-Key": os.getenv("ERCOT_PUBLIC_API_SUBSCRIPTION_KEY")}


def _get(path, params=None, timeout=120, retries=4):
    for i in range(retries):
        try:
            r = requests.get(BASE + path, headers=_hdr(), params=params or {}, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code in (401, 403):
                ercot_api._TOKEN_CACHE["token"] = None      # force token refresh, retry
        except requests.RequestException:
            pass
        time.sleep(2 ** i)
    raise RuntimeError(f"GET {path} failed after {retries} tries")


def list_day_docids(product: str, op_from: dt.date, op_to: dt.date, pad_days: int = 4) -> dict:
    """Map operating_day → latest docId for `product` over [op_from, op_to]. Operating day ≈
    postDatetime − 60 days; we scan the DESC-sorted archive listing and stop once we pass below the
    window. Keeps the FIRST docId seen per day (latest post = the final rerun)."""
    out: dict[dt.date, int] = {}
    page = 1
    while page <= 200:
        arch = _get(f"/archive/{product}", params={"size": 1000, "page": page}).json().get("archives", [])
        if not arch:
            break
        for a in arch:
            post = pd.to_datetime(a["postDatetime"]).date()
            opday = post - dt.timedelta(days=LAG_DAYS)
            if opday < op_from - dt.timedelta(days=pad_days):
                return out                                   # DESC → everything below is older
            if op_from <= opday <= op_to and opday not in out:
                out[opday] = a["docId"]
        page += 1
    return out


def fetch_zip(product: str, docid: int, timeout: int = 300, retries: int = 4) -> bytes:
    """Download one daily bundle into memory (bytes). Retries with backoff on ERCOT flakiness."""
    for i in range(retries):
        try:
            r = requests.get(f"{BASE}/archive/{product}?download={docid}", headers=_hdr(), timeout=timeout)
            if r.status_code == 200:
                return r.content
            if r.status_code in (401, 403):
                ercot_api._TOKEN_CACHE["token"] = None
        except requests.RequestException:
            pass
        time.sleep(2 ** i)
    raise RuntimeError(f"download {product} doc {docid} failed after {retries} tries")


def read_member(zip_bytes: bytes, substr: str) -> pd.DataFrame:
    """Extract the one inner CSV whose name contains `substr` (in memory) → DataFrame of strings."""
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    name = next(n for n in z.namelist() if substr.lower() in n.lower())
    with z.open(name) as fh:
        return pd.read_csv(fh, dtype=str, low_memory=False)


def _ingest_product(con, product, member, parser, docids, verbose=True):
    now = dt.datetime.now().isoformat(timespec="seconds")
    for opday, docid in sorted(docids.items()):
        if fw.is_done(con, docid):
            continue
        try:
            raw = read_member(fetch_zip(product, docid), member)
            if product == SCED_PRODUCT:
                df15, phys = parser(raw)
                n = fw.append(con, "fact_sced_esr", df15)
                fw.append(con, "stg_esr_physical", phys)
            else:
                dfh = parser(raw)
                n = fw.append(con, "fact_dam_esr", dfh)
            fw.mark(con, docid, product, opday, n, "done", now)
            if verbose:
                print(f"  [{product}] {opday} doc {docid}: {n:,} rows")
        except Exception as e:                               # noqa: BLE001
            fw.mark(con, docid, product, opday, 0, f"error:{type(e).__name__}", now)
            print(f"  [{product}] {opday} doc {docid}: ERROR {e}")


def ingest_window(op_from, op_to, path=fw.DEFAULT_PATH, rebuild_dim=True, verbose=True):
    """Ingest both disclosures over [op_from, op_to] into the fleet warehouse (resume-safe)."""
    op_from = pd.to_datetime(op_from).date()
    op_to = pd.to_datetime(op_to).date()
    con = fw.connect(path)
    if verbose:
        print(f"Auth..."); ercot_api._current_token(); print("token OK")
    sced = list_day_docids(SCED_PRODUCT, op_from, op_to)
    dam = list_day_docids(DAM_PRODUCT, op_from, op_to)
    print(f"archive listing: {len(sced)} SCED days, {len(dam)} DAM days in [{op_from}, {op_to}]")
    _ingest_product(con, SCED_PRODUCT, SCED_MEMBER, parse_sced_esr, sced, verbose)
    _ingest_product(con, DAM_PRODUCT, DAM_MEMBER, parse_dam_esr, dam, verbose)
    if rebuild_dim:
        n = fw.rebuild_dim_esr(con)
        print(f"rebuilt dim_esr: {n} batteries")
    print("summary:", fw.summary(con))
    con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="op_from", required=True)
    ap.add_argument("--to", dest="op_to", required=True)
    ap.add_argument("--db", default=fw.DEFAULT_PATH)
    a = ap.parse_args()
    ingest_window(a.op_from, a.op_to, path=a.db)


if __name__ == "__main__":
    main()
