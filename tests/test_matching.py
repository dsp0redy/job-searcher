from job_searcher.config import ProfileConfig
from job_searcher.matching import score_job
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
