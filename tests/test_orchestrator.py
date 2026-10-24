from __future__ import annotations

from datetime import datetime, timezone

import pytest

from job_searcher.ai_matching import MatchResult
from job_searcher.config import (
    AppConfig, MatchingConfig, NotificationConfig, ProfileConfig, SearchConfig,
    SourcesConfig, StorageConfig,
)
from job_searcher.models import Job
import job_searcher.orchestrator as orchestrator_module
from job_searcher.orchestrator import SearchOrchestrator


def make_job(source_id="1", title="C++ Engineer"):
    return Job(source="greenhouse", source_id=source_id, company="Acme", title=title,
               location="Bengaluru, India", url=f"https://example.com/jobs/{source_id}",
               description="C++ Linux systems", posted_at=datetime.now(timezone.utc))


class FakeSource:
    def __init__(self, name, jobs, fail=False):
        self.name = name
        self.jobs = jobs
        self.fail = fail
        self.board_tokens = ["board"] if name == "greenhouse" else []
        self.site_slugs = ["site"] if name == "lever" else []
        self.site_status = {"tenant": "ok: 0 postings"} if name == "workday" else {}
        self.closed = False

    def fetch(self):
        if self.fail:
            raise RuntimeError("source failed")
        return self.jobs

    def close(self):
        self.closed = True


def make_config(tmp_path, provider="none", notifications=False, **matching_overrides):
    matching = MatchingConfig(provider=provider, **matching_overrides)
    return AppConfig(
        profile=ProfileConfig(titles=["Engineer"], locations=["Bengaluru"], skills=["C++", "Linux"]),
        search=SearchConfig(minimum_local_score=0, posted_within_days=14),
        storage=StorageConfig(path=str(tmp_path / "state.sqlite3")),
        matching=matching,
        sources=SourcesConfig(greenhouse=["board"], lever=["site"], workday=[]),
        notifications=NotificationConfig(github_issues=notifications, repository="owner/repo"),
    )


def install_sources(monkeypatch, jobs, failed=()):
    created = {}
    def factory(name):
        def build(*args, **kwargs):
            source_jobs = jobs if name == "greenhouse" else []
            instance = FakeSource(name, source_jobs, fail=name in failed)
            created[name] = instance
            return instance
        return build
    monkeypatch.setattr(orchestrator_module, "GreenhouseAdapter", factory("greenhouse"))
    monkeypatch.setattr(orchestrator_module, "LeverAdapter", factory("lever"))
    monkeypatch.setattr(orchestrator_module, "WorkdayAdapter", factory("workday"))
    return created


def test_end_to_end_local_scan_persists_and_writes_three_reports(tmp_path, monkeypatch):
    job = make_job()
    created = install_sources(monkeypatch, [job])
    orchestrator = SearchOrchestrator(make_config(tmp_path))
    summary = orchestrator.run(str(tmp_path / "reports"))

    assert summary["run_status"] == "success"
    assert summary["postings_fetched"] == 1
    assert summary["new_identities"] == 1
    assert summary["qualified_candidates"] == 1
    assert len(summary["reports"]) == 3
    assert all(__import__("pathlib").Path(path).exists() for path in summary["reports"])
    assert all(source.closed for source in created.values())
    with orchestrator.store._connect() as db:
        run = db.execute("SELECT status FROM scan_runs WHERE run_id=?", (summary["run_id"],)).fetchone()
        stored = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert run["status"] == "success"
    assert stored == 1


def test_end_to_end_continues_when_one_source_fails(tmp_path, monkeypatch):
    install_sources(monkeypatch, [make_job()], failed=("lever",))
    summary = SearchOrchestrator(make_config(tmp_path)).run(str(tmp_path / "reports"))
    assert summary["run_status"] == "success"
    assert summary["sources"]["lever"] == "failed: RuntimeError"
    assert summary["postings_fetched"] == 1


def test_end_to_end_no_successful_sources_marks_run(tmp_path, monkeypatch):
    install_sources(monkeypatch, [], failed=("greenhouse", "lever", "workday"))
    summary = SearchOrchestrator(make_config(tmp_path)).run(str(tmp_path / "reports"))
    assert summary["run_status"] == "no_sources_succeeded"


