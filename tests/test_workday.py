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
