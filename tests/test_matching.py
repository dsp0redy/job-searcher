import pytest

from job_searcher.config import ProfileConfig
from job_searcher.matching import (_contains_location, extract_experience_range, is_allowed_location, is_experience_compatible, score_job)
from job_searcher.models import Job


def test_local_score_explains_matching_evidence():
    job = Job(source="lever", source_id="x", company="Acme", title="C++ Engineer",
              location="Bengaluru, India", url="https://example.com/x", description="Linux systems C++17")
    profile = ProfileConfig(titles=["C++ Engineer"], locations=["Bengaluru"], skills=["C++", "Linux", "Python"])
    result = score_job(job, profile)
    assert result["score"] > 0
    assert "C++" in result["skill_hits"]
    assert "Python" not in result["skill_hits"]


def test_empty_profile_never_gives_false_positive():
    job = Job(source="lever", source_id="x", company="Acme", title="Engineer",
              url="https://example.com/x", description="C++ Linux")
    assert score_job(job, ProfileConfig())["score"] == 0

def test_cache_key_changes_with_provider_and_profile():
    from job_searcher.matching import cache_key

    job = Job(source="lever", source_id="x", company="Acme", title="C++ Engineer",
              url="https://example.com/x", description="Linux")
    profile = ProfileConfig(skills=["C++"])
    assert cache_key(job, profile, "gemini") != cache_key(job, profile, "claude")
    assert cache_key(job, profile) != cache_key(job, ProfileConfig(skills=["Linux"]))




@pytest.mark.parametrize(
    "location",
    [
        "Bengaluru, Karnataka, India",
        "Bangalore, India",
        "Bengaluru Urban",
        "Hyderabad, Telangana",
        "Hyderabad, India",
    ],
)
def test_target_city_aliases_are_allowed(location):
    profile = ProfileConfig(locations=["Bengaluru", "Bangalore", "Hyderabad"])
    assert is_allowed_location(location, profile)


@pytest.mark.parametrize(
    "location",
    [
        "Pune, Maharashtra, India",
        "Chennai, Tamil Nadu",
        "Noida, Uttar Pradesh",
        "Remote - India",
        "India",
        "Unknown",
    ],
)
def test_non_target_locations_are_rejected(location):
    profile = ProfileConfig(locations=["Bengaluru", "Bangalore", "Hyderabad"])
    assert not is_allowed_location(location, profile)


def test_location_matching_does_not_match_city_as_substring():
    profile = ProfileConfig(locations=["Bengaluru", "Hyderabad"])
    assert not is_allowed_location("NotBengaluru, India", profile)


def test_out_of_area_job_gets_zero_local_score_even_if_title_and_skills_match():
    job = Job(
        source="lever",
        source_id="pune-role",
        company="Acme",
        title="Senior C++ Linux Engineer",
        location="Pune, Maharashtra, India",
        url="https://example.com/pune",
        description="C++ Linux embedded systems",
    )
    profile = ProfileConfig(
        titles=["Engineer"],
        locations=["Bengaluru", "Hyderabad"],
        skills=["C++", "Linux"],
    )
    result = score_job(job, profile)
    assert result["score"] == 0
    assert result["location_allowed"] is False
    assert result["reason"].startswith("Excluded:")



@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Requires 3-5 years of experience", (3.0, 5.0)),
        ("Minimum of 3 years of experience", (3.0, None)),
        ("5 years experience in C++", (5.0, None)),
        ("8+ years of relevant experience", (8.0, None)),
        ("8+ years", (8.0, None)),
        ("At least 4 yrs experience", (4.0, None)),
        ("At least 4 years", (4.0, None)),
        ("No experience details listed", (None, None)),
        ("Requires 8-3 years experience", (None, None)),
    ],
)
def test_extract_experience_range(text, expected):
    assert extract_experience_range(text) == expected


def test_experience_compatibility_rejects_roles_outside_configured_range():
    profile = ProfileConfig(minimum_experience_years=2, maximum_experience_years=5)
    assert not is_experience_compatible(8, None, profile)
    assert not is_experience_compatible(None, 1, profile)
    assert is_experience_compatible(3, 4, profile)
    assert is_experience_compatible(None, None, profile)
    assert is_experience_compatible(8, None, ProfileConfig())



def test_reviewed_location_regression_fixture():
    import json
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "location_regression.json"
    cases = json.loads(fixture.read_text(encoding="utf-8"))
    profile = ProfileConfig(locations=["Bengaluru", "Bangalore", "Hyderabad"])
    assert cases
    for case in cases:
        assert is_allowed_location(case["location"], profile) is case["allowed"], case["location"]



def test_location_match_handles_empty_and_custom_location_terms():
    assert not _contains_location("Bengaluru, India", "")
    assert _contains_location("Pune, Maharashtra", "Pune")
