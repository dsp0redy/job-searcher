"""Coordinates adapters, persistence, matching, notifications, and report generation."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .adapters.greenhouse import GreenhouseAdapter
from .adapters.lever import LeverAdapter
from .adapters.workday import WorkdayAdapter
from .config import AppConfig
from .matching import score_job
from .models import Job
from .notifications import GitHubIssuePublisher
from .reporting import write_reports
from .storage import JobStore

LOG = logging.getLogger(__name__)


class SearchOrchestrator:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.store = JobStore(config.storage.path)

    def run(self, output_dir: str = "reports") -> dict[str, Any]:
        run_id = self.store.start_run()
        timeout = self.config.search.request_timeout_seconds
        adapters = [
            GreenhouseAdapter(self.config.sources.greenhouse, timeout),
            LeverAdapter(self.config.sources.lever, timeout),
            WorkdayAdapter(self.config.sources.workday, timeout, self.config.search.max_pages_per_source),
        ]
        all_jobs: list[Job] = []
        source_status: dict[str, str] = {}
        publisher: GitHubIssuePublisher | None = None
        try:
            for adapter in adapters:
                try:
                    found = adapter.fetch()
                    all_jobs.extend(found)
                    source_status[adapter.name] = f"ok: {len(found)} postings"
                except Exception as exc:
                    source_status[adapter.name] = f"failed: {type(exc).__name__}"
                    LOG.exception("Source %s failed; continuing other sources", adapter.name)
                finally:
                    adapter.close()

            inserted = self.store.upsert_jobs(all_jobs)
            rows: list[dict[str, Any]] = []
            notification_results: list[dict[str, Any]] = []
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.search.posted_within_days)
            notify_enabled = self.config.notifications.github_issues
            token = self.config.github_token()
            repository = self.config.notifications.repository or self.config.github_repository()
            if notify_enabled:
                if not token or not repository:
                    LOG.error("GitHub notifications enabled but GITHUB_TOKEN/GITHUB_REPOSITORY is not configured")
                else:
                    publisher = GitHubIssuePublisher(repository, token, timeout)

            try:
                for job in all_jobs:
                    # Keep undated postings; public boards frequently omit a trustworthy timestamp.
                    if job.posted_at and job.posted_at < cutoff:
                        continue
                    match = score_job(job, self.config.profile)
                    score = int(match["score"])
                    if score < self.config.search.minimum_local_score:
                        continue
                    row = {
                        "source": job.source,
                        "source_id": job.source_id,
                        "company": job.company,
                        "title": job.title,
                        "location": job.location,
                        "url": str(job.url),
                        "posted_at": job.posted_at.isoformat() if job.posted_at else None,
                        "score": score,
                        "reason": match["reason"],
                        "title_hits": match["title_hits"],
                        "location_hits": match["location_hits"],
                        "skill_hits": match["skill_hits"],
                        "notification": "not_eligible",
                    }
                    if notify_enabled and score >= self.config.matching.threshold:
                        if publisher is None:
                            row["notification"] = "not_configured"
                        else:
                            result = publisher.publish(
                                job,
                                score,
                                str(match["reason"]),
                                list(match["skill_hits"]),
                            )
                            row["notification"] = result["status"]
                            notification_results.append({
                                "company": job.company,
                                "title": job.title,
                                "score": score,
                                **result,
                            })
                    rows.append(row)
            finally:
                if publisher is not None:
                    publisher.close()

            paths = write_reports(output_dir, run_id, rows)
            summary = {
                "run_id": run_id,
                "sources": source_status,
                "postings_fetched": len(all_jobs),
                "new_identities": inserted,
                "qualified_candidates": len(rows),
                "match_threshold_for_notifications": self.config.matching.threshold,
                "notifications": {
                    "enabled": notify_enabled,
                    "created": sum(item["status"] == "created" for item in notification_results),
                    "already_exists": sum(item["status"] == "already_exists" for item in notification_results),
                    "failed": sum(item["status"] == "failed" for item in notification_results),
                    "not_configured": notify_enabled and publisher is None,
                    "results": notification_results,
                },
                "reports": [str(path) for path in paths],
                "matching": "deterministic local scoring; no AI provider configured",
            }
            status = "success" if any(value.startswith("ok:") for value in source_status.values()) else "no_sources_succeeded"
            self.store.finish_run(run_id, status, summary)
            return summary
        except Exception as exc:
            self.store.finish_run(run_id, "failed", {"error_type": type(exc).__name__})
            raise
