"""Shared test fixtures.

Everything here is synthetic and in-memory so the suite runs in CI with no
ERCOT credentials and no cached data. Tests that DO use the real cached panel
are guarded with skipif on the parquet file's existence.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

AS_TYPES = ["ECRS", "NSPIN", "REGDN", "REGUP", "RRS"]


def _make_panel(n_days: int = 8, start: str = "2026-01-05", sp: str = "HB_NORTH") -> pd.DataFrame:
    """A clean synthetic warehouse panel: n_days full 96-interval days, no gaps,
    no DST (January), deterministic diurnal price. Matches the schema
    warehouse.build(panel=...) expects."""
    n = n_days * 96
    ts = pd.date_range(start, periods=n, freq="15min")
    q = np.arange(n) % 96  # quarter-of-day 0..95
    price = 30.0 + 20.0 * np.sin(q / 96 * 2 * np.pi) + 15.0 * ((q > 68) & (q < 80))
    df = pd.DataFrame({"ts": ts})
    df["date"] = df["ts"].dt.strftime("%Y-%m-%d")
    df["hour"] = df["ts"].dt.hour + 1           # ERCOT hour-ending 1..24
    df["interval"] = df["ts"].dt.minute // 15 + 1  # 1..4
    df["price"] = price
    for k in AS_TYPES:
        df[k] = 1.0
    df["settlement_point"] = sp
    return df


@pytest.fixture
def make_panel():
    return _make_panel
