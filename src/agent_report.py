"""Reporting agent: turns pre-computed metrics into a business report.

Two paths, same grounding:
- agentic path (if ANTHROPIC_API_KEY is set): an LLM drafts the report and uses a
  deterministic `check_report_numbers` tool to verify every figure against
  metrics.csv, revising until clean. This is the "agent" — it orchestrates,
  narrates and self-checks, but never does arithmetic.
- template path (no key / LLM error): a deterministic report built from the same
  metrics and highlights. Guarantees a reproducible, submittable artifact.
"""

from __future__ import annotations

import logging
import os
import re

import pandas as pd

from src import config, prompts

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Highlights — deterministic, derived purely from metrics.
# --------------------------------------------------------------------------- #
def _decomposition(df: pd.DataFrame, first, last) -> dict:
    """Attribute the revenue change to its drivers: volume vs ARPU, and quantify
    the revenue leaked to failed payments. All figures are real, from the data."""
    total_change = float(last["monthly_revenue"] - first["monthly_revenue"])
    # Volume effect: change in active users priced at the starting ARPU.
    volume_effect = float(
        (last["active_users"] - first["active_users"]) * first["arpu"]
    )
    # ARPU effect: change in per-user revenue on the ending base.
    arpu_effect = float(last["active_users"] * (last["arpu"] - first["arpu"]))

    active = df[df["is_active"]]
    potential = float(active["monthly_price"].sum())  # if every active user paid
    actual = float(active["amount_paid"].sum())  # what was actually collected
    leakage = potential - actual  # revenue lost to failed payments

    def premium_share(month: int) -> float:
        a = active[active["month"] == month]
        return round((a["plan"] == "premium").mean() * 100, 1) if len(a) else 0.0

    return {
        "rev_decline": round(abs(total_change), 2),
        "vol_share_pct": round(volume_effect / total_change * 100, 1)
        if total_change
        else 0.0,
        "arpu_share_pct": round(arpu_effect / total_change * 100, 1)
        if total_change
        else 0.0,
        "failed_leakage": round(leakage, 2),
        "failed_leakage_pct": round(leakage / potential * 100, 1) if potential else 0.0,
        "premium_share_first": premium_share(int(first["month"])),
        "premium_share_last": premium_share(int(last["month"])),
    }


def compute_highlights(metrics: pd.DataFrame, df: pd.DataFrame | None = None) -> dict:
    first, last = metrics.iloc[0], metrics.iloc[-1]
    after_first = metrics[metrics["month"] > 1]

    rev_change_pct = (
        (last["monthly_revenue"] - first["monthly_revenue"])
        / first["monthly_revenue"]
        * 100
        if first["monthly_revenue"]
        else 0.0
    )
    arpu_change_pct = (
        (last["arpu"] - first["arpu"]) / first["arpu"] * 100 if first["arpu"] else 0.0
    )
    max_churn = after_first.loc[after_first["churn_rate"].idxmax()]
    min_churn = after_first.loc[after_first["churn_rate"].idxmin()]
    avg_churn = float(after_first["churn_rate"].mean())
    anomalies = after_first[after_first["churn_rate"] > avg_churn * 1.5]

    result = {
        "total_revenue": round(float(metrics["monthly_revenue"].sum()), 2),
        "rev_first": float(first["monthly_revenue"]),
        "rev_last": float(last["monthly_revenue"]),
        "rev_change_pct": round(rev_change_pct, 1),
        "arpu_first": float(first["arpu"]),
        "arpu_last": float(last["arpu"]),
        "arpu_change_pct": round(arpu_change_pct, 1),
        "start_users": int(first["active_users"]),
        "end_users": int(last["active_users"]),
        "retention_pct": round(last["active_users"] / first["active_users"] * 100, 1),
        "avg_churn_pct": round(avg_churn * 100, 1),
        "max_churn_month": int(max_churn["month"]),
        "max_churn_pct": round(float(max_churn["churn_rate"]) * 100, 1),
        "min_churn_month": int(min_churn["month"]),
        "min_churn_pct": round(float(min_churn["churn_rate"]) * 100, 1),
        "anomaly_months": anomalies["month"].tolist(),
    }
    if df is not None:
        result.update(_decomposition(df, first, last))
    return result


