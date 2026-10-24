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
