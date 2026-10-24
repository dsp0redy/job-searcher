"""Adapter for public Lever postings."""
from __future__ import annotations
from urllib.parse import quote
from .base import JobSource
from ..models import Job


class LeverAdapter(JobSource):
    name = "lever"
    def __init__(self, site_slugs: list[str], timeout: float = 20) -> None:
        super().__init__(timeout)
        self.site_slugs = site_slugs
    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        for slug in self.site_slugs:
            if not slug.strip():
                continue
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
                    jobs.append(Job(source=self.name, source_id=str(item["id"]), company=slug,
                        title=str(item["text"]), location=str(location), url=item["hostedUrl"],
                        description=description, posted_at=None))
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Lever site %s failed; continuing", slug)
        return jobs