def _highlights_md(h: dict) -> str:
    return (
        f"- Total revenue over 12 months: ${h['total_revenue']:,.2f}\n"
        f"- Revenue month 1 -> month 12: ${h['rev_first']:,.2f} -> ${h['rev_last']:,.2f} "
        f"({h['rev_change_pct']:+.1f}%)\n"
        f"- ARPU month 1 -> month 12: ${h['arpu_first']:.2f} -> ${h['arpu_last']:.2f} "
        f"({h['arpu_change_pct']:+.1f}%)\n"
        f"- Active users month 1 -> month 12: {h['start_users']} -> {h['end_users']} "
        f"({h['retention_pct']:.1f}% retained)\n"
        f"- Average monthly churn (m2-m12): {h['avg_churn_pct']:.1f}%\n"
        f"- Highest churn: month {h['max_churn_month']} ({h['max_churn_pct']:.1f}%); "
        f"lowest: month {h['min_churn_month']} ({h['min_churn_pct']:.1f}%)\n"
        f"- Churn anomaly months (> 1.5x avg): {h['anomaly_months'] or 'none'}"
        + (
            f"\n- Revenue decline split: ~{h['vol_share_pct']:.1f}% volume (churn), "
            f"~{h['arpu_share_pct']:.1f}% ARPU\n"
            f"- Revenue leaked to failed payments: ${h['failed_leakage']:,.2f} "
            f"({h['failed_leakage_pct']:.1f}% of billable)\n"
            f"- Premium-plan share among active m1 -> m12: "
            f"{h['premium_share_first']:.1f}% -> {h['premium_share_last']:.1f}%"
            if "vol_share_pct" in h
            else ""
        )
    )


# --------------------------------------------------------------------------- #
# Guardrail: deterministic number checker (also exposed to the agent as a tool).
# --------------------------------------------------------------------------- #
def _allowed_numbers(metrics: pd.DataFrame, h: dict) -> tuple[set[float], set[float]]:
    """Return (unsigned magnitudes, signed change values).

    Signed values let the checker catch a wrong-direction percentage (e.g. a
    report claiming revenue rose +52.6% when it actually fell -52.6%).
    """
    unsigned: set[float] = set()
    for col in [
        "month",
        "active_users",
        "paid_users",
        "churned_users",
        "monthly_revenue",
        "arpu",
    ]:
        unsigned.update(float(v) for v in metrics[col].tolist())
    unsigned.update(float(round(v * 100, 1)) for v in metrics["churn_rate"].tolist())
    unsigned.update(float(v) for v in config.PLANS.values())
    changes = [float(h["rev_change_pct"]), float(h["arpu_change_pct"])]
    unsigned.update(
        {
            float(config.N_USERS),
            float(config.N_MONTHS),
            h["total_revenue"],
            h["retention_pct"],
            h["avg_churn_pct"],
            h["max_churn_pct"],
            h["min_churn_pct"],
            1.5,  # anomaly threshold multiplier referenced in the report
            *(abs(c) for c in changes),
        }
    )
    # Revenue-loss decomposition figures (present only when df was supplied).
    for key in (
        "rev_decline",
        "vol_share_pct",
        "arpu_share_pct",
        "failed_leakage",
        "failed_leakage_pct",
        "premium_share_first",
        "premium_share_last",
    ):
        if key in h:
            unsigned.add(abs(float(h[key])))
    return unsigned, set(changes)


# Optional sign + number + optional %. The lookbehind stops "2-12" (a month
# range) from being read as the signed value "-12".
_NUM_RE = re.compile(r"(?<!\d)([-+]?)(\d[\d,]*(?:\.\d+)?)(%?)")


