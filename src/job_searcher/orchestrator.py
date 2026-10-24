"""Coordinates source adapters, local/AI matching, persistence, and reports."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .adapters.greenhouse import GreenhouseAdapter
from .adapters.lever import LeverAdapter
from .adapters.workday import WorkdayAdapter
from .ai_matching import AIResumeMatcher, MatchResult
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
        ai_matcher: AIResumeMatcher | None = None
        publisher: GitHubIssuePublisher | None = None
        try:
            provider = self.config.matching.provider.casefold()
            if provider != "none":
                ai_matcher = AIResumeMatcher(provider, timeout)

            adapters = [
                GreenhouseAdapter(self.config.sources.greenhouse, timeout),
                LeverAdapter(self.config.sources.lever, timeout),
                WorkdayAdapter(self.config.sources.workday, timeout, self.config.search.max_pages_per_source),
            ]
            all_jobs: list[Job] = []
            source_status: dict[str, str] = {}
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
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.search.posted_within_days)
            candidates: list[tuple[Job, dict[str, object]]] = []
            for job in all_jobs:
                if job.posted_at and job.posted_at < cutoff:
                    continue
                local_match = score_job(job, self.config.profile)
                if int(local_match["score"]) >= self.config.search.minimum_local_score:
                    candidates.append((job, local_match))

            ai_results: dict[str, MatchResult] = {}
            ai_failed: set[str] = set()
            ai_deferred: set[str] = set()
            ai_cached = 0
            if ai_matcher is not None:
                ranked = sorted(candidates, key=lambda pair: int(pair[1]["score"]), reverse=True)
                ai_limit = self.config.matching.max_ai_jobs_per_scan
                selected = ranked[:ai_limit]
                ai_deferred = {job.identity for job, _ in ranked[ai_limit:]}
                uncached: list[Job] = []
                for job, _ in selected:
                    key = ai_matcher.cache_key(job)
                    cached = self.store.get_match(key)
                    if cached is not None:
                        try:
                            result = MatchResult.model_validate(cached)
                            if result.job_id == job.identity:
                                ai_results[job.identity] = result
                                ai_cached += 1
                                continue
                        except Exception:
                            LOG.info("Ignoring invalid cached AI result for %s", job.identity)
                    uncached.append(job)

                batch_size = self.config.matching.max_jobs_per_ai_batch
                for offset in range(0, len(uncached), batch_size):
                    batch = uncached[offset:offset + batch_size]
                    results = ai_matcher.match_batch(batch)
                    ai_results.update(results)
                    for job in batch:
                        result = results.get(job.identity)
                        if result is None:
                            ai_failed.add(job.identity)
                        else:
                            self.store.save_match(ai_matcher.cache_key(job), provider, result.model_dump())

            notify_enabled = self.config.notifications.github_issues
            token = self.config.github_token()
            repository = self.config.notifications.repository or self.config.github_repository()
            if notify_enabled:
                if not token or not repository:
                    LOG.error("GitHub notifications enabled but GITHUB_TOKEN/GITHUB_REPOSITORY is not configured")
                else:
                    publisher = GitHubIssuePublisher(repository, token, timeout)

            rows: list[dict[str, Any]] = []
            notification_results: list[dict[str, Any]] = []
            for job, local_match in candidates:
                local_score = int(local_match["score"])
                ai_result = ai_results.get(job.identity)
                if ai_matcher is None:
                    score = local_score
                    reason = str(local_match["reason"])
                    matched_skills = list(local_match["skill_hits"])
                    missing_skills: list[str] = []
                    improvements: list[str] = []
                    ai_status = "disabled"
                elif ai_result is not None:
                    score = ai_result.score
                    reason = ai_result.reason
                    matched_skills = list(local_match["skill_hits"])
                    missing_skills = ai_result.missing_skills
                    improvements = ai_result.improvements
                    ai_status = "matched"
                else:
                    score = local_score
                    reason = str(local_match["reason"])
                    matched_skills = list(local_match["skill_hits"])
                    missing_skills = []
                    improvements = []
                    ai_status = "deferred" if job.identity in ai_deferred else "failed"

                row: dict[str, Any] = {
                    "source": job.source,
                    "source_id": job.source_id,
                    "company": job.company,
                    "title": job.title,
                    "location": job.location,
                    "url": str(job.url),
                    "posted_at": job.posted_at.isoformat() if job.posted_at else None,
                    "score": score,
                    "local_score": local_score,
                    "ai_score": ai_result.score if ai_result else None,
                    "ai_status": ai_status,
                    "reason": reason,
                    "title_hits": local_match["title_hits"],
                    "location_hits": local_match["location_hits"],
                    "skill_hits": matched_skills,
                    "missing_skills": missing_skills,
                    "improvements": improvements,
                    "notification": "not_eligible",
                }

                ai_eligible = ai_matcher is None or ai_status == "matched"
                if notify_enabled and ai_eligible and score >= self.config.matching.threshold:
                    if publisher is None:
                        row["notification"] = "not_configured"
                    else:
                        result = publisher.publish(
                            job,
                            score,
                            reason,
                            matched_skills,
                            missing_skills=missing_skills,
                            improvements=improvements,
                        )
                        row["notification"] = result["status"]
                        notification_results.append({
                            "company": job.company,
                            "title": job.title,
                            "score": score,
                            **result,
                        })
                elif notify_enabled and ai_matcher is not None and ai_status in {"failed", "deferred"}:
                    row["notification"] = f"ai_{ai_status}"

                rows.append(row)

            paths = write_reports(output_dir, run_id, rows)
            summary = {
                "run_id": run_id,
                "sources": source_status,
                "postings_fetched": len(all_jobs),
                "new_identities": inserted,
                "qualified_candidates": len(rows),
                "matching": provider if ai_matcher else "deterministic local scoring",
                "ai": {
                    "enabled": ai_matcher is not None,
                    "scored": len(ai_results) - ai_cached,
                    "matched_including_cache": len(ai_results),
                    "cached": ai_cached,
                    "failed": len(ai_failed),
                    "deferred_by_scan_limit": len(ai_deferred),
                    "max_jobs_per_scan": self.config.matching.max_ai_jobs_per_scan,
                },
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
            }
            sources_succeeded = any(value.startswith("ok:") for value in source_status.values())
            status = "success" if sources_succeeded else "no_sources_succeeded"
            if sources_succeeded and ai_failed:
                status = "partial_ai_failure"
            summary["run_status"] = status
            self.store.finish_run(run_id, status, summary)
            return summary
        except Exception as exc:
            self.store.finish_run(run_id, "failed", {"error_type": type(exc).__name__})
            raise
        finally:
            if publisher is not None:
                publisher.close()
            if ai_matcher is not None:
                ai_matcher.close()
