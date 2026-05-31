"""Independent revenue reconciliation.

The in-pipeline data-quality check #17 (`monthly_metric_recomputation`) re-runs
`metrics.compute`, so it shares the production implementation — it catches a stale
or hand-edited `metrics.csv`, but not a bug inside `compute` itself.

This test computes monthly revenue with a *second, independent formula* — a plain
group-by sum of successful payments straight from the raw rows, without calling
`metrics.compute` — and asserts it equals the production metric. If the metric
implementation and this hand-written sum ever disagree, one of them is wrong.
"""

from __future__ import annotations

import pandas as pd

from src import config
from src.generate_data import generate
from src.metrics import compute


def _independent_monthly_revenue(raw: pd.DataFrame) -> pd.Series:
    """Monthly revenue = Σ amount_paid of successful payments, computed directly
    from the raw rows (no use of metrics.compute)."""
    paid = raw[raw["payment_status"] == "paid"]
    return paid.groupby("month")["amount_paid"].sum().round(2).sort_index()


def test_monthly_revenue_matches_independent_sum():
    raw = generate(seed=config.SEED)
    produced = compute(raw).set_index("month")["monthly_revenue"].sort_index()
    independent = _independent_monthly_revenue(raw).reindex(
        produced.index, fill_value=0.0
    )
    pd.testing.assert_series_equal(
        produced, independent, check_names=False, check_dtype=False
    )


def test_total_revenue_matches_independent_sum():
    raw = generate(seed=config.SEED)
    produced_total = round(float(compute(raw)["monthly_revenue"].sum()), 2)
    independent_total = round(
        float(raw.loc[raw["payment_status"] == "paid", "amount_paid"].sum()), 2
    )
    assert produced_total == independent_total
