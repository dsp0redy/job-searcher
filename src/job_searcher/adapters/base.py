"""Shared adapter contract, host pacing, and bounded HTTP retry helpers."""
from __future__ import annotations

import random
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from ..models import Job

_HOST_LOCK = threading.Lock()
_HOST_NEXT_REQUEST: dict[str, float] = {}


class JobSource(ABC):
    name: str
    MAX_ATTEMPTS = 3
    MAX_RETRY_DELAY_SECONDS = 30.0
    MIN_HOST_INTERVAL_SECONDS = 0.15
    RETRY_JITTER_SECONDS = 0.25

    def __init__(self, timeout: float = 20) -> None:
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

    @staticmethod
    def _wait_for_host(url: str) -> None:
        """Pace requests to the same host across adapter instances in this process."""
        host = urlparse(url).netloc.casefold()
        if not host:
            return
        now = time.monotonic()
        with _HOST_LOCK:
            next_allowed = _HOST_NEXT_REQUEST.get(host, now)
            wait = max(0.0, next_allowed - now)
            _HOST_NEXT_REQUEST[host] = max(now, next_allowed) + JobSource.MIN_HOST_INTERVAL_SECONDS
        if wait > 0:
            time.sleep(wait)

    def request_json(
        self,
        method: str,
        url: str,
        params: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> object:
        """Perform a GET/POST JSON request with host pacing and bounded transient retries."""
        for attempt in range(self.MAX_ATTEMPTS):
            self._wait_for_host(url)
            try:
                if method.upper() == "GET":
                    response = self.client.get(url, params=params)
                else:
                    response = self.client.post(url, params=params, json=json_body)
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
            jitter = random.uniform(0.0, min(self.RETRY_JITTER_SECONDS, delay * 0.1))
            time.sleep(min(delay + jitter, self.MAX_RETRY_DELAY_SECONDS))
        raise RuntimeError("HTTP retries exhausted")

    def get_json(self, url: str, params: dict[str, str] | None = None) -> object:
        """Fetch JSON with bounded retries for transient network and HTTP failures."""
        return self.request_json("GET", url, params=params)
