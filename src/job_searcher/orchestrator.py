"""Coordinates source adapters, local/AI matching, persistence, and reports."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .adapters.greenhouse import GreenhouseAdapter
from .adapters.lever import LeverAdapter
from .adapters.workday import WorkdayAdapter
from .ai_matching import AIResumeMatcher, MatchResult
from .config import AppConfig
from .matching import (
    extract_experience_range,
    is_allowed_location,
    is_experience_compatible,
    is_too_senior,
    score_job,
)
from .models import Job
from .notifications import GitHubIssuePublisher
from .reporting import prune_old_reports, write_digest, write_reports
from .storage import JobStore

LOG = logging.getLogger(__name__)


class SearchOrchestrator:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.store = JobStore(config.storage.path)

    def run(self, output_dir: str = "reports") -> dict[str, Any]:
        started_monotonic = time.monotonic()
        run_id = self.store.start_run()
        timeout = self.config.search.request_timeout_seconds
        ai_matcher: AIResumeMatcher | None = None
        publisher: GitHubIssuePublisher | None = None
        ai_initialization_failed = False
        try:
            retention_summary = self.store.prune_old_data(self.config.storage.retention_days)
            old_reports_pruned = prune_old_reports(output_dir, self.config.search.report_retention_days)
            provider = self.config.matching.provider.casefold()
            if provider != "none":
                try:
                    ai_matcher = AIResumeMatcher(provider, timeout)
                except Exception as exc:
                    # AI is optional: continue discovering/reporting jobs with local scoring.
                    ai_initialization_failed = True
                    LOG.error("AI matcher initialization failed (%s); continuing with local scoring", type(exc).__name__)

            adapters = [
                GreenhouseAdapter(self.config.sources.greenhouse, timeout),
                LeverAdapter(self.config.sources.lever, timeout),
                WorkdayAdapter(
                    self.config.sources.workday,
                    timeout,
                    self.config.search.max_pages_per_source,
                    detail_limit=self.config.search.workday_detail_limit,
                    search_terms=self.config.search.workday_search_terms,
                    max_workers=self.config.search.max_concurrency,
                ),
            ]
            all_jobs: list[Job] = []
            source_status: dict[str, str] = {}
            for adapter in adapters:
                try:
                    found = adapter.fetch()
                    all_jobs.extend(found)
                    if adapter.name == "workday" and not self.config.sources.workday:
                        source_status[adapter.name] = "skipped: no Workday sites configured"
                    elif adapter.name == "workday":
                        site_status = getattr(adapter, "site_status", {})
                        successful_sites = sum(value.startswith("ok:") for value in site_status.values())
                        source_status[adapter.name] = (
                            f"ok: {len(found)} postings; {successful_sites}/{len(site_status)} sites responded"
                            if successful_sites
                            else f"failed: 0/{len(site_status)} Workday sites responded"
                        )
                        for site, site_result in site_status.items():
                            source_status[f"workday:{site}"] = site_result
                    elif adapter.name == "greenhouse" and not getattr(adapter, "board_tokens", []):
                        source_status[adapter.name] = "skipped: no Greenhouse boards configured"
                    elif adapter.name == "lever" and not getattr(adapter, "site_slugs", []):
                        source_status[adapter.name] = "skipped: no Lever sites configured"
                    elif adapter.name in {"greenhouse", "lever"} and getattr(adapter, "site_status", {}):
                        site_status = getattr(adapter, "site_status", {})
                        successful_sites = sum(value.startswith("ok:") for value in site_status.values())
                        source_status[adapter.name] = (
                            f"ok: {len(found)} postings; {successful_sites}/{len(site_status)} sites responded"
                            if successful_sites else f"failed: 0/{len(site_status)} sites responded"
                        )
                        for site, site_result in site_status.items():
                            source_status[f"{adapter.name}:{site}"] = site_result
                    else:
                        source_status[adapter.name] = f"ok: {len(found)} postings"
                except Exception as exc:
                    source_status[adapter.name] = f"failed: {type(exc).__name__}"
                    LOG.exception("Source %s failed; continuing other sources", adapter.name)
                finally:
                    adapter.close()

            fetched_count = len(all_jobs)
            # Multiple configured boards/sites can return the same posting. Keep the
            # latest occurrence while ensuring it is scored and reported only once.
            unique_jobs = {job.identity: job for job in all_jobs}
            all_jobs = list(unique_jobs.values())
            inserted = self.store.upsert_jobs(all_jobs)
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.search.posted_within_days)
            candidates: list[tuple[Job, dict[str, Any]]] = []
            experience_evidence: dict[str, dict[str, float | None]] = {}
            excluded_by_location = 0
            excluded_by_freshness = 0
            excluded_by_experience = 0
            excluded_by_seniority = 0
            excluded_by_review = 0
            reviewed = self.store.review_statuses([job.identity for job in all_jobs])
            for job in all_jobs:
                if reviewed.get(job.identity) in {"applied", "rejected"}:
                    excluded_by_review += 1
                    continue
                if is_too_senior(job.title, self.config.profile):
                    excluded_by_seniority += 1
                    continue
                if not is_allowed_location(job.location, self.config.profile):
                    excluded_by_location += 1
                    continue
                if job.posted_at and job.posted_at < cutoff:
                    excluded_by_freshness += 1
                    continue
                required_min, required_max = job.experience_min, job.experience_max
                if required_min is None and required_max is None:
                    required_min, required_max = extract_experience_range(f"{job.title}\n{job.description}")
                if not is_experience_compatible(required_min, required_max, self.config.profile):
                    excluded_by_experience += 1
                    continue
                experience_evidence[job.identity] = {
                    "minimum_years": required_min,
                    "maximum_years": required_max,
                }
                local_match = score_job(job, self.config.profile)
                if int(local_match["score"]) >= self.config.search.minimum_local_score:
                    candidates.append((job, local_match))

            ai_results: dict[str, MatchResult] = {}
            ai_failed: set[str] = (
                {job.identity for job, _ in candidates} if ai_initialization_failed else set()
            )
            ai_deferred: set[str] = set()
            ai_cached = 0
            ai_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            if ai_matcher is not None:
                ranked = sorted(candidates, key=lambda pair: int(pair[1]["score"]), reverse=True)
                ai_limit = self.config.matching.max_ai_jobs_per_scan
                uncached: list[Job] = []
                for job, _ in ranked:
                    key = ai_matcher.cache_key(job)
                    cached = self.store.get_match(key)
                    if cached is not None:
                        try:
                            result = MatchResult.model_validate(cached)
                            if result.job_id == job.identity:
                                # Cache hits cost nothing, so they never use up the paid budget.
                                ai_results[job.identity] = result
                                ai_cached += 1
                                continue
                        except Exception:
                            LOG.info("Ignoring invalid cached AI result for %s", job.identity)
                    if len(uncached) < ai_limit:
                        uncached.append(job)
                    else:
                        ai_deferred.add(job.identity)

                batch_size = self.config.matching.max_jobs_per_ai_batch
                for offset in range(0, len(uncached), batch_size):
                    batch = uncached[offset:offset + batch_size]
                    results = ai_matcher.match_batch(batch)
                    usage = getattr(ai_matcher, "last_usage", {})
                    for token_key in ai_usage:
                        token_value = usage.get(token_key, 0) if isinstance(usage, dict) else 0
                        if isinstance(token_value, int) and not isinstance(token_value, bool) and token_value >= 0:
                            ai_usage[token_key] += token_value
                    ai_results.update(results)
                    for job in batch:
                        batch_result = results.get(job.identity)
                        if batch_result is None:
                            ai_failed.add(job.identity)
                        else:
                            self.store.save_match(
                                ai_matcher.cache_key(job), provider, batch_result.model_dump()
                            )

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
                    ai_status = "failed" if provider != "none" else "disabled"
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
                    "identity": job.identity,
                    "source": job.source,
                    "source_id": job.source_id,
                    "company": job.company,
                    "title": job.title,
                    "location": job.location,
                    "url": str(job.url),
                    "posted_at": job.posted_at.isoformat() if job.posted_at else None,
                    "freshness_status": "undated" if job.posted_at is None else "within_configured_window",
                    "experience_requirement": experience_evidence.get(job.identity, {
                        "minimum_years": None, "maximum_years": None,
                    }),
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

                ai_eligible = provider == "none" or ai_status == "matched"
                if notify_enabled and ai_eligible and score >= self.config.matching.threshold:
                    if publisher is None:
                        row["notification"] = "not_configured"
                    else:
                        publish_result = publisher.publish(
                            job,
                            score,
                            reason,
                            matched_skills,
                            missing_skills=missing_skills,
                            improvements=improvements,
                        )
                        row["notification"] = publish_result["status"]
                        notification_results.append({
                            "company": job.company,
                            "title": job.title,
                            "score": score,
                            **publish_result,
                        })
                elif notify_enabled and provider != "none" and ai_status in {"failed", "deferred"}:
                    row["notification"] = f"ai_{ai_status}"

                rows.append(row)

            paths = (*write_reports(output_dir, run_id, rows), write_digest(output_dir, run_id, rows))
            input_rate = self.config.matching.input_cost_usd_per_million_tokens
            output_rate = self.config.matching.output_cost_usd_per_million_tokens
            estimated_ai_cost = (
                (ai_usage["input_tokens"] * input_rate + ai_usage["output_tokens"] * output_rate) / 1_000_000
                if input_rate is not None and output_rate is not None else None
            )
            summary: dict[str, Any] = {
                "run_id": run_id,
                "retention": {**retention_summary, "reports": old_reports_pruned},
                "sources": source_status,
                "postings_fetched": fetched_count,
                "new_identities": inserted,
                "qualified_candidates": len(rows),
                "excluded_by_location": excluded_by_location,
                "excluded_by_freshness": excluded_by_freshness,
                "excluded_by_experience": excluded_by_experience,
                "excluded_by_seniority": excluded_by_seniority,
                "excluded_by_review": excluded_by_review,
                "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
                "source_health": {
                    "successful": sum(source_status.get(name, "").startswith("ok:") for name in ("greenhouse", "lever", "workday")),
                    "failed": sum(source_status.get(name, "").startswith("failed:") for name in ("greenhouse", "lever", "workday")),
                    "skipped": sum(source_status.get(name, "").startswith("skipped:") for name in ("greenhouse", "lever", "workday")),
                },
                "matching": provider if ai_matcher else (
                    "deterministic local scoring (AI unavailable)" if provider != "none"
                    else "deterministic local scoring"
                ),
                "ai": {
                    "enabled": ai_matcher is not None,
                    "requested": provider != "none",
                    "initialization_failed": ai_initialization_failed,
                    "scored": len(ai_results) - ai_cached,
                    "matched_including_cache": len(ai_results),
                    "cached": ai_cached,
                    "failed": len(ai_failed),
                    "deferred_by_scan_limit": len(ai_deferred),
                    "max_jobs_per_scan": self.config.matching.max_ai_jobs_per_scan,
                    "token_usage": ai_usage,
                    "estimated_cost_usd": round(estimated_ai_cost, 8) if estimated_ai_cost is not None else None,
                    "cost_estimate_configured": input_rate is not None and output_rate is not None,
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
            if sources_succeeded and (ai_failed or ai_initialization_failed):
                status = "partial_ai_failure"
            elif sources_succeeded and summary["notifications"]["failed"] > 0:
                status = "partial_notification_failure"
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
