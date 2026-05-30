"""Unit tests for metric computation, including churn edge cases."""

from __future__ import annotations

import pandas as pd
import pytest

from src import config
from src.generate_data import COLUMNS, generate
from src.metrics import compute


@pytest.fixture
def tiny_cohort() -> pd.DataFrame:
    """Three users over the first two months, with one churn and one failed pay.

    - u1: pays both months, stays active.
    - u2: pays month 1, lapses into month 2 (is_active=False row).
    - u3: failed payment in month 1 (active, $0), pays month 2.
    """
    rows = [
        (1, 1, "basic", 10.0, "paid", 10.0, True),
        (1, 2, "basic", 10.0, "paid", 10.0, True),
        (2, 1, "basic", 10.0, "paid", 10.0, True),
        (2, 2, "basic", 10.0, "failed", 0.0, False),  # lapse event
        (3, 1, "basic", 10.0, "failed", 0.0, True),  # active but charge failed
        (3, 2, "basic", 10.0, "paid", 10.0, True),
    ]
    return pd.DataFrame(rows, columns=COLUMNS)


def test_month1_has_zero_churn(tiny_cohort):
    m = compute(tiny_cohort).set_index("month")
    assert m.loc[1, "churned_users"] == 0
    assert m.loc[1, "churn_rate"] == 0.0


def test_month1_counts_and_revenue(tiny_cohort):
    m = compute(tiny_cohort).set_index("month")
    assert m.loc[1, "active_users"] == 3  # all three are active
    assert m.loc[1, "paid_users"] == 2  # u3 failed
    assert m.loc[1, "monthly_revenue"] == 20.0
    assert m.loc[1, "arpu"] == round(20.0 / 3, 2)  # per active user, incl. failed


def test_month2_churn_and_arpu(tiny_cohort):
    m = compute(tiny_cohort).set_index("month")
    assert m.loc[2, "active_users"] == 2  # u1, u3
    assert m.loc[2, "churned_users"] == 1  # u2 lapsed
    assert m.loc[2, "churn_rate"] == round(1 / 3, 4)  # 1 churned / 3 prior active
    assert m.loc[2, "monthly_revenue"] == 20.0
    assert m.loc[2, "arpu"] == 10.0


def test_zero_active_denominator_is_safe(tiny_cohort):
    """Empty later months must not divide by zero."""
    m = compute(tiny_cohort).set_index("month")
    assert m.loc[config.N_MONTHS, "active_users"] == 0
    assert m.loc[config.N_MONTHS, "arpu"] == 0.0
    assert m.loc[config.N_MONTHS, "churn_rate"] == 0.0


def test_closed_cohort_identity():
    """active[m-1] == active[m] + churned[m] for every month, on the real cohort."""
    m = compute(generate(seed=42)).set_index("month")
    for month in range(2, config.N_MONTHS + 1):
        assert m.loc[month - 1, "active_users"] == (
            m.loc[month, "active_users"] + m.loc[month, "churned_users"]
        )
