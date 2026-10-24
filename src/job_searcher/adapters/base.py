"""Shared adapter contract and HTTP safety helpers."""
from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from ..models import Job


class JobSource(ABC):
    name: str

    def __init__(self, timeout: float = 20) -> None:
        transport = httpx.HTTPTransport(retries=2)
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
            headers={"User-Agent": "job-searcher/0.1 (+personal job discovery)"},
        )

    @abstractmethod
    def fetch(self) -> list[Job]:
        """Return normalized jobs from a configured source."""

    def close(self) -> None:
        self.client.close()

    def get_json(self, url: str, params: dict[str, str] | None = None) -> object:
        response = self.client.get(url, params=params)
        response.raise_for_status()
        return response.json()
