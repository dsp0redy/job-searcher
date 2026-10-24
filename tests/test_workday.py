from __future__ import annotations

import pytest

from job_searcher.adapters.workday import WorkdayAdapter


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
         ("nvidia.wd5.myworkdayjobs.com", "nvidia", "NVIDIAExternalCareerSite")),
        ("https://nvidia.wd5.myworkdayjobs.com/en-US/AnotherCareerSite",
         ("nvidia.wd5.myworkdayjobs.com", "nvidia", "AnotherCareerSite")),
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
    assert adapter.site_status["nvidia/NVIDIAExternalCareerSite"] == "ok: 1 postings"


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
        assert adapter.site_status["nvidia/NVIDIAExternalCareerSite"] == "failed: no successful job-search response"
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

def test_start_date_is_not_used_as_posting_date(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = WorkdayAdapter(
        ["https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"],
        max_pages=1,
    )
    listing = {
        "jobPostings": [{
            "externalPath": "/job/Software-Engineer_REQ-123",
            "title": "C++ Software Engineer",
            "locationsText": "Bengaluru, India",
        }],
        "total": 1,
    }
    detail = {
        "jobPostingInfo": {
            "jobReqId": "REQ-123",
            "jobDescription": "C++ systems role",
            "startDate": "2026-10-24T00:00:00Z",
            "location": "Bengaluru",
        }
    }
    monkeypatch.setattr(adapter.client, "post", lambda *args, **kwargs: FakeResponse(listing))
    monkeypatch.setattr(adapter.client, "get", lambda *args, **kwargs: FakeResponse(detail))
    try:
        jobs = adapter.fetch()
    finally:
        adapter.close()

    assert len(jobs) == 1
    assert jobs[0].posted_at is None

def test_plain_text_handles_empty_and_non_string_values() -> None:
    assert WorkdayAdapter._plain_text(None) == ""
    assert WorkdayAdapter._plain_text(0) == ""
    assert WorkdayAdapter._plain_text("  plain   text  ") == "plain text"


@pytest.mark.parametrize(("value", "expected_days"), [
    ("today", 0), ("Yesterday", 1), ("posted 3 days ago", 3),
])
def test_parse_relative_date_variants(value: str, expected_days: int) -> None:
    from datetime import datetime, timezone
    parsed = WorkdayAdapter._parse_posted_at(value)
    assert parsed is not None
    assert 0 <= (datetime.now(timezone.utc) - parsed).total_seconds() <= expected_days * 86400 + 2


def test_fetch_skips_invalid_url_and_empty_or_malformed_listings(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = WorkdayAdapter([
        "not a url",
        "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
    ], max_pages=2)
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs["json"]["offset"])
        return FakeResponse({"jobPostings": []} if len(calls) == 1 else {"unexpected": []})
    monkeypatch.setattr(adapter.client, "post", post)
    try:
        assert adapter.fetch() == []
        assert adapter.site_status["not a url"].startswith("failed: invalid URL")
        assert adapter.site_status["nvidia/NVIDIAExternalCareerSite"] == "ok: 0 postings"
        assert calls == [0]
    finally:
        adapter.close()


def test_fetch_skips_invalid_rows_and_deduplicates_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = WorkdayAdapter([
        "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
        "https://nvidia.wd5.myworkdayjobs.com/en-US/AnotherCareerSite",
    ], max_pages=1, detail_limit=0)
    listing = {"jobPostings": [
        None,
        {},
        {"externalPath": "relative/path", "title": "Bad path"},
        {"externalPath": "/job/without-title"},
        {"externalPath": "/job/Engineer_REQ-1", "title": "Engineer"},
    ], "total": 5}
    monkeypatch.setattr(adapter.client, "post", lambda *a, **kw: FakeResponse(listing))
    monkeypatch.setattr(adapter.client, "get", lambda *a, **kw: pytest.fail("detail cap should prevent get"))
    try:
        jobs = adapter.fetch()
    finally:
        adapter.close()
    assert len(jobs) == 1
    assert jobs[0].source_id == "/job/Engineer_REQ-1"
    assert adapter.site_status["nvidia/NVIDIAExternalCareerSite"] == "ok: 1 postings"


def test_fetch_falls_back_to_listing_fields_when_detail_request_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = WorkdayAdapter(["https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"], max_pages=1)
    listing = {"jobPostings": [{
        "externalPath": "/job/Engineer_REQ-1", "title": "Engineer",
        "locationsText": "India", "postedOn": "Posted Today",
    }], "total": 1}
    monkeypatch.setattr(adapter.client, "post", lambda *a, **kw: FakeResponse(listing))
    def fail_get(*args, **kwargs):
        raise RuntimeError("detail endpoint unavailable")
    monkeypatch.setattr(adapter.client, "get", fail_get)
    try:
        jobs = adapter.fetch()
    finally:
        adapter.close()
    assert len(jobs) == 1
    assert jobs[0].location == "India"
    assert jobs[0].description == ""
    assert jobs[0].posted_at is not None


def test_fetch_handles_non_mapping_detail_and_location_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = WorkdayAdapter(["https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"], max_pages=1)
    listing = {"jobPostings": [{
        "externalPath": "/job/Engineer_REQ-1", "title": "Engineer",
        "locationsText": "Listing location",
    }], "total": 1}
    monkeypatch.setattr(adapter.client, "post", lambda *a, **kw: FakeResponse(listing))
    monkeypatch.setattr(adapter.client, "get", lambda *a, **kw: FakeResponse([]))
    try:
        jobs = adapter.fetch()
    finally:
        adapter.close()
    assert jobs[0].location == "Listing location"
    assert jobs[0].description == ""


def test_fetch_paginates_and_stops_at_total(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = WorkdayAdapter(["https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"], max_pages=3, detail_limit=0)
    first_page = [{"externalPath": f"/job/Engineer_REQ-{i}", "title": f"Engineer {i}"} for i in range(20)]
    second_page = [{"externalPath": "/job/Engineer_REQ-20", "title": "Engineer 20"}]
    offsets = []
    def post(url, json):
        offsets.append(json["offset"])
        return FakeResponse({"jobPostings": first_page, "total": 21} if json["offset"] == 0 else {"jobPostings": second_page, "total": 21})
    monkeypatch.setattr(adapter.client, "post", post)
    try:
        jobs = adapter.fetch()
    finally:
        adapter.close()
    assert len(jobs) == 21
    assert offsets == [0, 20]


def test_fetch_handles_detail_info_with_mixed_additional_locations(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = WorkdayAdapter(["https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"], max_pages=1)
    listing = {"jobPostings": [{
        "externalPath": "/job/Engineer_REQ-1", "title": "Engineer",
        "locationsText": "Fallback",
    }], "total": 1}
    detail = {"jobPostingInfo": {
        "jobDescription": "role", "location": "",
        "additionalLocations": [{"descriptor": "Hyderabad"}, "Pune", None],
        "postedOn": "unknown", "timeType": None,
    }}
    monkeypatch.setattr(adapter.client, "post", lambda *a, **kw: FakeResponse(listing))
    monkeypatch.setattr(adapter.client, "get", lambda *a, **kw: FakeResponse(detail))
    try:
        jobs = adapter.fetch()
    finally:
        adapter.close()
    assert jobs[0].location == "Hyderabad | Pune"
    assert jobs[0].employment_type is None
    assert jobs[0].description == "role"

def test_fetch_marks_invalid_response_schema_as_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = WorkdayAdapter(["https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"], max_pages=1)
    monkeypatch.setattr(adapter.client, "post", lambda *a, **kw: FakeResponse({"wrong": []}))
    try:
        assert adapter.fetch() == []
        assert adapter.site_status["nvidia/NVIDIAExternalCareerSite"] == "failed: no successful job-search response"
    finally:
        adapter.close()


def test_fetch_uses_listing_location_when_job_posting_info_is_not_a_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = WorkdayAdapter(["https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"], max_pages=1)
    listing = {"jobPostings": [{
        "externalPath": "/job/Engineer_REQ-1", "title": "Engineer",
        "locationsText": "Listing location",
    }], "total": 1}
    monkeypatch.setattr(adapter.client, "post", lambda *a, **kw: FakeResponse(listing))
    monkeypatch.setattr(adapter.client, "get", lambda *a, **kw: FakeResponse({"jobPostingInfo": []}))
    try:
        jobs = adapter.fetch()
    finally:
        adapter.close()
    assert jobs[0].location == "Listing location"


def test_fetch_stops_when_total_is_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = WorkdayAdapter(["https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"], max_pages=3, detail_limit=0)
    postings = [{"externalPath": f"/job/Engineer_REQ-{i}", "title": f"Engineer {i}"} for i in range(20)]
    offsets = []
    def post(url, json):
        offsets.append(json["offset"])
        return FakeResponse({"jobPostings": postings, "total": 20})
    monkeypatch.setattr(adapter.client, "post", post)
    try:
        assert len(adapter.fetch()) == 20
    finally:
        adapter.close()
    assert offsets == [0]


def test_fetch_handles_non_integer_total_after_full_page(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = WorkdayAdapter(["https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"], max_pages=1, detail_limit=0)
    postings = [{"externalPath": f"/job/Engineer_REQ-{i}", "title": f"Engineer {i}"} for i in range(20)]
    monkeypatch.setattr(adapter.client, "post", lambda *a, **kw: FakeResponse({"jobPostings": postings, "total": "20"}))
    try:
        assert len(adapter.fetch()) == 20
    finally:
        adapter.close()

