from __future__ import annotations

import pytest

from job_searcher.adapters.workday import WorkdayAdapter


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
         ("nvidia.wd5.myworkdayjobs.com", "nvidia", "NVIDIAExternalCareerSite")),
        ("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite",
         ("nvidia.wd5.myworkdayjobs.com", "nvidia", "NVIDIAExternalCareerSite")),
    ],
)
def test_parse_career_url(url: str, expected: tuple[str, str, str]) -> None:
    assert WorkdayAdapter.parse_career_url(url) == expected


@pytest.mark.parametrize("url", [
    "http://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
    "https://example.com/careers",
    "https://nvidia.wd5.myworkdayjobs.com/",
])
def test_parse_career_url_rejects_non_workday_or_incomplete_urls(url: str) -> None:
    with pytest.raises(ValueError):
        WorkdayAdapter.parse_career_url(url)


def test_plain_text_removes_markup_and_normalizes_whitespace() -> None:
    assert WorkdayAdapter._plain_text("<p>C++ Engineer</p>\n <b>Linux</b>") == "C++ Engineer Linux"

def test_parse_workday_relative_posting_date() -> None:
    from datetime import datetime, timezone

    parsed = WorkdayAdapter._parse_posted_at("Posted 2 Days Ago")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert (datetime.now(timezone.utc) - parsed).days in {1, 2}


def test_parse_workday_iso_posting_date() -> None:
    parsed = WorkdayAdapter._parse_posted_at("2026-10-20T12:30:00Z")
    assert parsed is not None
    assert parsed.isoformat() == "2026-10-20T12:30:00+00:00"


def test_unknown_workday_posting_date_is_not_a_fake_timestamp() -> None:
    assert WorkdayAdapter._parse_posted_at("Posted recently") is None


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


def test_fetch_normalizes_listing_and_detail_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = WorkdayAdapter(
        ["https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"],
        max_pages=1,
    )
    listing = {
        "jobPostings": [{
            "externalPath": "/job/Software-Engineer_REQ-123",
            "title": "C++ Software Engineer",
            "locationsText": "Bengaluru, India",
            "postedOn": "Posted Today",
        }],
        "total": 1,
    }
    detail = {
        "jobPostingInfo": {
            "jobReqId": "REQ-123",
            "jobDescription": "<p>C++ systems role</p>",
            "postedOn": "Posted Today",
            "location": "Bengaluru",
            "additionalLocations": [{"location": "Hyderabad"}],
            "timeType": "Full time",
        }
    }
    monkeypatch.setattr(adapter.client, "post", lambda *args, **kwargs: FakeResponse(listing))
    monkeypatch.setattr(adapter.client, "get", lambda *args, **kwargs: FakeResponse(detail))
    try:
        jobs = adapter.fetch()
    finally:
        adapter.close()

    assert len(jobs) == 1
    assert jobs[0].source_id == "REQ-123"
    assert jobs[0].title == "C++ Software Engineer"
    assert jobs[0].location == "Bengaluru | Hyderabad"
    assert jobs[0].description == "C++ systems role"
    assert jobs[0].posted_at is not None
    assert adapter.site_status["nvidia"] == "ok: 1 postings"


def test_fetch_records_failed_site_status(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = WorkdayAdapter(
        ["https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"],
        max_pages=1,
    )

    def fail_request(*args: object, **kwargs: object) -> FakeResponse:
        raise RuntimeError("site unavailable")

    monkeypatch.setattr(adapter.client, "post", fail_request)
    try:
        assert adapter.fetch() == []
        assert adapter.site_status["nvidia"] == "failed: no successful job-search response"
    finally:
        adapter.close()


def test_fetch_obeys_detail_request_cap_and_keeps_listing_date(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = WorkdayAdapter(
        ["https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"],
        max_pages=1,
        detail_limit=0,
    )
    listing = {
        "jobPostings": [{
            "externalPath": "/job/Software-Engineer_REQ-123",
            "title": "C++ Software Engineer",
            "locationsText": "Bengaluru, India",
            "postedOn": "Posted Today",
        }],
        "total": 1,
    }
    monkeypatch.setattr(adapter.client, "post", lambda *args, **kwargs: FakeResponse(listing))
    monkeypatch.setattr(adapter.client, "get", lambda *args, **kwargs: pytest.fail("detail request should be capped"))
    try:
        jobs = adapter.fetch()
    finally:
        adapter.close()

    assert len(jobs) == 1
    assert jobs[0].description == ""
    assert jobs[0].posted_at is not None
