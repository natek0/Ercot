"""
Step 0 ingest (see docs/step0_spec.md section 4).

Two series at one settlement point:
  - Energy price: NP6-905-CD via the QUERY API (paginated, date-filtered).
  - RT ancillary MCPC: NP6-796-ER "Historical 15-min RTM MCPC" bulk bundles
    (one xlsx per year), read with the calamine engine because ERCOT's xlsx
    files omit standard metadata that openpyxl requires.

Raw pulls are cached under data/raw/ (gitignored) so re-runs are free.
"""

from __future__ import annotations

import io
import os
import zipfile

import pandas as pd
import requests

from src import ercot_api as api

RAW_DIR = "data/raw"
os.makedirs(RAW_DIR, exist_ok=True)
AS_TYPES = ["ECRS", "NSPIN", "REGDN", "REGUP", "RRS"]


def _headers():
    return {
        "Authorization": f"Bearer {api._current_token()}",
        "Ocp-Apim-Subscription-Key": api.PUBLIC_KEY,
    }


# --------------------------------------------------------------------------- #
# Energy price (query API)                                                     #
# --------------------------------------------------------------------------- #
def fetch_energy(date_from: str, date_to: str, settlement_point="HB_NORTH", cache=True) -> pd.DataFrame:
    fn = f"{RAW_DIR}/energy_{settlement_point}_{date_from}_{date_to}.parquet"
    if cache and os.path.exists(fn):
        return pd.read_parquet(fn)
    body = api.get_report(
        "/np6-905-cd/spp_node_zone_hub",
        {"deliveryDateFrom": date_from, "deliveryDateTo": date_to, "settlementPoint": settlement_point},
    )
    cols = [f["name"] for f in body["fields"]]
    df = pd.DataFrame(body["data"], columns=cols).rename(
        columns={"deliveryDate": "date", "deliveryHour": "hour",
                 "deliveryInterval": "interval", "settlementPointPrice": "price"}
    )
    df = df[["date", "hour", "interval", "price"]].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["hour"] = df["hour"].astype(int)
    df["interval"] = df["interval"].astype(int)
    df["price"] = df["price"].astype(float)
    if cache:
        df.to_parquet(fn)
    return df


# --------------------------------------------------------------------------- #
# RT MCPC (NP6-796-ER yearly xlsx bundles)                                     #
# --------------------------------------------------------------------------- #
def _archive_list(emil: str, size=100):
    r = api.request(f"/archive/{emil}", {"size": size})
    r.raise_for_status()
    return r.json()["archives"]


