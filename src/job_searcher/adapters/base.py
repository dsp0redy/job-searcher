"""Shared adapter contract and bounded HTTP retry helpers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from ..models import Job


class JobSource(ABC):
    name: str
    MAX_ATTEMPTS = 3
    MAX_RETRY_DELAY_SECONDS = 30.0

    def __init__(self, timeout: float = 20) -> None:
        # Retries are explicit below so HTTP status codes and Retry-After are handled too.
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "job-searcher/0.1 (+personal job discovery)"},
        )

    @abstractmethod
    def fetch(self) -> list[Job]:
        """Return normalized jobs from a configured source."""

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        """Return a bounded Retry-After delay, falling back to exponential backoff."""
        fallback = float(min(2**attempt, 8))
        value = response.headers.get("Retry-After")
        if not value:
            return fallback
        try:
            delay = float(value)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return fallback
        return min(max(delay, 0.0), JobSource.MAX_RETRY_DELAY_SECONDS)

    def get_json(self, url: str, params: dict[str, str] | None = None) -> object:
        """Fetch JSON with bounded retries for transient network and HTTP failures."""
        for attempt in range(self.MAX_ATTEMPTS):
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                retryable = status == 429 or 500 <= status <= 599
                if not retryable or attempt == self.MAX_ATTEMPTS - 1:
                    raise
                delay = self._retry_delay(exc.response, attempt)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == self.MAX_ATTEMPTS - 1:
                    raise
                delay = float(min(2**attempt, 8))
            import time
            time.sleep(delay)
        raise RuntimeError("HTTP retries exhausted")
