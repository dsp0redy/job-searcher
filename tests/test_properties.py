from __future__ import annotations

from hypothesis import given, settings, strategies as st

from job_searcher.config import ProfileConfig
from job_searcher.matching import score_job
from job_searcher.models import Job
from job_searcher.adapters.workday import WorkdayAdapter


@given(st.text(min_size=1, max_size=80), st.text(min_size=1, max_size=80))
@settings(max_examples=100)
def test_job_identity_is_stable_and_case_insensitive_for_source_company_and_id(source, source_id):
    # Keep required model values bounded and URLs valid while fuzzing identity material.
    job = Job(source=source[:40] or "s", source_id=source_id[:300] or "id",
              company="Example", title="Engineer", url="https://example.com/job")
    same = job.model_copy(update={"source": job.source.swapcase(), "source_id": job.source_id.swapcase()})
    assert job.identity == same.identity


@given(
    title=st.text(max_size=100),
    description=st.text(max_size=500),
    location=st.text(max_size=100),
    skills=st.lists(st.text(max_size=20), max_size=10),
    titles=st.lists(st.text(max_size=20), max_size=5),
    locations=st.lists(st.text(max_size=20), max_size=5),
)
@settings(max_examples=100)
def test_local_score_is_always_bounded(title, description, location, skills, titles, locations):
    job = Job(source="fuzz", source_id="1", company="Example", title=title or "Engineer",
              location=location, url="https://example.com/job", description=description)
    profile = ProfileConfig(titles=titles, locations=locations, skills=skills)
    result = score_job(job, profile)
    assert isinstance(result["score"], int)
    assert 0 <= result["score"] <= 100
    assert set(result) == {"score", "title_hits", "location_hits", "skill_hits", "reason"}


@given(st.text(max_size=200))
@settings(max_examples=100)
def test_workday_relative_date_parser_never_raises_for_arbitrary_text(value):
    result = WorkdayAdapter._parse_posted_at(value)
    assert result is None or result.tzinfo is not None


def test_workday_relative_date_parser_handles_absurd_day_counts():
    assert WorkdayAdapter._parse_posted_at("999999999999999999999999999999999 days ago") is None