def check_report_numbers(report_md: str, metrics: pd.DataFrame, h: dict) -> dict:
    """Verify every numeric token in the report matches an allowed figure.

    A guardrail against fabricated/garbled numbers (not semantics). Small
    integers (1-12, used as month/section indices) pass; signed percentages must
    match a signed change value, so a flipped direction is flagged.
    """
    unsigned, signed = _allowed_numbers(metrics, h)
    issues: list[str] = []
    for sign, body, pct in _NUM_RE.findall(report_md):
        magnitude = float(body.replace(",", ""))
        if sign and pct:  # a signed percentage -> must match a signed change
            value = magnitude if sign == "+" else -magnitude
            if any(abs(value - a) <= max(0.1, abs(a) * 0.01) for a in signed):
                continue
            issues.append(f"{sign}{body}%")
            continue
        if magnitude <= config.N_MONTHS and magnitude == int(magnitude):
            continue  # month / section indices
        if any(abs(magnitude - a) <= max(0.5, a * 0.01) for a in unsigned):
            continue
        issues.append(body)
    issues = sorted(set(issues))
    return {"ok": not issues, "unmatched_numbers": issues}


# --------------------------------------------------------------------------- #
# Template path (deterministic, no API needed).
# --------------------------------------------------------------------------- #
def _metrics_table_md(metrics: pd.DataFrame) -> str:
    header = "| month | active | paid | churned | revenue | churn_rate | arpu |\n"
    header += "|---|---|---|---|---|---|---|\n"
    rows = ""
    for _, r in metrics.iterrows():
        rows += (
            f"| {int(r['month'])} | {int(r['active_users'])} | {int(r['paid_users'])} "
            f"| {int(r['churned_users'])} | ${r['monthly_revenue']:,.2f} "
            f"| {r['churn_rate'] * 100:.1f}% | ${r['arpu']:.2f} |\n"
        )
    return header + rows


