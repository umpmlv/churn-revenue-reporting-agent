# Monthly Business Report

## 1. Executive Summary

Over the 12-month period, the business generated **$144,880.00** in total revenue. Starting from 1,000 active users in month 1, the base contracted to **476** by month 12 — a retention rate of **47.6%**. Revenue fell from **$18,000.00** to **$8,540.00**, a decline of **52.6%**, driven almost entirely (~99.7%) by subscriber loss rather than pricing erosion. ARPU remained remarkably stable, moving only from **$18.00** to **$17.94** (-0.3%). All data-quality checks passed; figures presented below are final.

---

## 2. Monthly Revenue Trend

| Month | Revenue |
|---|---|
| 1 | $18,000.00 |
| 2 | $16,470.00 |
| 3 | $14,680.00 |
| 4 | $13,570.00 |
| 5 | $12,480.00 |
| 6 | $11,910.00 |
| 7 | $11,010.00 |
| 8 | $10,410.00 |
| 9 | $9,920.00 |
| 10 | $9,140.00 |
| 11 | $8,750.00 |
| 12 | $8,540.00 |

Revenue declined every single month, falling **52.6%** from $18,000.00 (M1) to $8,540.00 (M12). The steepest absolute drop occurred between months 2 and 3 ($16,470.00 → $14,680.00), coinciding with the second-highest churn month. The pace of decline visibly slowed in the second half: months 6–12 posted progressively smaller sequential drops as churn moderated. A notable drag throughout is **$7,330.00** in revenue leaked to failed payments (**4.8%** of billable), which represents a recoverable opportunity.

---

## 3. Churn Trend

| Month | Churned | Churn Rate |
|---|---|---|
| 2 | 96 | 9.6% |
| 3 | 86 | 9.5% |
| 4 | 74 | 9.0% |
| 5 | 43 | 5.8% |
| 6 | 49 | 7.0% |
| 7 | 43 | 6.6% |
| 8 | 35 | 5.8% |
| 9 | 31 | 5.4% |
| 10 | 28 | 5.2% |
| 11 | 23 | 4.5% |
| 12 | 16 | 3.2% |

The average monthly churn rate (M2–M12) was **6.5%**. Churn was front-loaded: months 2–4 posted rates of **9.6%**, **9.5%**, and **9.0%** respectively — well above the period average. Month 5 marked a structural break, with churn dropping sharply to **5.8%** and never returning to early-period levels. From M5 onward, churn trended steadily downward, reaching a period-low of **3.2%** in month 12. No anomaly months (defined as >1.5× the average) were identified. The improving trajectory is encouraging, but the absolute base has already shrunk significantly.

---

## 4. ARPU Trend

| Month | ARPU |
|---|---|
| 1 | $18.00 |
| 2 | $18.22 |
| 3 | $17.95 |
| 4 | $18.24 |
| 5 | $17.80 |
| 6 | $18.27 |
| 7 | $18.08 |
| 8 | $18.14 |
| 9 | $18.27 |
| 10 | $17.75 |
| 11 | $17.78 |
| 12 | $17.94 |

ARPU was exceptionally stable across the period, ranging from a low of **$17.75** (M10) to a high of **$18.27** (M6 and M9), a spread of just **$0.52**. The 12-month change was a negligible **-0.3%** ($18.00 → $17.94). Premium-plan share among active users was similarly flat: **19.7%** in M1 versus **19.3%** in M12. This confirms that the revenue decline is a pure volume story — the product's monetisation per user is holding firm.

---

## 5. Data Quality Checks

All **17 data-quality checks passed** with no failures or warnings:

`schema_columns` · `no_nulls` · `unique_user_month` · `user_count` · `month_range` · `plan_price_mapping` · `payment_amount_consistency` · `lapse_row_consistency` · `active_users_non_increasing` · `paid_le_active` · `churn_rate_range` · `revenue_reconciliation` · `arpu_recomputation` · `payment_status_domain` · `no_reactivation` · `single_lapse_per_user` · `monthly_metric_recomputation`

The dataset is clean and internally consistent. All figures in this report are confirmed final. No caveats apply.

---

## 6. Business Interpretation

**1. Acquisition failure is the core problem, not monetisation.**
Revenue is down **52.6%** purely because the active user base halved (1,000 → 476, **47.6%** retained). ARPU barely moved (**-0.3%**), and premium-plan share held at ~19–20%. The product charges the right price; it is simply losing subscribers faster than it retains them. Without new user acquisition, the base will continue to erode even at the improved M12 churn rate of **3.2%**.

**2. Churn improvement is real and should be protected.**
The drop from **9.6%** (M2) to **3.2%** (M12) is a meaningful operational improvement — monthly churn roughly halved over the period. If the M12 rate of **3.2%** can be sustained or reduced further, the remaining 476 users represent a more stable revenue floor of ~**$8,540.00**/month. Identifying what drove the M5 inflection (product change, cohort maturation, support intervention) is a priority to replicate and defend.

**3. Failed-payment recovery is a quick win.**
**$7,330.00** (**4.8%** of billable revenue) was lost to failed payments over the period. This is involuntary churn that does not reflect user intent to cancel. Implementing a dunning workflow (automated retries, payment-update prompts) could recover a meaningful share of this leakage with minimal product investment.