"""Adapter for public Workday career sites using their published CXS endpoints.

This is an adapter for compatible public Workday career pages, not a universal
crawler. It uses the site's public job-search and posting-detail endpoints.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from typing import Any, cast

from pydantic import HttpUrl

from .base import JobSource
from ..models import Job

LOG = logging.getLogger(__name__)
_LOCALE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")
_RELATIVE_POSTED = re.compile(r"(today|yesterday|(?:posted\s*)?(\d+)\+?\s*days?\s*ago)", re.I)


class WorkdayAdapter(JobSource):
    name = "workday"

    def __init__(
        self,
        career_urls: list[str],
        timeout: float = 20,
        max_pages: int = 5,
        detail_limit: int = 12,
        search_terms: list[str] | None = None,
        max_workers: int = 1,
    ) -> None:
        super().__init__(timeout)
        self.career_urls = career_urls
        self.max_pages = max_pages
        self.detail_limit = max(0, detail_limit)
        # Workday's listing endpoint is unfiltered by default and returns the newest
        # postings worldwide; search terms (e.g. city names) narrow it server-side.
        self.search_terms = [t.strip() for t in (search_terms or []) if t.strip()] or [""]
        self.max_workers = max(1, max_workers)
        self.site_status: dict[str, str] = {}

    @staticmethod
    def parse_career_url(url: str) -> tuple[str, str, str]:
        """Return (host, tenant, site) for a normal Workday career-site URL."""
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if parsed.scheme != "https" or not host.endswith(".myworkdayjobs.com"):
            raise ValueError("Expected an HTTPS *.myworkdayjobs.com career-site URL")
        parts = [part for part in parsed.path.split("/") if part]
        if parts and _LOCALE.fullmatch(parts[0]):
            parts.pop(0)
        if not parts:
            raise ValueError("Workday career URL must include a site slug")
        tenant = host.split(".", 1)[0]
        return host, tenant, parts[0]

    @staticmethod
    def _stable_source_id(item: dict[str, Any], path: str) -> str:
        """Return an ID that depends only on the listing row, never on whether a detail
        request happened to be made, so a posting keeps one identity across scans."""
        listed = str(item.get("jobReqId") or item.get("jobRequisitionId") or "").strip()
        if listed:
            return listed
        last_segment = path.rstrip("/").rsplit("/", 1)[-1]
        if "_" in last_segment:
            trailing = last_segment.rsplit("_", 1)[-1]
            if any(char.isdigit() for char in trailing):
                return trailing
        return path

    @staticmethod
    def _plain_text(value: object) -> str:
        text = re.sub(r"<[^>]+>", " ", str(value or ""))
        return re.sub(r"\s+", " ", unescape(text)).strip()

    @staticmethod
    def _parse_posted_at(value: object) -> datetime | None:
        """Parse ISO dates and Workday's relative labels; leave unknown dates unset."""
        if not value:
            return None
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        except ValueError:
            pass
        match = _RELATIVE_POSTED.search(text)
        if not match:
            return None
        lowered = match.group(1).casefold()
        try:
            days = 0 if lowered == "today" else 1 if lowered == "yesterday" else int(match.group(2))
            return datetime.now(timezone.utc) - timedelta(days=days)
        except (OverflowError, ValueError):
            # A malformed or absurd relative date should not abort an entire source scan.
            return None

    def fetch(self) -> list[Job]:
        if not self.career_urls:
            return []
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(self.career_urls))) as pool:
            results = list(pool.map(self._fetch_site, self.career_urls))
        jobs: list[Job] = []
        seen: set[str] = set()
        for site_jobs, status_key, status in results:
            self.site_status[status_key] = status
            for job in site_jobs:
                if job.identity not in seen:
                    seen.add(job.identity)
                    jobs.append(job)
        return jobs

    def _fetch_site(self, career_url: str) -> tuple[list[Job], str, str]:
        try:
            host, tenant, site = self.parse_career_url(career_url)
        except ValueError as exc:
            LOG.warning("Skipping invalid Workday URL %r: %s", career_url, exc)
            return [], career_url, f"failed: invalid URL ({type(exc).__name__})"

        jobs: list[Job] = []
        seen: set[tuple[str, str]] = set()
        site_succeeded = False
        company = tenant.replace("-", " ").replace("_", " ").title()
        endpoint = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        details_fetched = 0
        for term in self.search_terms:
            for page in range(self.max_pages):
                try:
                    payload = self.request_json(
                        "POST",
                        endpoint,
                        json_body={"appliedFacets": {}, "limit": 20, "offset": page * 20, "searchText": term},
                    )
                    if not isinstance(payload, dict) or not isinstance(payload.get("jobPostings"), list):
                        raise ValueError("Unexpected Workday job-search response schema")
                    site_succeeded = True
                except Exception as exc:
                    LOG.warning("Workday site %s failed on page %d (%s)", tenant, page + 1, type(exc).__name__)
                    break

                postings = payload["jobPostings"]
                if not postings:
                    break
                for item in postings:
                    if not isinstance(item, dict):
                        continue
                    path = str(item.get("externalPath") or "").strip()
                    title = str(item.get("title") or "").strip()
                    if not path or not title or not path.startswith("/"):
                        continue
                    identity = (tenant.casefold(), path.casefold())
                    if identity in seen:
                        continue
                    seen.add(identity)
                    source_id = self._stable_source_id(item, path)
                    detail_url = f"https://{host}/wday/cxs/{tenant}/{site}{path}"
                    description = ""
                    posted_at = self._parse_posted_at(item.get("postedOn"))
                    employment_type = None
                    try:
                        if details_fetched >= self.detail_limit:
                            raise RuntimeError("Per-site detail request limit reached")
                        details_fetched += 1
                        detail = self.request_json("GET", detail_url)
                        info = detail.get("jobPostingInfo", {}) if isinstance(detail, dict) else {}
                        if isinstance(info, dict):
                            description = self._plain_text(info.get("jobDescription"))
                            detail_posted_at = self._parse_posted_at(info.get("postedOn"))
                            if detail_posted_at is not None:
                                posted_at = detail_posted_at
                            employment_type = info.get("timeType")
                            locations = [info.get("location", "")]
                            for extra in info.get("additionalLocations") or []:
                                if isinstance(extra, dict):
                                    locations.append(extra.get("location") or extra.get("descriptor") or "")
                                elif extra:
                                    locations.append(str(extra))
                            location = " | ".join(str(x).strip() for x in locations if x) or str(item.get("locationsText") or "Unknown")
                        else:
                            location = str(item.get("locationsText") or "Unknown")
                    except Exception as exc:
                        if not isinstance(exc, RuntimeError):
                            LOG.info("Workday details unavailable for %s (%s); using listing fields", path, type(exc).__name__)
                        location = str(item.get("locationsText") or "Unknown")

                    jobs.append(Job(
                        source=self.name,
                        source_id=source_id[:300],
                        company=company[:200],
                        title=title[:300],
                        location=location[:300] or "Unknown",
                        url=cast(HttpUrl, f"https://{host}{path}"),
                        description=description[:100_000],
                        posted_at=posted_at,
                        employment_type=str(employment_type) if employment_type else None,
                    ))
                total = payload.get("total")
                if len(postings) < 20 or (isinstance(total, int) and (page + 1) * 20 >= total):
                    break
        status = (
            f"ok: {len(jobs)} postings" if site_succeeded
            else "failed: no successful job-search response"
        )
        return jobs, f"{tenant}/{site}", status
