"""Data-quality checks and metric reconciliation.

Produces a machine-readable validation report (list of named checks + overall
status) that is consumed both by the reporting agent and by the final report.
"""

from __future__ import annotations

import json
import logging

import pandas as pd

from src import config
from src.generate_data import COLUMNS

logger = logging.getLogger(__name__)

_TOL = 0.01  # tolerance for float reconciliation


def _check(name: str, passed: bool, detail: str = "") -> dict:
    return {"check": name, "passed": bool(passed), "detail": detail}


def validate(df: pd.DataFrame, metrics: pd.DataFrame) -> dict:
    checks: list[dict] = []

    # 1. Schema
    checks.append(
        _check(
            "schema_columns",
            list(df.columns) == COLUMNS,
            f"expected {COLUMNS}, got {list(df.columns)}",
        )
    )

    # 2. No nulls in required fields
    null_cols = [c for c in df.columns if df[c].isna().any()]
    checks.append(_check("no_nulls", not null_cols, f"columns with nulls: {null_cols}"))

    # 3. Unique (user_id, month)
    dup = int(df.duplicated(["user_id", "month"]).sum())
    checks.append(_check("unique_user_month", dup == 0, f"{dup} duplicate pairs"))

    # 4. Exactly N_USERS unique users
    n_users = df["user_id"].nunique()
    checks.append(
        _check(
            "user_count",
            n_users == config.N_USERS,
            f"{n_users} unique users (expected {config.N_USERS})",
        )
    )

    # 5. Month range
    bad_month = df[(df["month"] < 1) | (df["month"] > config.N_MONTHS)]
    checks.append(
        _check("month_range", bad_month.empty, f"{len(bad_month)} out of range")
    )

    # 6. Plan -> price mapping
    expected_price = df["plan"].map(config.PLANS)
    bad_price = df[df["monthly_price"] != expected_price]
    checks.append(
        _check("plan_price_mapping", bad_price.empty, f"{len(bad_price)} mismatched")
    )

    # 7. paid => amount == price & active ; failed => amount == 0
    paid = df[df["payment_status"] == "paid"]
    bad_paid = paid[
        (paid["amount_paid"] != paid["monthly_price"]) | (~paid["is_active"])
    ]
    failed = df[df["payment_status"] == "failed"]
    bad_failed = failed[failed["amount_paid"] != 0]
    checks.append(
        _check(
            "payment_amount_consistency",
            bad_paid.empty and bad_failed.empty,
            f"{len(bad_paid)} bad paid, {len(bad_failed)} bad failed",
        )
    )

    # 8. Lapse rows: is_active=False => failed & amount 0
    inactive = df[~df["is_active"]]
    bad_inactive = inactive[
        (inactive["payment_status"] != "failed") | (inactive["amount_paid"] != 0)
    ]
    checks.append(
        _check("lapse_row_consistency", bad_inactive.empty, f"{len(bad_inactive)} bad")
    )

    # 9. Active users monotonically non-increasing (closed cohort)
    active = metrics["active_users"].tolist()
    non_increasing = all(active[i] >= active[i + 1] for i in range(len(active) - 1))
    checks.append(
        _check("active_users_non_increasing", non_increasing, f"series={active}")
    )

    # 10. paid_users <= active_users each month
    ok_paid_le_active = bool((metrics["paid_users"] <= metrics["active_users"]).all())
    checks.append(_check("paid_le_active", ok_paid_le_active))

    # 11. churn_rate within [0, 1]
    ok_churn_range = bool(
        ((metrics["churn_rate"] >= 0) & (metrics["churn_rate"] <= 1)).all()
    )
    checks.append(_check("churn_rate_range", ok_churn_range))

    # 12. Reconciliation: CSV revenue == sum of metric revenue
    csv_total = round(float(df["amount_paid"].sum()), 2)
    metric_total = round(float(metrics["monthly_revenue"].sum()), 2)
    checks.append(
        _check(
            "revenue_reconciliation",
            abs(csv_total - metric_total) < _TOL,
            f"csv={csv_total} vs metrics={metric_total}",
        )
    )

    # 13. ARPU recomputation
    recomputed_ok = True
    for _, r in metrics.iterrows():
        expected = (
            0.0 if r["active_users"] == 0 else r["monthly_revenue"] / r["active_users"]
        )
        if abs(round(expected, 2) - r["arpu"]) > _TOL:
            recomputed_ok = False
            break
    checks.append(_check("arpu_recomputation", recomputed_ok))

    # 14. payment_status domain
    bad_status = df[~df["payment_status"].isin(["paid", "failed"])]
    checks.append(
        _check("payment_status_domain", bad_status.empty, f"{len(bad_status)} bad")
    )

    # 15. No reactivation: each user's active months are contiguous from month 1
    #     (a churned user never comes back).
    reactivated = 0
    for _, g in df[df["is_active"]].groupby("user_id"):
        months = sorted(int(m) for m in g["month"])
        if months and months != list(range(months[0], months[0] + len(months))):
            reactivated += 1
    checks.append(
        _check("no_reactivation", reactivated == 0, f"{reactivated} reactivated users")
    )

    # 16. At most one lapse (is_active=False) row per user.
    lapses = df[~df["is_active"]].groupby("user_id").size()
    multi = int((lapses > 1).sum())
    checks.append(_check("single_lapse_per_user", multi == 0, f"{multi} multi-lapse"))

    # 17. Full recomputation: every monthly metric recomputed from raw must equal
    #     the provided metrics table. This proves the whole table is correct, not
    #     just the totals — guards against a stale or hand-edited metrics.csv.
    from src import metrics as metrics_mod

    recomputed = metrics_mod.compute(df).reset_index(drop=True)
    provided = metrics.reset_index(drop=True)
    if len(recomputed) != len(provided):
        mismatched = ["<row count differs>"]
    else:
        mismatched = [
            col
            for col in metrics_mod.METRIC_COLUMNS
            if not (
                abs(provided[col].to_numpy() - recomputed[col].to_numpy()) <= _TOL
            ).all()
        ]
    checks.append(
        _check(
            "monthly_metric_recomputation",
            not mismatched,
            f"mismatched columns: {mismatched}",
        )
    )

    overall = all(c["passed"] for c in checks)
    report = {
        "overall_passed": overall,
        "n_checks": len(checks),
        "n_failed": sum(1 for c in checks if not c["passed"]),
        "checks": checks,
    }
    logger.info(
        "Validation: %s (%d/%d passed)",
        "PASS" if overall else "FAIL",
        len(checks) - report["n_failed"],
        len(checks),
    )
    return report


def validate_to_json(df: pd.DataFrame, metrics: pd.DataFrame) -> dict:
    report = validate(df, metrics)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.VALIDATION_JSON.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("Wrote validation -> %s", config.VALIDATION_JSON)
    return report
