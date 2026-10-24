"""Coordinates adapters, persistence, matching, and report generation."""
from __future__ import annotations
import logging
from typing import Any
from .adapters.greenhouse import GreenhouseAdapter
from .adapters.lever import LeverAdapter
from .config import AppConfig
from .matching import score_job
from .models import Job
from .reporting import write_reports
from .storage import JobStore

LOG = logging.getLogger(__name__)


class SearchOrchestrator:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.store = JobStore(config.storage.path)

    def run(self, output_dir: str = "reports") -> dict[str, Any]:
        run_id = self.store.start_run()
        adapters = [GreenhouseAdapter(self.config.sources.greenhouse, self.config.search.request_timeout_seconds),
                    LeverAdapter(self.config.sources.lever, self.config.search.request_timeout_seconds)]
        all_jobs: list[Job] = []
        source_status: dict[str, str] = {}
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
            for job in all_jobs:
                match = score_job(job, self.config.profile)
                if int(match["score"]) < self.config.search.minimum_local_score:
                    continue
                rows.append({"source": job.source, "source_id": job.source_id, "company": job.company,
                    "title": job.title, "location": job.location, "url": str(job.url),
                    "posted_at": job.posted_at.isoformat() if job.posted_at else None,
                    "score": match["score"], "reason": match["reason"],
                    "title_hits": match["title_hits"], "location_hits": match["location_hits"],
                    "skill_hits": match["skill_hits"]})
            paths = write_reports(output_dir, run_id, rows)
            summary = {"run_id": run_id, "sources": source_status, "postings_fetched": len(all_jobs),
                       "new_identities": inserted, "qualified_candidates": len(rows),
                       "reports": [str(p) for p in paths], "matching": "deterministic local scoring"}
            status = "success" if any(v.startswith("ok:") for v in source_status.values()) else "no_sources_succeeded"
            self.store.finish_run(run_id, status, summary)
            return summary
        except Exception as exc:
            self.store.finish_run(run_id, "failed", {"error_type": type(exc).__name__})
            raise