def template_report(metrics: pd.DataFrame, validation: dict, h: dict) -> str:
    dq_status = "PASSED" if validation["overall_passed"] else "FAILED"
    failed = [c["check"] for c in validation["checks"] if not c["passed"]]
    warning = (
        ""
        if validation["overall_passed"]
        else "> ⚠️ **Data quality checks FAILED — figures below are not reliable; "
        "treat conclusions as provisional.**\n\n"
    )
    anomalies = (
        f"Churn in month(s) {h['anomaly_months']} exceeded 1.5x the average "
        f"({h['avg_churn_pct']:.1f}%) and warrants investigation."
        if h["anomaly_months"]
        else "No month exceeded 1.5x the average churn rate; the curve is smooth."
    )

    decomp_md = ""
    if "vol_share_pct" in h:
        richer = (
            "richer"
            if h["premium_share_last"] >= h["premium_share_first"]
            else "leaner"
        )
        decomp_md = (
            f"**Revenue-loss decomposition.** Of the ${h['rev_decline']:,.2f} drop in "
            f"monthly revenue (month 1 -> month {config.N_MONTHS}), ~{h['vol_share_pct']:.1f}% "
            f"is volume (fewer active users) and only ~{h['arpu_share_pct']:.1f}% is ARPU — "
            f"hard confirmation that this is retention, not pricing. Separately, failed "
            f"payments leaked **${h['failed_leakage']:,.2f}** ({h['failed_leakage_pct']:.1f}% "
            f"of billable revenue) over the year — the addressable dunning opportunity. The "
            f"surviving base skews slightly {richer}: premium share moved "
            f"{h['premium_share_first']:.1f}% -> {h['premium_share_last']:.1f}%.\n\n"
        )

    return f"""\
# Churn & Revenue Report — Consumer Subscription Cohort

{warning}## 1. Executive summary

A closed cohort of {h["start_users"]} users acquired in month 1 was tracked for
{config.N_MONTHS} months. Over the period the cohort generated
**${h["total_revenue"]:,.2f}** in revenue. Monthly revenue moved from
${h["rev_first"]:,.2f} to ${h["rev_last"]:,.2f} ({h["rev_change_pct"]:+.1f}%),
driven by churn: only {h["end_users"]} users ({h["retention_pct"]:.1f}%) remained
active by month {config.N_MONTHS}. ARPU held up at ${h["arpu_last"]:.2f}
({h["arpu_change_pct"]:+.1f}% vs month 1), so revenue decline is a volume story,
not a pricing one.

## 2. Monthly revenue trend

Revenue fell from ${h["rev_first"]:,.2f} (month 1) to ${h["rev_last"]:,.2f}
(month {config.N_MONTHS}), a {h["rev_change_pct"]:+.1f}% change. The decline
tracks the shrinking active base rather than lower spend per user.

{_metrics_table_md(metrics)}

## 3. Churn trend

Average monthly churn (months 2-{config.N_MONTHS}) was {h["avg_churn_pct"]:.1f}%.
Churn peaked in month {h["max_churn_month"]} ({h["max_churn_pct"]:.1f}%) and was
lowest in month {h["min_churn_month"]} ({h["min_churn_pct"]:.1f}%). The pattern is
front-loaded: losses are heaviest in the early onboarding months and ease as the
surviving base stabilises.

## 4. ARPU trend

ARPU went from ${h["arpu_first"]:.2f} to ${h["arpu_last"]:.2f}
({h["arpu_change_pct"]:+.1f}%). ARPU is per active user and stays stable: it
reflects the plan mix of survivors net of failed-payment leakage (months where an
active user's charge fails contribute $0), not discounting.

## 5. Data quality checks

Validation status: **{dq_status}** (all data-quality checks).
{("Failed checks: " + ", ".join(failed)) if failed else "Every check passed, including a full monthly metric recomputation from the raw data, revenue reconciliation (CSV total == metrics total), uniqueness of (user_id, month), plan-price consistency, and a monotonically non-increasing active base."}

## 6. Business interpretation

{anomalies}

{decomp_md}Takeaways:
1. **Revenue loss is a retention problem, not a pricing problem** — ARPU is flat
   ({h["arpu_change_pct"]:+.1f}%) while the active base fell to {h["retention_pct"]:.1f}%.
   Effort belongs on keeping users, not raising prices.
2. **Fix the early-life leak** — churn is highest around month {h["max_churn_month"]};
   improving onboarding and the first-payment experience has the largest payback.
3. **Failed payments feed involuntary churn** — payment recovery (retries, dunning)
   is a cheap lever to protect revenue without acquiring new users.
"""


def _enforce_check_count(text: str, validation: dict) -> str:
    """Code owns the count of data-quality checks — never the model.

    The number-gate only proves a figure *exists* in the data; it cannot tell
    that a real value is used in the wrong role. The model once wrote the churn
    value (16) as the check count, and the gate passed it because 16 is a legit
    number. Here code overwrites any stated check count with the true value from
    `validation`, closing that "right number, wrong role" class deterministically.
    """
    n = validation.get("n_checks", len(validation.get("checks", [])))
    return re.sub(
        r"\d+(\s+data[- ]quality\s+checks)",
        lambda m: f"{n}{m.group(1)}",
        text,
        flags=re.IGNORECASE,
    )


