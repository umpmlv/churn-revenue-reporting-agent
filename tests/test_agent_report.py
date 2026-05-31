"""Unit tests for the report number-guardrail (deterministic, no API needed)."""

from __future__ import annotations

import pytest

from src.agent_report import (
    _enforce_check_count,
    check_report_numbers,
    compute_highlights,
    template_report,
)
from src.generate_data import generate
from src.metrics import compute

_CLEAN_VALIDATION = {
    "overall_passed": True,
    "n_checks": 14,
    "n_failed": 0,
    "checks": [],
}


@pytest.fixture
def ctx():
    df = generate(seed=42)
    metrics = compute(df)
    return metrics, compute_highlights(metrics)


def test_enforce_check_count_forces_true_value():
    # The model wrote the churn value 16 in the role of "check count"; code must
    # overwrite it with the true count from validation (17) — the gate cannot,
    # because 16 is a legitimate number elsewhere in the data.
    bad = "All 16 data-quality checks passed with no failures."
    fixed = _enforce_check_count(bad, {"n_checks": 17})
    assert "17 data-quality checks" in fixed
    assert "16 data-quality checks" not in fixed


def test_enforce_check_count_leaves_real_data_numbers_untouched():
    # A genuine 16 (churned users / revenue) must not be rewritten.
    text = "Revenue fell to $16,470.00 and 16 users churned in month 12."
    assert _enforce_check_count(text, {"n_checks": 17}) == text


def test_enforce_check_count_normalises_ratio_form():
    # "16/16 data-quality checks" must become "17/17", not "16/17".
    bad = "All 16/16 data-quality checks passed."
    fixed = _enforce_check_count(bad, {"n_checks": 17})
    assert "17/17 data-quality checks" in fixed
    assert "16" not in fixed


def test_template_report_passes_its_own_check(ctx):
    metrics, h = ctx
    report = template_report(metrics, _CLEAN_VALIDATION, h)
    verdict = check_report_numbers(report, metrics, h)
    assert verdict["ok"], verdict["unmatched_numbers"]


def test_fabricated_number_is_flagged(ctx):
    metrics, h = ctx
    verdict = check_report_numbers("Revenue was $999,999.00 last month.", metrics, h)
    assert not verdict["ok"]
    assert "999,999.00" in verdict["unmatched_numbers"]


def test_wrong_sign_percentage_is_flagged(ctx):
    metrics, h = ctx
    # Actual revenue change is negative; claim a positive change of equal size.
    magnitude = abs(h["rev_change_pct"])
    text = f"Revenue increased by +{magnitude:.1f}% over the period."
    verdict = check_report_numbers(text, metrics, h)
    assert not verdict["ok"]


def test_month_range_not_misread_as_negative(ctx):
    metrics, h = ctx
    # "2-12" must not be parsed as the signed value -12.
    verdict = check_report_numbers("Churn over months 2-12 was steady.", metrics, h)
    assert verdict["ok"], verdict["unmatched_numbers"]
