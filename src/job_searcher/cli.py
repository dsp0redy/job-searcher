"""Command-line interface."""
from __future__ import annotations
import argparse
import json
import logging
from .config import AppConfig
from .orchestrator import SearchOrchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover and rank public job postings")
    parser.add_argument("--config", default="config.yml", help="YAML configuration path")
    parser.add_argument("--output-dir", default="reports", help="Report output directory")
    parser.add_argument("--check-config", action="store_true", help="Validate config without network calls")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = AppConfig.load(args.config)
    if args.check_config:
        print("Configuration valid")
        print(json.dumps(config.model_dump(), indent=2))
        return
    summary = SearchOrchestrator(config).run(args.output_dir)
    print(json.dumps(summary, indent=2))
    if summary.get("run_status") == "partial_ai_failure":
        raise SystemExit("AI matching was incomplete after retries; reports were generated, but the scan needs attention.")

if __name__ == "__main__":
    main()
