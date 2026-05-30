"""Deterministic synthetic data generator for a closed subscription cohort.

Model: 1000 users acquired in month 1, followed for 12 months.
- Each user gets a fixed plan (basic/plus/premium) at onboarding.
- While active, each month a payment is attempted: `paid` or (rarely) `failed`.
- A monthly churn hazard decides whether the user lapses into the next month.
  A failed payment raises that hazard (involuntary churn).
- Churn is recorded as a single row in the lapse month with `is_active=False`
  (a `failed` payment that ends the subscription). No rows after that.

This makes every column load-bearing and keeps `payment_status` in {paid, failed}.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from src import config

logger = logging.getLogger(__name__)

COLUMNS = [
    "user_id",
    "month",
    "plan",
    "monthly_price",
    "payment_status",
    "amount_paid",
    "is_active",
]


def generate(seed: int = config.SEED) -> pd.DataFrame:
    """Generate the synthetic subscription panel. Fully determined by `seed`."""
    rng = np.random.default_rng(seed)
    plans = list(config.PLANS)
    weights = [config.PLAN_WEIGHTS[p] for p in plans]
    user_plans = rng.choice(plans, size=config.N_USERS, p=weights)

    rows: list[tuple] = []
    for idx in range(config.N_USERS):
        user_id = idx + 1
        plan = str(user_plans[idx])
        price = config.PLANS[plan]
        active = True

        for month in range(1, config.N_MONTHS + 1):
            if not active:
                break

            # Active subscription month: attempt a payment.
            failed = rng.random() < config.P_PAYMENT_FAIL
            status = "failed" if failed else "paid"
            amount = 0.0 if failed else price
            rows.append((user_id, month, plan, price, status, amount, True))

            # Decide churn into the next month (cannot churn past the window).
            if month < config.N_MONTHS:
                hazard = config.churn_hazard(month)
                if failed:
                    hazard = min(1.0, hazard * config.FAILED_PAYMENT_CHURN_MULT)
                if rng.random() < hazard:
                    active = False
                    # Lapse event: a failed renewal that ends the subscription.
                    rows.append((user_id, month + 1, plan, price, "failed", 0.0, False))

    df = pd.DataFrame(rows, columns=COLUMNS)
    df = df.sort_values(["user_id", "month"]).reset_index(drop=True)
    logger.info(
        "Generated %d rows for %d users over %d months",
        len(df),
        config.N_USERS,
        config.N_MONTHS,
    )
    return df


def generate_to_csv(seed: int = config.SEED) -> pd.DataFrame:
    df = generate(seed)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(config.DATA_CSV, index=False)
    logger.info("Wrote synthetic data -> %s", config.DATA_CSV)
    return df
