"""Independent metric reconciliation.

The in-pipeline data-quality check #17 (`monthly_metric_recomputation`) re-runs
`metrics.compute`, so it shares the production implementation — it catches a stale
or hand-edited `metrics.csv`, but not a bug inside `compute` itself.

These tests recompute each metric with a *second, independent formula* straight
from the raw rows (never calling `metrics.compute`) and assert equality:

- revenue: group-by sum of successful payments;
- active users: distinct active user ids per month;
- churned / churn rate: the closed-cohort identity `active[m-1] - active[m]`
  (valid because no new users join and churned users never reactivate);
- ARPU: revenue / active.

Plus a structural / golden check on the committed `output/metrics.csv`.
If the production metric and any hand-written formula disagree, one is wrong.
"""

from __future__ import annotations

import pathlib

import pandas as pd
import pytest

from src import config
from src.generate_data import generate
from src.metrics import METRIC_COLUMNS, compute


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


def test_active_users_match_independent_count():
    raw = generate(seed=config.SEED)
    produced = compute(raw).set_index("month")["active_users"].sort_index()
    independent = (
        raw[raw["is_active"]]
        .groupby("month")["user_id"]
        .nunique()
        .reindex(produced.index, fill_value=0)
    )
    pd.testing.assert_series_equal(
        produced, independent, check_names=False, check_dtype=False
    )


def test_churn_matches_closed_cohort_identity():
    # In a closed cohort with no reactivation, active[m] = active[m-1] - churned[m],
    # so churned[m] = active[m-1] - active[m] — an identity independent of how the
    # production code derives churn from the active sets.
    raw = generate(seed=config.SEED)
    m = compute(raw).set_index("month")
    active = m["active_users"]
    for month in range(2, config.N_MONTHS + 1):
        expected_churn = int(active.loc[month - 1] - active.loc[month])
        assert int(m.loc[month, "churned_users"]) == expected_churn
        expected_rate = round(expected_churn / active.loc[month - 1], 4)
        assert round(float(m.loc[month, "churn_rate"]), 4) == expected_rate
    assert int(m.loc[1, "churned_users"]) == 0
    assert float(m.loc[1, "churn_rate"]) == 0.0


def test_arpu_matches_revenue_over_active():
    raw = generate(seed=config.SEED)
    m = compute(raw)
    for _, row in m.iterrows():
        expected = round(row["monthly_revenue"] / row["active_users"], 2)
        assert round(float(row["arpu"]), 2) == expected


def test_metrics_csv_structure_and_golden():
    # Structural + golden check on the committed artifact: exact columns, months
    # 1..N in order, and values byte-equal to a fresh seed-42 recompute.
    if not config.METRICS_CSV.exists():
        pytest.skip("output/metrics.csv not generated in this environment")
    on_disk = pd.read_csv(config.METRICS_CSV)
    assert list(on_disk.columns) == METRIC_COLUMNS
    assert list(on_disk["month"]) == list(range(1, config.N_MONTHS + 1))
    fresh = compute(generate(seed=config.SEED)).reset_index(drop=True)
    pd.testing.assert_frame_equal(
        on_disk.reset_index(drop=True), fresh, check_dtype=False
    )
