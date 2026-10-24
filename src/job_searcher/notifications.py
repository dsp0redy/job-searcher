"""Optional GitHub Issues publisher with stable markers and duplicate checks."""
from __future__ import annotations

import hashlib
import logging
import re
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
        self._existing: dict[str, dict[str, Any]] = {}
        self._issues_loaded = False

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def marker(job: Job) -> str:
        identity = f"{job.source.casefold()}:{job.company.casefold()}:{job.source_id.casefold()}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _load_existing_issues(self) -> None:
        if self._issues_loaded:
            return
        page = 1
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
                if "pull_request" in issue:
                    continue
                body = str(issue.get("body") or "")
                match = re.search(r"<!-- job-searcher:([a-f0-9]{64}) -->", body)
                if match:
                    self._existing[match.group(1)] = issue
            if len(issues) < 100:
                break
            page += 1
        self._issues_loaded = True

    def publish(
        self,
        job: Job,
        score: int,
        reason: str,
        skills: list[str],
        missing_skills: list[str] | None = None,
        improvements: list[str] | None = None,
    ) -> dict[str, Any]:
        digest = self.marker(job)
        marker = f"<!-- job-searcher:{digest} -->"
        try:
            self._load_existing_issues()
            existing = self._existing.get(digest)
            if existing:
                return {
                    "status": "already_exists",
                    "issue_url": existing.get("html_url"),
                    "issue_number": existing.get("number"),
                }

            body = (
                f"## Job match: {score}/100\n\n"
                f"- **Company:** {job.company}\n"
                f"- **Role:** {job.title}\n"
                f"- **Location:** {job.location}\n"
                f"- **Source:** {job.source}\n"
                f"- **Apply:** {job.url}\n\n"
                f"### Local matching evidence\n{reason}\n\n"
                f"### Matched skills (local keyword evidence)\n{', '.join(skills) if skills else 'No configured skills matched.'}\n\n"
                f"### Missing skills (AI mode)\n{', '.join(missing_skills or []) if missing_skills else 'None reported.'}\n\n"
                f"### Suggested next steps\n"
                + ("\n".join(f"- {item}" for item in improvements) if improvements else "No suggestions generated.")
                + "\n\nThe score is a relevance estimate, not an interview probability. "
                "Review the original job description and requirements before applying.\n\n"
                + marker
            )
            response = self.client.post(
                f"{self.base_url}/issues",
                json={"title": f"[Job match {score}/100] {job.company} — {job.title}"[:250], "body": body},
            )
            response.raise_for_status()
            issue = response.json()
            self._existing[digest] = issue
            return {"status": "created", "issue_url": issue.get("html_url"), "issue_number": issue.get("number")}
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            LOG.warning("Could not publish GitHub issue for %s: %s", job.identity, type(exc).__name__)
            return {"status": "failed", "error": type(exc).__name__}
