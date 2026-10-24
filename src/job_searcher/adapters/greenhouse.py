"""Adapter for public Greenhouse job boards."""
from __future__ import annotations
from urllib.parse import quote
from .base import JobSource
from ..models import Job


class GreenhouseAdapter(JobSource):
    name = "greenhouse"
    def __init__(self, board_tokens: list[str], timeout: float = 20) -> None:
        super().__init__(timeout)
        self.board_tokens = board_tokens
    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        for board in self.board_tokens:
            if not board.strip():
                continue
            url = f"https://boards-api.greenhouse.io/v1/boards/{quote(board, safe='')}/jobs"
            try:
                data = self.get_json(url, {"content": "true"})
                if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
                    raise ValueError("Unexpected Greenhouse response schema")
                for item in data["jobs"]:
                    if not isinstance(item, dict) or not item.get("id") or not item.get("title") or not item.get("absolute_url"):
                        continue
                    location = item.get("location") or {}
                    jobs.append(Job(source=self.name, source_id=str(item["id"]), company=board,
                        title=str(item["title"]), location=str(location.get("name", "Unknown")),
                        url=item["absolute_url"], description=str(item.get("content") or ""),
                        posted_at=None  # updated_at is not the original publication date))
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Greenhouse board %s failed; continuing", board)
        return jobs