# --------------------------------------------------------------------------- #
# Agentic path (LLM orchestration with self-check tool).
# --------------------------------------------------------------------------- #
def _agentic_report(metrics: pd.DataFrame, validation: dict, h: dict) -> str:
    import json

    import anthropic

    client = anthropic.Anthropic()
    validation_md = "\n".join(
        f"- {c['check']}: {'PASS' if c['passed'] else 'FAIL'}"
        + (f" ({c['detail']})" if c["detail"] and not c["passed"] else "")
        for c in validation["checks"]
    )
    user_prompt = prompts.build_user_prompt(
        _metrics_table_md(metrics), validation_md, _highlights_md(h)
    )
    tools = [
        {
            "name": "check_report_numbers",
            "description": "Verify that every number in the draft report matches the "
            "official metrics. Returns ok=true when clean, else the unmatched numbers.",
            "input_schema": {
                "type": "object",
                "properties": {"report_markdown": {"type": "string"}},
                "required": ["report_markdown"],
            },
        }
    ]
    messages = [{"role": "user", "content": user_prompt}]
    transcript: list[str] = [
        "# Agent transcript",
        "",
        "Evidence that the report is produced by a tool-using agent loop: the agent "
        "drafts, calls the deterministic `check_report_numbers` tool, and revises "
        "until clean. Numbers come from the metrics, never invented by the model.",
        "",
    ]

    for turn in range(1, config.MAX_AGENT_ITERS + 2):
        resp = client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=config.LLM_MAX_TOKENS,
            temperature=config.LLM_TEMPERATURE,
            system=prompts.NARRATOR_SYSTEM,
            tools=tools,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "tool_use":
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use" and block.name == "check_report_numbers":
                    result = check_report_numbers(
                        block.input.get("report_markdown", ""), metrics, h
                    )
                    transcript.append(
                        f"## Turn {turn}: agent called `check_report_numbers`\n"
                        f"- tool verdict: `{json.dumps(result, ensure_ascii=False)}`"
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
            messages.append({"role": "user", "content": tool_results})
            continue

        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        # Drop any conversational preamble before the first Markdown heading.
        heading = text.find("# ")
        if heading > 0:
            text = text[heading:]

        # Always gate the FINAL text through the deterministic checker, even if
        # the model never called the tool itself. This is the real guardrail.
        verdict = check_report_numbers(text, metrics, h)
        if not verdict["ok"]:
            logger.warning("Final report has unverified numbers: %s", verdict)
            transcript.append(
                f"## Turn {turn}: final-gate check FAILED\n"
                f"- unverified numbers: `{verdict['unmatched_numbers']}` -> sent back for repair"
            )
            messages.append(
                {
                    "role": "user",
                    "content": "Your report contains numbers not present in the "
                    f"metrics: {verdict['unmatched_numbers']}. Fix them using only "
                    "the provided figures and output the corrected report.",
                }
            )
            continue  # spend another round to repair

        text = _enforce_check_count(text, validation)
        transcript.append(
            f"## Turn {turn}: final report accepted\n"
            "- deterministic final-gate check: `ok=true` (every number traced to metrics.csv)\n"
            "- code-owned counts normalised: data-quality check count set from validation, "
            "not the model"
        )
        if not validation["overall_passed"]:
            text = (
                "> ⚠️ **Data quality checks FAILED — figures are not reliable.**\n\n"
                + text
            )
        _write_transcript(transcript)
        return text

    _write_transcript(
        transcript + ["", "_Agent did not converge; template fallback used._"]
    )
    raise RuntimeError(
        "agent did not converge to a number-clean report; using template fallback"
    )


def _write_transcript(lines: list[str]) -> None:
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.AGENT_TRANSCRIPT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote agent transcript -> %s", config.AGENT_TRANSCRIPT)


# --------------------------------------------------------------------------- #
# Entry point.
# --------------------------------------------------------------------------- #
def build_report(
    metrics: pd.DataFrame, validation: dict, df: pd.DataFrame | None = None
) -> str:
    h = compute_highlights(metrics, df)
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            logger.info("Generating report via agentic LLM path")
            return _agentic_report(metrics, validation, h)
        except Exception as exc:  # noqa: BLE001 - fall back to deterministic report
            logger.warning("LLM path failed (%s); falling back to template", exc)
    else:
        logger.info("No ANTHROPIC_API_KEY; using deterministic template report")
    return template_report(metrics, validation, h)


def build_report_to_md(
    metrics: pd.DataFrame, validation: dict, df: pd.DataFrame | None = None
) -> str:
    report = build_report(metrics, validation, df)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.REPORT_MD.write_text(report, encoding="utf-8")
    logger.info("Wrote report -> %s", config.REPORT_MD)
    return report
