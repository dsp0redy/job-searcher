"""Optional GitHub Issues publisher with stable markers and duplicate checks."""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

import httpx

from .models import Job

LOG = logging.getLogger(__name__)


class GitHubIssuePublisher:
    """Publish one issue per job identity when explicitly enabled in configuration."""

    def __init__(self, repository: str, token: str, timeout: float = 20) -> None:
        if "/" not in repository or repository.startswith("/") or repository.endswith("/"):
            raise ValueError("notifications.repository must be in owner/repository format")
        self.repository = repository
        self.client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "job-searcher/0.1",
            },
        )
        self.base_url = f"https://api.github.com/repos/{repository}"

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def marker(job: Job) -> str:
        return hashlib.sha256(f"{job.source.casefold()}:{job.company.casefold()}:{job.source_id.casefold()}".encode()).hexdigest()

    def publish(self, job: Job, score: int, reason: str, skills: list[str]) -> dict[str, Any]:
        marker = f"<!-- job-searcher:{self.marker(job)} -->"
        try:
            page = 1
            existing: dict[str, Any] | None = None
            while page <= 10:
                response = self.client.get(
                    f"{self.base_url}/issues",
                    params={"state": "all", "per_page": 100, "page": page},
                )
                response.raise_for_status()
                issues = response.json()
                if not isinstance(issues, list):
                    raise ValueError("Unexpected GitHub issues response")
                for issue in issues:
                    # Pull requests also appear in the Issues endpoint.
                    if "pull_request" not in issue and marker in str(issue.get("body") or ""):
                        existing = issue
                        break
                if existing or len(issues) < 100:
                    break
                page += 1

            body = (
                f"## Job match: {score}/100\n\n"
                f"- **Company:** {job.company}\n"
                f"- **Role:** {job.title}\n"
                f"- **Location:** {job.location}\n"
                f"- **Source:** {job.source}\n"
                f"- **Apply:** {job.url}\n\n"
                f"### Local matching evidence\n{reason}\n\n"
                f"### Matched skills\n{', '.join(skills) if skills else 'No configured skills matched.'}\n\n"
                "This score is a deterministic keyword relevance heuristic, not an interview probability. "
                "Review the original job description and requirements before applying.\n\n"
                f"{marker}"
            )
            if existing:
                return {
                    "status": "already_exists",
                    "issue_url": existing.get("html_url"),
                    "issue_number": existing.get("number"),
                }
            response = self.client.post(
                f"{self.base_url}/issues",
                json={"title": f"[Job match {score}/100] {job.company} — {job.title}"[:250], "body": body},
            )
            response.raise_for_status()
            issue = response.json()
            return {"status": "created", "issue_url": issue.get("html_url"), "issue_number": issue.get("number")}
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            LOG.warning("Could not publish GitHub issue for %s: %s", job.identity, type(exc).__name__)
            return {"status": "failed", "error": type(exc).__name__}
