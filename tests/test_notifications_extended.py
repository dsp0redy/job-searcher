from __future__ import annotations

import httpx
import pytest

from job_searcher.models import Job
from job_searcher.notifications import GitHubIssuePublisher


def make_job(source_id="REQ-123"):
    return Job(source="workday", source_id=source_id, company="NVIDIA",
               title="Software Engineer", location="Bengaluru",
               url="https://example.com/jobs/1")


class FakeResponse:
    def __init__(self, payload, status=200, method="GET", url="https://api.github.com") -> None:
        self.payload, self.status = payload, status
        self.request = httpx.Request(method, url)
        self.response = httpx.Response(status, request=self.request)

    def raise_for_status(self):
        if self.status >= 400:
            raise httpx.HTTPStatusError("request failed", request=self.request, response=self.response)

    def json(self):
        return self.payload


@pytest.mark.parametrize("repository", ["", "/owner/repo", "owner/", "owner/repo/extra"])
def test_publisher_rejects_invalid_repository(repository):
    with pytest.raises(ValueError, match="owner/repository"):
        GitHubIssuePublisher(repository, "token")


def test_load_existing_issues_skips_pull_requests_and_is_cached(monkeypatch):
    publisher = GitHubIssuePublisher("owner/repo", "token")
    job = make_job()
    marker = publisher.marker(job)
    calls = []
    issues = [
        {"pull_request": {"url": "ignore"}, "body": f"<!-- job-searcher:{marker} -->"},
        {"number": 7, "html_url": "https://github.com/owner/repo/issues/7",
         "body": f"<!-- job-searcher:{marker} -->"},
        {"number": 8, "body": "no marker"},
    ]
    monkeypatch.setattr(publisher.client, "get", lambda *a, **kw: (calls.append(1), FakeResponse(issues))[1])
    try:
        publisher._load_existing_issues()
        publisher._load_existing_issues()
        assert len(calls) == 1
        assert publisher._existing[marker]["number"] == 7
        result = publisher.publish(job, 90, "good fit", ["C++"])
        assert result["status"] == "already_exists"
        assert result["issue_number"] == 7
    finally:
        publisher.close()


def test_publish_creates_issue_and_caches_it(monkeypatch):
    publisher = GitHubIssuePublisher("owner/repo", "token")
    job = make_job()
    calls = []
    monkeypatch.setattr(publisher.client, "get", lambda *a, **kw: FakeResponse([]))
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse({"number": 42, "html_url": "https://github.com/owner/repo/issues/42"}, method="POST", url=url)
    monkeypatch.setattr(publisher.client, "post", post)
    try:
        result = publisher.publish(job, 91, "C++ fit", ["C++"], ["QNX"], ["Study QNX"])
        assert result == {"status": "created", "issue_url": "https://github.com/owner/repo/issues/42", "issue_number": 42}
        assert len(calls) == 1
        body = calls[0][1]["json"]["body"]
        assert "Missing skills (AI mode)" in body
        assert "Study QNX" in body
        assert publisher.publish(job, 91, "C++ fit", ["C++"])["status"] == "already_exists"
    finally:
        publisher.close()


def test_publish_returns_failed_when_existing_issue_lookup_fails(monkeypatch):
    publisher = GitHubIssuePublisher("owner/repo", "token")
    monkeypatch.setattr(publisher.client, "get", lambda *a, **kw: FakeResponse({}, status=503))
    try:
        result = publisher.publish(make_job(), 80, "fit", [])
        assert result == {"status": "failed", "error": "HTTPStatusError"}
    finally:
        publisher.close()


def test_publish_returns_failed_when_create_fails(monkeypatch):
    publisher = GitHubIssuePublisher("owner/repo", "token")
    monkeypatch.setattr(publisher.client, "get", lambda *a, **kw: FakeResponse([]))
    monkeypatch.setattr(publisher.client, "post", lambda *a, **kw: FakeResponse({}, status=403, method="POST"))
    try:
        result = publisher.publish(make_job(), 80, "fit", [])
        assert result == {"status": "failed", "error": "HTTPStatusError"}
    finally:
        publisher.close()


def test_existing_issue_loader_rejects_non_list_payload(monkeypatch):
    publisher = GitHubIssuePublisher("owner/repo", "token")
    monkeypatch.setattr(publisher.client, "get", lambda *a, **kw: FakeResponse({"items": []}))
    try:
        with pytest.raises(ValueError, match="Unexpected GitHub issues"):
            publisher._load_existing_issues()
    finally:
        publisher.close()


def test_existing_issue_loader_follows_full_pages(monkeypatch):
    publisher = GitHubIssuePublisher("owner/repo", "token")
    calls = []
    def get(url, params):
        calls.append(params["page"])
        return FakeResponse([{"body": "no marker"}] * (100 if params["page"] == 1 else 1))
    monkeypatch.setattr(publisher.client, "get", get)
    try:
        publisher._load_existing_issues()
        assert calls == [1, 2]
    finally:
        publisher.close()

def test_existing_issue_loader_skips_non_object_items(monkeypatch):
    publisher = GitHubIssuePublisher("owner/repo", "token")
    monkeypatch.setattr(publisher.client, "get", lambda *a, **kw: FakeResponse([None, "bad", {"body": "safe"}]))
    try:
        publisher._load_existing_issues()
        assert publisher._existing == {}
    finally:
        publisher.close()


def test_publish_rejects_non_object_create_response(monkeypatch):
    publisher = GitHubIssuePublisher("owner/repo", "token")
    monkeypatch.setattr(publisher.client, "get", lambda *a, **kw: FakeResponse([]))
    monkeypatch.setattr(publisher.client, "post", lambda *a, **kw: FakeResponse(["unexpected"], method="POST"))
    try:
        assert publisher.publish(make_job(), 80, "fit", []) == {
            "status": "failed", "error": "ValueError"
        }
    finally:
        publisher.close()

def test_existing_issue_loader_caps_scan_at_ten_pages(monkeypatch):
    publisher = GitHubIssuePublisher("owner/repo", "token")
    calls = []
    monkeypatch.setattr(publisher.client, "get", lambda url, params: (calls.append(params["page"]), FakeResponse([{"body": "none"}] * 100))[1])
    try:
        publisher._load_existing_issues()
        assert calls == list(range(1, 11))
        assert publisher._issues_loaded is True
    finally:
        publisher.close()

