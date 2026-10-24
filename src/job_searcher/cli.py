"""Command-line interface."""
from __future__ import annotations
import argparse
import json
import logging
from .ai_matching import load_resume_text
from .config import AppConfig
from .orchestrator import SearchOrchestrator
from .storage import JobStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover and rank public job postings")
    parser.add_argument("--config", default="config.yml", help="YAML configuration path")
    parser.add_argument("--output-dir", default="reports", help="Report output directory")
    parser.add_argument("--check-config", action="store_true", help="Validate config without network calls")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--preview-resume", action="store_true", help="Preview extracted resume text locally; no provider calls are made")
    parser.add_argument("--backup-db", metavar="PATH", help="Create a consistent SQLite backup and exit")
    parser.add_argument("--job-identity", help="Job identity from a JSON report; inspect or update its local review status")
    parser.add_argument("--review-status", choices=["saved", "applied", "rejected", "stale"], help="Set review status for --job-identity")
    parser.add_argument("--review-notes", default="", help="Optional private local review notes (max 2000 characters)")
    parser.add_argument("--prune-now", action="store_true", help="Prune persisted data using configured retention and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = AppConfig.load(args.config)
    if args.preview_resume:
        try:
            resume = load_resume_text()
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        preview = {
            "characters": len(resume),
            "words": len(resume.split()),
            "quality_warning": len(resume) < 80,
            "preview": resume[:1200],
            "truncated": len(resume) > 1200,
            "network_requests_made": False,
        }
        print(json.dumps(preview, indent=2))
        return
    if args.check_config:
        print("Configuration valid")
        print(json.dumps(config.model_dump(), indent=2))
        return
    store = JobStore(config.storage.path)
    if args.backup_db:
        print(json.dumps({"backup": store.backup_to(args.backup_db)}, indent=2))
        return
    if args.prune_now:
        print(json.dumps({"retention": store.prune_old_data(config.storage.retention_days)}, indent=2))
        return
    if args.job_identity:
        if args.review_status:
            result = store.set_review_status(args.job_identity, args.review_status, args.review_notes)
        else:
            if args.review_notes:
                parser.error("--review-notes requires --review-status")
            review_result = store.get_review_status(args.job_identity)
            if review_result is None:
                raise SystemExit(f"No review status found for job identity: {args.job_identity}")
            result = review_result
        print(json.dumps(result, indent=2))
        return
    if args.review_status or args.review_notes:
        parser.error("--review-status and --review-notes require --job-identity")
    summary = SearchOrchestrator(config).run(args.output_dir)
    print(json.dumps(summary, indent=2))
    if summary.get("run_status") == "partial_ai_failure":
        raise SystemExit("AI matching was incomplete after retries; reports were generated, but the scan needs attention.")
    if summary.get("run_status") == "no_sources_succeeded":
        raise SystemExit("No configured job sources returned successfully; inspect source health and credentials.")
    if summary.get("run_status") == "partial_notification_failure":
        raise SystemExit("One or more GitHub notifications failed; reports were generated, but notification delivery needs attention.")

if __name__ == "__main__":
    main()
