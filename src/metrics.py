"""Deterministic metric computation. This is the single source of numeric truth.

Definitions (also documented in README):
- active_users[m]   : users with is_active=True in month m.
- paid_users[m]     : users with payment_status='paid' in month m (a subset of active).
- churned_users[m]  : users who were active in m-1 but lapsed in m
                      (recorded as is_active=False rows). 0 for m=1 by definition.
- monthly_revenue[m]: sum of amount_paid in month m (only successful payments).
- churn_rate[m]     : churned_users[m] / active_users[m-1]; 0 for m=1.
- arpu[m]           : monthly_revenue[m] / active_users[m]; 0 if no active users.
"""

from __future__ import annotations

import logging

import pandas as pd

from src import config

logger = logging.getLogger(__name__)

METRIC_COLUMNS = [
    "month",
    "active_users",
    "paid_users",
    "churned_users",
    "monthly_revenue",
    "churn_rate",
    "arpu",
]


def compute(df: pd.DataFrame) -> pd.DataFrame:
    # Active user set per month — the basis for a churn definition that does not
    # depend on how a lapse is represented in the raw rows.
    active_sets: dict[int, set] = {
        month: set(df.loc[(df["month"] == month) & df["is_active"], "user_id"])
        for month in range(1, config.N_MONTHS + 1)
    }

    records: list[dict] = []
    for month in range(1, config.N_MONTHS + 1):
        sub = df[df["month"] == month]
        active_users = len(active_sets[month])
        paid_users = int((sub["payment_status"] == "paid").sum())
        # Churn = users active in m-1 who are no longer active in m. Zero for the
        # first month by definition (no prior period).
        churned_users = (
            0 if month == 1 else len(active_sets[month - 1] - active_sets[month])
        )
        monthly_revenue = float(sub["amount_paid"].sum())
        records.append(
            {
                "month": month,
                "active_users": active_users,
                "paid_users": paid_users,
                "churned_users": churned_users,
                "monthly_revenue": monthly_revenue,
            }
        )

    metrics = pd.DataFrame(records)
    prev_active = metrics["active_users"].shift(1)

    metrics["churn_rate"] = [
        0.0 if pd.isna(p) or p == 0 else c / p
        for c, p in zip(metrics["churned_users"], prev_active)
    ]
    metrics["arpu"] = [
        0.0 if a == 0 else r / a
        for r, a in zip(metrics["monthly_revenue"], metrics["active_users"])
    ]

    metrics["monthly_revenue"] = metrics["monthly_revenue"].round(2)
    metrics["churn_rate"] = metrics["churn_rate"].round(4)
    metrics["arpu"] = metrics["arpu"].round(2)

    logger.info("Computed metrics for %d months", len(metrics))
    return metrics[METRIC_COLUMNS]


def compute_to_csv(df: pd.DataFrame) -> pd.DataFrame:
    metrics = compute(df)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(config.METRICS_CSV, index=False)
    logger.info("Wrote metrics -> %s", config.METRICS_CSV)
    return metrics
