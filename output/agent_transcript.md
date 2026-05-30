# Agent transcript

Evidence that the report is produced by a tool-using agent loop: the agent drafts, calls the deterministic `check_report_numbers` tool, and revises until clean. Numbers come from the metrics, never invented by the model.

## Turn 1: agent called `check_report_numbers`
- tool verdict: `{"ok": false, "unmatched_numbers": ["-10.9%", "-2.4%", "-4.3%", "-4.6%", "-4.8%", "-5.4%", "-7.6%", "-7.9%", "-8.0%", "-8.5%", "1,790.00", "17"]}`
## Turn 2: agent called `check_report_numbers`
- tool verdict: `{"ok": true, "unmatched_numbers": []}`
## Turn 3: final report accepted
- deterministic final-gate check: `ok=true` (every number traced to metrics.csv)
