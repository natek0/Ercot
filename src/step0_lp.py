"""
Stage 0 compatibility shim.

The Stage 0 perfect-foresight LP was generalised into the reusable oracle in
`src/oracle.py` during Stage 1. This module re-exports the Stage 0 names so
`src/step0_run.py` and any existing references keep working unchanged. New code
should import from `src.oracle` directly.
"""

from __future__ import annotations

from src.oracle import (  # noqa: F401
    ALL_PRODUCTS,
    CONTINGENCY,
    ENERGY_ONLY,
    BatteryParams,
    OracleResult,
    Params,
    binding_diagnostics,
    diagnostics,
    duration_identity,
    solve,
    solve_lp,
    synthetic_prices,
    verification,
    verify,
)

# Old private helper name, kept in case anything imported it.
_synthetic = synthetic_prices