def test_ai_initialization_failure_falls_back_to_local_report_and_skips_notification(
    tmp_path, monkeypatch
):
    job = make_job()
    install_sources(monkeypatch, [job])
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(orchestrator_module, "AIResumeMatcher",
                        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("missing secret")))
    summary = SearchOrchestrator(make_config(tmp_path, provider="gemini", notifications=True)).run(
        str(tmp_path / "reports")
    )
    assert summary["run_status"] == "partial_ai_failure"
    assert summary["ai"]["initialization_failed"] is True
    assert summary["ai"]["failed"] == 1
    assert summary["matching"] == "deterministic local scoring (AI unavailable)"
    import json
    rows = json.loads(__import__("pathlib").Path(summary["reports"][0]).read_text(encoding="utf-8"))
    assert rows[0]["ai_status"] == "failed"
    assert rows[0]["notification"] == "ai_failed"
    assert summary["notifications"]["created"] == 0


def test_ai_match_results_are_cached_between_scans(tmp_path, monkeypatch):
    job = make_job()
    install_sources(monkeypatch, [job])
    class FakeMatcher:
        calls = 0
        def __init__(self, provider, timeout):
            self.provider = provider
        def cache_key(self, item):
            return "cache-" + item.identity
        def match_batch(self, batch):
            self.calls += 1
            return {item.identity: MatchResult(job_id=item.identity, score=91, reason="Evidence") for item in batch}
        def close(self):
            pass
    matcher = FakeMatcher("gemini", 10)
    monkeypatch.setattr(orchestrator_module, "AIResumeMatcher", lambda *args, **kwargs: matcher)
    config = make_config(tmp_path, provider="gemini")
    first = SearchOrchestrator(config).run(str(tmp_path / "reports1"))
    second = SearchOrchestrator(config).run(str(tmp_path / "reports2"))
    assert first["ai"]["scored"] == 1
    assert second["ai"]["cached"] == 1
    assert matcher.calls == 1


def test_ai_batch_failure_is_reported_as_partial_failure(tmp_path, monkeypatch):
    install_sources(monkeypatch, [make_job()])
    class FailedMatcher:
        def __init__(self, provider, timeout): pass
        def cache_key(self, item): return item.identity
        def match_batch(self, batch): return {}
        def close(self): pass
    monkeypatch.setattr(orchestrator_module, "AIResumeMatcher", FailedMatcher)
    summary = SearchOrchestrator(make_config(tmp_path, provider="gemini")).run(str(tmp_path / "reports"))
    assert summary["run_status"] == "partial_ai_failure"
    assert summary["ai"]["failed"] == 1


def test_ai_scan_limit_marks_unselected_candidates_deferred(tmp_path, monkeypatch):
    jobs = [make_job("1", "C++ Engineer"), make_job("2", "Linux Engineer")]
    install_sources(monkeypatch, jobs)
    class LimitedMatcher:
        def __init__(self, provider, timeout): pass
        def cache_key(self, item): return item.identity
        def match_batch(self, batch):
            return {item.identity: MatchResult(job_id=item.identity, score=80, reason="Evidence") for item in batch}
        def close(self): pass
    monkeypatch.setattr(orchestrator_module, "AIResumeMatcher", LimitedMatcher)
    summary = SearchOrchestrator(make_config(tmp_path, provider="gemini", max_ai_jobs_per_scan=1)).run(
        str(tmp_path / "reports")
    )
    assert summary["ai"]["deferred_by_scan_limit"] == 1
    assert summary["qualified_candidates"] == 2
    assert summary["run_status"] == "success"


def test_orchestrator_marks_exceptional_run_failed_and_closes_ai(tmp_path, monkeypatch):
    install_sources(monkeypatch, [make_job()])
    closed = []
    class Matcher:
        def __init__(self, provider, timeout): pass
        def cache_key(self, item): return item.identity
        def match_batch(self, batch): return {}
        def close(self): closed.append(True)
    monkeypatch.setattr(orchestrator_module, "AIResumeMatcher", Matcher)
    monkeypatch.setattr(orchestrator_module, "write_reports",
                        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    orchestrator = SearchOrchestrator(make_config(tmp_path, provider="gemini"))
    with pytest.raises(OSError):
        orchestrator.run(str(tmp_path / "reports"))
    with orchestrator.store._connect() as db:
        run = db.execute("SELECT status, summary_json FROM scan_runs").fetchone()
    assert run["status"] == "failed"
    assert '"error_type": "OSError"' in run["summary_json"]
    assert closed == [True]
