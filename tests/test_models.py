from datetime import datetime
from job_searcher.models import Job


def make_job(**overrides):
    values = dict(source="greenhouse", source_id="123", company="Acme", title="C++ Engineer",
                  location="Bengaluru, India", url="https://example.com/jobs/123", description="C++ Linux")
    values.update(overrides)
    return Job(**values)


def test_identity_is_stable():
    assert make_job().identity == make_job().identity


def test_identity_changes_by_source_id():
    assert make_job().identity != make_job(source_id="456").identity


def test_naive_posted_datetime_becomes_utc():
    job = make_job(posted_at=datetime(2025, 1, 1))
    assert job.posted_at is not None and job.posted_at.utcoffset().total_seconds() == 0