def _parse_mcpc_zip(zip_path: str) -> pd.DataFrame:
    """Return wide MCPC frame [date,hour,interval, ECRS,NSPIN,REGDN,REGUP,RRS].

    ERCOT's month sheets have title rows and NO text header, so we locate the
    data by content: find the column that holds ASType values, then read its
    neighbours by fixed offset (layout: date, hour, interval, ASType, MCPC, flag).
    """
    z = zipfile.ZipFile(zip_path)
    xb = z.read(z.namelist()[0])  # inner .xlsx
    xls = pd.ExcelFile(io.BytesIO(xb), engine="calamine")
    parts = []
    for sheet in [s for s in xls.sheet_names if s.lower() != "report info"]:
        raw = pd.read_excel(xls, sheet_name=sheet, engine="calamine", header=None)
        asmask = raw.apply(lambda col: col.astype(str).str.strip().isin(AS_TYPES))
        if not asmask.values.any():
            continue
        ai = int(asmask.sum(axis=0).idxmax())          # column holding ASType
        rows = asmask[ai]                               # data rows
        sub = raw.loc[rows, [ai - 3, ai - 2, ai - 1, ai, ai + 1]].copy()
        sub.columns = ["date", "hour", "interval", "ASType", "MCPC"]
        parts.append(sub)
    if not parts:
        raise RuntimeError(f"No ASType data rows found in {zip_path}")
    df = pd.concat(parts, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["hour"] = df["hour"].astype(int)
    df["interval"] = df["interval"].astype(int)
    df["ASType"] = df["ASType"].astype(str).str.strip()
    df["MCPC"] = pd.to_numeric(df["MCPC"], errors="coerce")
    df = df.dropna(subset=["MCPC"])
    wide = df.pivot_table(index=["date", "hour", "interval"], columns="ASType", values="MCPC").reset_index()
    wide.columns.name = None
    return wide


def fetch_mcpc(years=(2025, 2026), cache=True) -> pd.DataFrame:
    fn = f"{RAW_DIR}/mcpc_rtm_{min(years)}_{max(years)}.parquet"
    if cache and os.path.exists(fn):
        return pd.read_parquet(fn)
    archives = _archive_list("NP6-796-ER", size=100)
    frames = []
    for yr in years:
        cands = [a for a in archives if str(yr) in a["friendlyName"]]
        if not cands:
            print(f"  (no NP6-796-ER bundle for {yr})")
            continue
        doc = sorted(cands, key=lambda a: a["postDatetime"])[-1]  # latest posting
        raw_fn = f"{RAW_DIR}/NP6-796-ER_{yr}_{doc['docId']}.zip"
        if not os.path.exists(raw_fn):
            print(f"  downloading {yr} bundle (doc {doc['docId']})...")
            resp = requests.get(doc["_links"]["endpoint"]["href"], headers=_headers(), timeout=600)
            resp.raise_for_status()
            open(raw_fn, "wb").write(resp.content)
        frames.append(_parse_mcpc_zip(raw_fn))
    df = pd.concat(frames, ignore_index=True)
    if cache:
        df.to_parquet(fn)
    return df


# --------------------------------------------------------------------------- #
# Joined panel                                                                 #
# --------------------------------------------------------------------------- #
def dedup_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Drop exact-duplicate (date,hour,interval) rows, keeping the first.

    The source pull yields a handful of duplicated intervals (6 in the Dec-Jun
    window) — the energy query API occasionally repeats a row across a page
    boundary. We assert the duplicates are IDENTICAL across every value column
    before dropping, so a future CONFLICTING duplicate (a real data problem)
    raises instead of being silently discarded.
    """
    key = ["date", "hour", "interval"]
    vals = ["price"] + AS_TYPES
    dup = panel[panel.duplicated(key, keep=False)]
    if len(dup):
        conflicting = dup.groupby(key)[vals].nunique().gt(1).any(axis=1)
        if conflicting.any():
            bad = conflicting[conflicting].index.tolist()
            raise ValueError(
                f"Conflicting duplicate intervals (different values for the same "
                f"(date,hour,interval)) — investigate, do not silently drop: {bad[:10]}"
            )
    return panel.drop_duplicates(key, keep="first").reset_index(drop=True)


def build_panel(date_from: str, date_to: str, settlement_point="HB_NORTH",
                dedup: bool = True) -> pd.DataFrame:
    """Join energy + MCPC into one 15-minute panel.

    dedup=True (default, Stage 1 Option A) drops the 6 exact-duplicate intervals
    the source pull produces — a data-hygiene fix, not a parameter change, so it
    is consistent with the frozen pre-registration (which freezes the modelling
    PARAMETERS, not the raw pull). Stage 0's numbers were regenerated on the
    deduped panel; see the changelog in reports/step0_results.md. Pass
    dedup=False only to reproduce the pre-dedup historical numbers.
    """
    e = fetch_energy(date_from, date_to, settlement_point)
    years = tuple(sorted({int(date_from[:4]), int(date_to[:4])}))
    m = fetch_mcpc(years)
    panel = e.merge(m, on=["date", "hour", "interval"], how="inner")
    panel = panel[(panel["date"] >= date_from) & (panel["date"] <= date_to)].copy()
    panel["ts"] = pd.to_datetime(panel["date"]) + pd.to_timedelta(
        (panel["hour"] - 1) * 60 + (panel["interval"] - 1) * 15, unit="m"
    )
    panel = panel.sort_values("ts").reset_index(drop=True)
    if dedup:
        panel = dedup_panel(panel)
    return panel


if __name__ == "__main__":
    print("SMOKE TEST: 1 month (2025-12-05 .. 2026-01-04)")
    panel = build_panel("2025-12-05", "2026-01-04")
    print("panel shape:", panel.shape, "| cols:", list(panel.columns))
    counts = panel.groupby("date").size()
    print(f"intervals/day: min={counts.min()} max={counts.max()} median={counts.median()} (expect ~96)")
    print("\nprice + MCPC summary ($/MWh, $/MW-h):")
    print(panel[["price"] + AS_TYPES].describe().round(2).to_string())
    print("\nhead:")
    print(panel[["ts", "price"] + AS_TYPES].head(4).to_string())
