"""Central configuration: all knobs in one place for reproducibility."""

from __future__ import annotations

from pathlib import Path

# --- Reproducibility ---
SEED = 42

# --- Synthetic cohort shape ---
N_USERS = 1000
N_MONTHS = 12

# --- Subscription plans (plan -> monthly price) and onboarding mix ---
PLANS: dict[str, float] = {"basic": 10.0, "plus": 20.0, "premium": 40.0}
PLAN_WEIGHTS: dict[str, float] = {"basic": 0.5, "plus": 0.3, "premium": 0.2}

# --- Behaviour model ---
# Probability that an active subscriber's payment fails in a given month
# (failed payment != churn: the user can stay and recover next month).
P_PAYMENT_FAIL = 0.05
# A failed payment raises the chance of (involuntary) churn into the next month.
FAILED_PAYMENT_CHURN_MULT = 1.5


def churn_hazard(month: int) -> float:
    """Monthly probability that an active user churns INTO the next month.

    Higher early (onboarding shock), lower once users settle — a realistic
    subscription survival curve that produces an interesting churn trend.
    """
    if month <= 3:
        return 0.10
    if month <= 8:
        return 0.06
    return 0.04


# --- LLM (optional; pipeline is fully functional without it) ---
LLM_MODEL = "claude-sonnet-4-6"
LLM_MAX_TOKENS = 2500
LLM_TEMPERATURE = 0.0
MAX_AGENT_ITERS = 2  # report draft -> self-check -> revise rounds

# --- Paths ---
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"
DATA_CSV = DATA_DIR / "subscriptions.csv"
METRICS_CSV = OUTPUT_DIR / "metrics.csv"
VALIDATION_JSON = OUTPUT_DIR / "validation.json"
REPORT_MD = OUTPUT_DIR / "report.md"
AGENT_TRANSCRIPT = OUTPUT_DIR / "agent_transcript.md"
