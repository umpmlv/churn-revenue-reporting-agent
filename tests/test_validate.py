"""Unit tests for data-quality validation, incl. the full-recompute guard."""

from __future__ import annotations

from src.generate_data import generate
from src.metrics import compute
from src.validate import validate


def test_clean_data_passes_all_checks():
    df = generate(seed=42)
    metrics = compute(df)
    report = validate(df, metrics)
    assert report["overall_passed"], report
    assert report["n_failed"] == 0


def test_tampered_metrics_caught_by_recomputation():
    """A hand-edited metrics table must fail the recomputation check."""
    df = generate(seed=42)
    metrics = compute(df)
    tampered = metrics.copy()
    tampered.loc[4, "active_users"] = int(tampered.loc[4, "active_users"]) + 5

    report = validate(df, tampered)
    assert not report["overall_passed"]
    failed = {c["check"] for c in report["checks"] if not c["passed"]}
    assert "monthly_metric_recomputation" in failed


def test_revenue_reconciliation_present():
    df = generate(seed=42)
    metrics = compute(df)
    report = validate(df, metrics)
    names = {c["check"] for c in report["checks"]}
    assert "revenue_reconciliation" in names
    assert "monthly_metric_recomputation" in names
