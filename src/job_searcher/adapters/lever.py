"""Adapter for public Lever postings."""
from __future__ import annotations
from datetime import datetime, timezone
from urllib.parse import quote
from .base import JobSource
from ..models import Job


class LeverAdapter(JobSource):
    name = "lever"
    def __init__(self, site_slugs: list[str], timeout: float = 20) -> None:
        super().__init__(timeout)
        self.site_slugs = site_slugs
        self.site_status: dict[str, str] = {}
    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        for slug in self.site_slugs:
            if not slug.strip():
                continue
            before_count = len(jobs)
            try:
                data = self.get_json(f"https://api.lever.co/v0/postings/{quote(slug, safe='')}", {"mode": "json"})
                if not isinstance(data, list):
                    raise ValueError("Unexpected Lever response schema")
                for item in data:
                    if not isinstance(item, dict) or item.get("id") is None or not item.get("text") or not item.get("hostedUrl"):
                        continue
                    categories = item.get("categories") or {}
                    location = categories.get("location") or "Unknown"
                    description = "\n".join(str(item.get(key) or "") for key in
                        ("descriptionPlain", "additionalPlain"))
                    created_at = item.get("createdAt")
                    posted_at = None
                    if isinstance(created_at, (int, float)) and not isinstance(created_at, bool):
                        try:
                            posted_at = datetime.fromtimestamp(float(created_at) / 1000, tz=timezone.utc)
                        except (OverflowError, OSError, ValueError):
                            posted_at = None
                    jobs.append(Job(source=self.name, source_id=str(item["id"]), company=slug,
                        title=str(item["text"]), location=str(location), url=item["hostedUrl"],
                        description=description, posted_at=posted_at))
                self.site_status[slug] = f"ok: {len(jobs) - before_count} postings"
            except Exception as exc:
                self.site_status[slug] = f"failed: {type(exc).__name__}"
                import logging
                logging.getLogger(__name__).exception("Lever site %s failed; continuing", slug)
        return jobs
