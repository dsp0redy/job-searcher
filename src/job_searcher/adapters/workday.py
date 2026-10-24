"""Adapter for public Workday career sites using their published CXS endpoints.

This is an adapter for compatible public Workday career pages, not a universal
crawler. It uses the site's public job-search and posting-detail endpoints.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import urlparse

from .base import JobSource
from ..models import Job

LOG = logging.getLogger(__name__)
_LOCALE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")
_RELATIVE_POSTED = re.compile(r"(today|yesterday|(?:posted\s*)?(\d+)\+?\s*days?\s*ago)", re.I)


class WorkdayAdapter(JobSource):
    name = "workday"

    def __init__(self, career_urls: list[str], timeout: float = 20, max_pages: int = 5, detail_limit: int = 12) -> None:
        super().__init__(timeout)
        self.career_urls = career_urls
        self.max_pages = max_pages
        self.detail_limit = max(0, detail_limit)
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
        days = 0 if lowered == "today" else 1 if lowered == "yesterday" else int(match.group(2))
        return datetime.now(timezone.utc) - timedelta(days=days)

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        seen: set[tuple[str, str]] = set()
        for career_url in self.career_urls:
            try:
                host, tenant, site = self.parse_career_url(career_url)
            except ValueError as exc:
                self.site_status[career_url] = f"failed: invalid URL ({type(exc).__name__})"
                LOG.warning("Skipping invalid Workday URL %r: %s", career_url, exc)
                continue

            site_succeeded = False
            site_start_count = len(jobs)
            company = tenant.replace("-", " ").replace("_", " ").title()
            endpoint = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
            details_fetched = 0
            for page in range(self.max_pages):
                try:
                    response = self.client.post(
                        endpoint,
                        json={"appliedFacets": {}, "limit": 20, "offset": page * 20, "searchText": ""},
                    )
                    response.raise_for_status()
                    payload = response.json()
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
                    source_id = str(item.get("jobReqId") or item.get("jobRequisitionId") or path).strip()
                    detail_url = f"https://{host}/wday/cxs/{tenant}/{site}{path}"
                    description = ""
                    posted_at = self._parse_posted_at(item.get("postedOn"))
                    employment_type = None
                    try:
                        if details_fetched >= self.detail_limit:
                            raise RuntimeError("Per-site detail request limit reached")
                        detail_response = self.client.get(detail_url)
                        details_fetched += 1
                        detail_response.raise_for_status()
                        detail = detail_response.json()
                        info = detail.get("jobPostingInfo", {}) if isinstance(detail, dict) else {}
                        if isinstance(info, dict):
                            source_id = str(info.get("jobReqId") or info.get("jobRequisitionId") or source_id)
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
                        url=f"https://{host}{path}",
                        description=description[:100_000],
                        posted_at=posted_at,
                        employment_type=str(employment_type) if employment_type else None,
                    ))
                total = payload.get("total")
                if len(postings) < 20 or (isinstance(total, int) and (page + 1) * 20 >= total):
                    break
            count = len(jobs) - site_start_count
            self.site_status[tenant] = (
                f"ok: {count} postings" if site_succeeded
                else "failed: no successful job-search response"
            )
        return jobs
