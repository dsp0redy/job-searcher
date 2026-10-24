"""Optional GitHub Issues publisher with stable markers and duplicate checks."""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

import httpx

from .models import Job

LOG = logging.getLogger(__name__)

MAX_ISSUE_PAGES = 50  # 5,000 issues; beyond this we refuse to guess rather than duplicate
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]<>()#+!|~])")


def sanitize_markdown(value: object, limit: int = 500) -> str:
    """Neutralize untrusted text (job/AI-controlled) before placing it in an issue body.

    Escapes Markdown/HTML syntax, defuses @mentions and #refs so a posting cannot ping
    people, inject links/images, or forge the dedupe marker comment.
    """
    text = " ".join(str(value).split())[:limit]
    text = _MD_SPECIAL.sub(r"\\\1", text)
    return text.replace("@", "@\u200b")


class GitHubIssuePublisher:
    """Publish one issue per job identity when explicitly enabled in configuration."""

    def __init__(self, repository: str, token: str, timeout: float = 20) -> None:
        parts = repository.split("/")
        if len(parts) != 2 or not all(part.strip() for part in parts):
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
        self._load_error: str | None = None

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def marker(job: Job) -> str:
        identity = f"{job.source.casefold()}:{job.company.casefold()}:{job.source_id.casefold()}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _load_existing_issues(self) -> None:
        if self._issues_loaded:
            return
        if self._load_error:
            raise ValueError(self._load_error)
        page = 1
        while page <= MAX_ISSUE_PAGES:
            response = self.client.get(
                f"{self.base_url}/issues",
                params={"state": "all", "per_page": 100, "page": page},
            )
            response.raise_for_status()
            issues = response.json()
            if not isinstance(issues, list):
                raise ValueError("Unexpected GitHub issues response")
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                # Pull requests also appear in the Issues endpoint.
                if "pull_request" in issue:
                    continue
                body = str(issue.get("body") or "")
                match = re.search(r"<!-- job-searcher:([a-f0-9]{64}) -->", body)
                if match:
                    self._existing[match.group(1)] = issue
            if len(issues) < 100:
                self._issues_loaded = True
                return
            page += 1
        # Every page was full: older issues may be unseen, so duplicate detection is
        # unreliable. Fail closed instead of silently creating duplicate issues.
        self._load_error = f"Issue history exceeds {MAX_ISSUE_PAGES * 100} issues; cannot dedupe safely"
        raise ValueError(self._load_error)

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

            safe_skills = ", ".join(sanitize_markdown(x, 80) for x in skills)
            safe_missing = ", ".join(sanitize_markdown(x, 80) for x in (missing_skills or []))
            safe_steps = "\n".join(f"- {sanitize_markdown(item, 300)}" for item in (improvements or []))
            body = (
                f"## Job match: {score}/100\n\n"
                f"- **Company:** {sanitize_markdown(job.company, 200)}\n"
                f"- **Role:** {sanitize_markdown(job.title, 300)}\n"
                f"- **Location:** {sanitize_markdown(job.location, 300)}\n"
                f"- **Source:** {sanitize_markdown(job.source, 40)}\n"
                f"- **Apply:** {job.url}\n\n"
                f"### Local matching evidence\n{sanitize_markdown(reason, 1200)}\n\n"
                f"### Matched skills (local keyword evidence)\n{safe_skills or 'No configured skills matched.'}\n\n"
                f"### Missing skills (AI mode)\n{safe_missing or 'None reported.'}\n\n"
                f"### Suggested next steps\n"
                + (safe_steps or "No suggestions generated.")
                + "\n\nThe score is a relevance estimate, not an interview probability. "
                "Review the original job description and requirements before applying.\n\n"
                + marker
            )
            response = self.client.post(
                f"{self.base_url}/issues",
                json={
                    "title": f"[Job match {score}/100] "
                             f"{' '.join(job.company.split())} — {' '.join(job.title.split())}"[:250],
                    "body": body,
                },
            )
            response.raise_for_status()
            issue = response.json()
            if not isinstance(issue, dict):
                raise ValueError("Unexpected GitHub issue response")
            self._existing[digest] = issue
            return {"status": "created", "issue_url": issue.get("html_url"), "issue_number": issue.get("number")}
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            LOG.warning("Could not publish GitHub issue for %s: %s", job.identity, type(exc).__name__)
            return {"status": "failed", "error": type(exc).__name__}
