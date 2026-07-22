"""Ingest dedup-hardening tests (no network — operate on small DataFrames)."""

from __future__ import annotations

import pandas as pd
import pytest

from src import ingest


def _rows(n=6):
    df = pd.DataFrame({
        "date": ["2026-01-05"] * n,
        "hour": list(range(1, n + 1)),
        "interval": [1] * n,
        "price": [10.0 + i for i in range(n)],
    })
    for k in ingest.AS_TYPES:
        df[k] = 1.0
    return df


def test_dedup_drops_exact_duplicate():
    df = _rows(4)
    dup = pd.concat([df, df.iloc[[1]]], ignore_index=True)  # exact-duplicate row
    out = ingest.dedup_panel(dup)
    assert len(out) == 4
    assert out.duplicated(["date", "hour", "interval"]).sum() == 0


def test_dedup_passes_through_clean():
    df = _rows(5)
    out = ingest.dedup_panel(df)
    assert len(out) == 5


def test_dedup_raises_on_conflicting_duplicate():
    """Same key, DIFFERENT value = a real data problem, must raise, not drop."""
    df = _rows(4)
    conflict = df.iloc[[1]].copy()
    conflict["price"] = 999.0  # same (date,hour,interval), different price
    bad = pd.concat([df, conflict], ignore_index=True)
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        ingest.dedup_panel(bad)
