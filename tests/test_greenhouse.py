from __future__ import annotations

import pytest

from job_searcher.adapters.greenhouse import GreenhouseAdapter


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


def test_fetch_does_not_use_updated_at_as_original_posting_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = GreenhouseAdapter(["example-board"])
    payload = {
        "jobs": [
            {
                "id": 123,
                "title": "C++ Engineer",
                "absolute_url": "https://example.com/jobs/123",
                "updated_at": "2026-10-24T10:00:00Z",
                "location": {"name": "Bengaluru"},
                "content": "C++ Linux",
            }
        ]
    }
    monkeypatch.setattr(adapter.client, "get", lambda *args, **kwargs: FakeResponse(payload))
    try:
        jobs = adapter.fetch()
    finally:
        adapter.close()

    assert len(jobs) == 1
    assert jobs[0].posted_at is None
