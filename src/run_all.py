"""End-to-end pipeline: generate -> compute metrics -> validate -> report.

The deterministic core (generate/metrics/validate) always runs and is the source
of numeric truth. The reporting step uses the LLM agent when a key is available,
otherwise a deterministic template — either way the numbers come from the core.

Usage:
    python -m src.run_all [--seed N]
"""

from __future__ import annotations

import argparse
import logging
import os

from src import agent_report, config, generate_data, metrics as metrics_mod, validate


def _load_dotenv() -> None:
    """Load KEY=VALUE pairs from a local .env (if present) into the environment.

    Lets the optional LLM path pick up ANTHROPIC_API_KEY without exporting it or
    hard-coding it. The .env file is gitignored.
    """
    env_path = config.REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> None:
    parser = argparse.ArgumentParser(description="Churn & revenue reporting agent")
    parser.add_argument("--seed", type=int, default=config.SEED, help="RNG seed")
    args = parser.parse_args()

    _load_dotenv()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    log = logging.getLogger("run_all")

    log.info("1/4 Generating synthetic data (seed=%d)", args.seed)
    df = generate_data.generate_to_csv(args.seed)

    log.info("2/4 Computing metrics")
    metrics = metrics_mod.compute_to_csv(df)

    log.info("3/4 Validating data and metrics")
    validation = validate.validate_to_json(df, metrics)

    log.info("4/4 Building report")
    agent_report.build_report_to_md(metrics, validation, df)

    status = "PASS" if validation["overall_passed"] else "FAIL"
    log.info(
        "Done. DQ=%s | rows=%d | revenue=$%.2f | artifacts in %s",
        status,
        len(df),
        metrics["monthly_revenue"].sum(),
        config.OUTPUT_DIR,
    )


if __name__ == "__main__":
    main()
