from job_searcher.models import Job
from job_searcher.notifications import GitHubIssuePublisher


def test_job_marker_is_stable_for_same_job_identity() -> None:
    data = {
        "source": "workday",
        "source_id": "REQ-123",
        "company": "NVIDIA",
        "title": "Software Engineer",
        "location": "Bengaluru",
        "url": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/REQ-123",
    }
    first = Job(**data)
    second = Job(**data)
    assert GitHubIssuePublisher.marker(first) == GitHubIssuePublisher.marker(second)


def test_job_marker_changes_for_different_requisition() -> None:
    base = {
        "source": "workday",
        "source_id": "REQ-123",
        "company": "NVIDIA",
        "title": "Software Engineer",
        "location": "Bengaluru",
        "url": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/REQ-123",
    }
    first = Job(**base)
    second = Job(**{**base, "source_id": "REQ-456"})
    assert GitHubIssuePublisher.marker(first) != GitHubIssuePublisher.marker(second)
