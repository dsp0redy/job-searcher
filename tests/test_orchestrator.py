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
        profile=ProfileConfig(titles=["Engineer"], locations=["Bengaluru", "Bangalore", "Hyderabad"], minimum_experience_years=2, maximum_experience_years=5, skills=["C++", "Linux"]),
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
            configured = args[0] if args else []
            if name == "greenhouse":
                instance.board_tokens = configured
            elif name == "lever":
                instance.site_slugs = configured
            elif name == "workday":
                instance.site_status = {"tenant/site": "ok: 0 postings"} if configured else {}
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
    assert len(summary["reports"]) == 4
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

def test_unconfigured_sources_are_reported_as_skipped(tmp_path, monkeypatch):
    install_sources(monkeypatch, [])
    config = make_config(tmp_path)
    config.sources.greenhouse = []
    config.sources.lever = []
    config.sources.workday = []
    summary = SearchOrchestrator(config).run(str(tmp_path / "reports"))
    assert summary["sources"]["greenhouse"] == "skipped: no Greenhouse boards configured"
    assert summary["sources"]["lever"] == "skipped: no Lever sites configured"
    assert summary["run_status"] == "no_sources_succeeded"


def test_old_jobs_are_stored_but_excluded_from_candidates(tmp_path, monkeypatch):
    from datetime import timedelta
    old_job = make_job()
    old_job = old_job.model_copy(update={"posted_at": datetime.now(timezone.utc) - timedelta(days=100)})
    install_sources(monkeypatch, [old_job])
    summary = SearchOrchestrator(make_config(tmp_path)).run(str(tmp_path / "reports"))
    assert summary["postings_fetched"] == 1
    assert summary["qualified_candidates"] == 0
    with SearchOrchestrator(make_config(tmp_path)).store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_invalid_cached_ai_result_is_ignored_and_recomputed(tmp_path, monkeypatch):
    job = make_job()
    install_sources(monkeypatch, [job])
    from job_searcher.storage import JobStore
    JobStore(str(tmp_path / "state.sqlite3")).save_match(
        "cache-" + job.identity, "gemini",
        {"job_id": "wrong", "score": 101, "reason": ""},
    )
    class Matcher:
        calls = 0
        def __init__(self, provider, timeout): pass
        def cache_key(self, item): return "cache-" + item.identity
        def match_batch(self, batch):
            self.calls += 1
            return {item.identity: MatchResult(job_id=item.identity, score=77, reason="recomputed") for item in batch}
        def close(self): pass
    matcher = Matcher("gemini", 10)
    monkeypatch.setattr(orchestrator_module, "AIResumeMatcher", lambda *a, **kw: matcher)
    summary = SearchOrchestrator(make_config(tmp_path, provider="gemini")).run(str(tmp_path / "reports"))
    assert matcher.calls == 1
    assert summary["ai"]["scored"] == 1


def test_ai_jobs_are_processed_in_multiple_batches(tmp_path, monkeypatch):
    jobs = [make_job("1"), make_job("2")]
    install_sources(monkeypatch, jobs)
    class Matcher:
        def __init__(self, provider, timeout): self.batch_sizes = []
        def cache_key(self, item): return item.identity
        def match_batch(self, batch):
            self.batch_sizes.append(len(batch))
            return {item.identity: MatchResult(job_id=item.identity, score=75, reason="fit") for item in batch}
        def close(self): pass
    matcher = Matcher("gemini", 10)
    monkeypatch.setattr(orchestrator_module, "AIResumeMatcher", lambda *a, **kw: matcher)
    summary = SearchOrchestrator(make_config(tmp_path, provider="gemini", max_jobs_per_ai_batch=1)).run(
        str(tmp_path / "reports")
    )
    assert matcher.batch_sizes == [1, 1]
    assert summary["ai"]["scored"] == 2


@pytest.mark.parametrize("publish_status", ["created", "already_exists", "failed"])
def test_notification_results_are_reported(tmp_path, monkeypatch, publish_status):
    job = make_job()
    install_sources(monkeypatch, [job])
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    class Publisher:
        def __init__(self, repository, token, timeout): self.closed = False
        def publish(self, *args, **kwargs):
            return {"status": publish_status, "issue_url": "https://example.com/issue"}
        def close(self): self.closed = True
    publisher_instances = []
    def publisher_factory(*args, **kwargs):
        instance = Publisher(*args, **kwargs)
        publisher_instances.append(instance)
        return instance
    monkeypatch.setattr(orchestrator_module, "GitHubIssuePublisher", publisher_factory)
    config = make_config(tmp_path, notifications=True)
    config.matching.threshold = 50
    summary = SearchOrchestrator(config).run(str(tmp_path / "reports"))
    assert summary["notifications"][publish_status if publish_status != "already_exists" else "already_exists"] >= 0
    assert summary["notifications"]["results"][0]["status"] == publish_status
    if publish_status == "failed":
        assert summary["run_status"] == "partial_notification_failure"
    assert publisher_instances[0].closed is True


def test_notifications_enabled_without_credentials_do_not_abort_scan(tmp_path, monkeypatch):
    install_sources(monkeypatch, [make_job()])
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    config = make_config(tmp_path, notifications=True)
    config.matching.threshold = 50
    summary = SearchOrchestrator(config).run(str(tmp_path / "reports"))
    assert summary["notifications"]["not_configured"] is True

def test_duplicate_postings_are_scored_once_but_raw_fetch_count_is_preserved(tmp_path, monkeypatch):
    job = make_job()
    duplicate = job.model_copy(update={"description": "Updated description"})
    install_sources(monkeypatch, [job, duplicate])
    summary = SearchOrchestrator(make_config(tmp_path)).run(str(tmp_path / "reports"))
    assert summary["postings_fetched"] == 2
    assert summary["new_identities"] == 1
    assert summary["qualified_candidates"] == 1
    with SearchOrchestrator(make_config(tmp_path)).store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1

def test_workday_site_status_is_included_in_summary(tmp_path, monkeypatch):
    install_sources(monkeypatch, [])
    config = make_config(tmp_path)
    config.sources.workday = ["https://example.myworkdayjobs.com/site"]
    summary = SearchOrchestrator(config).run(str(tmp_path / "reports"))
    assert summary["sources"]["workday"].startswith("ok: 0 postings")
    assert summary["sources"]["workday:tenant/site"] == "ok: 0 postings"


def test_candidates_below_local_threshold_are_not_reported(tmp_path, monkeypatch):
    install_sources(monkeypatch, [make_job()])
    config = make_config(tmp_path)
    config.search.minimum_local_score = 100
    summary = SearchOrchestrator(config).run(str(tmp_path / "reports"))
    assert summary["qualified_candidates"] == 0


def test_cached_result_with_wrong_job_id_is_recomputed(tmp_path, monkeypatch):
    job = make_job()
    install_sources(monkeypatch, [job])
    from job_searcher.storage import JobStore
    JobStore(str(tmp_path / "state.sqlite3")).save_match(
        "cache-" + job.identity, "gemini",
        {"job_id": "different-but-valid", "score": 50, "reason": "other job"},
    )
    class Matcher:
        calls = 0
        def __init__(self, provider, timeout): pass
        def cache_key(self, item): return "cache-" + item.identity
        def match_batch(self, batch):
            self.calls += 1
            return {item.identity: MatchResult(job_id=item.identity, score=80, reason="correct") for item in batch}
        def close(self): pass
    matcher = Matcher("gemini", 10)
    monkeypatch.setattr(orchestrator_module, "AIResumeMatcher", lambda *a, **kw: matcher)
    summary = SearchOrchestrator(make_config(tmp_path, provider="gemini")).run(str(tmp_path / "reports"))
    assert matcher.calls == 1
    assert summary["ai"]["scored"] == 1




def test_out_of_area_job_never_becomes_candidate_or_github_issue(tmp_path, monkeypatch):
    job = make_job().model_copy(update={"location": "Pune, Maharashtra, India"})
    install_sources(monkeypatch, [job])
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    calls = []

    class Publisher:
        def __init__(self, repository, token, timeout):
            pass
        def publish(self, *args, **kwargs):
            calls.append(args[0].location)
            return {"status": "created", "issue_url": "https://example.com/issue"}
        def close(self):
            pass

    monkeypatch.setattr(orchestrator_module, "GitHubIssuePublisher", Publisher)
    config = make_config(tmp_path, notifications=True)
    config.matching.threshold = 0
    summary = SearchOrchestrator(config).run(str(tmp_path / "reports"))

    assert summary["postings_fetched"] == 1
    assert summary["excluded_by_location"] == 1
    assert summary["qualified_candidates"] == 0
    assert summary["notifications"]["created"] == 0
    assert calls == []


@pytest.mark.parametrize("location", ["Bangalore, India", "Hyderabad, Telangana, India"])
def test_bengaluru_and_hyderabad_jobs_remain_eligible(tmp_path, monkeypatch, location):
    job = make_job().model_copy(update={"location": location})
    install_sources(monkeypatch, [job])
    summary = SearchOrchestrator(make_config(tmp_path)).run(str(tmp_path / "reports"))
    assert summary["excluded_by_location"] == 0
    assert summary["qualified_candidates"] == 1



def test_explicitly_senior_experience_requirement_is_excluded(tmp_path, monkeypatch):
    job = make_job().model_copy(update={"description": "Requires 8+ years of experience in C++."})
    install_sources(monkeypatch, [job])
    summary = SearchOrchestrator(make_config(tmp_path)).run(str(tmp_path / "reports"))
    assert summary["excluded_by_experience"] == 1
    assert summary["qualified_candidates"] == 0


def test_unknown_experience_requirement_is_kept_with_transparent_evidence(tmp_path, monkeypatch):
    job = make_job().model_copy(update={"description": "C++ Linux systems development"})
    install_sources(monkeypatch, [job])
    summary = SearchOrchestrator(make_config(tmp_path)).run(str(tmp_path / "reports"))
    assert summary["excluded_by_experience"] == 0
    import json
    from pathlib import Path
    rows = json.loads(Path(summary["reports"][0]).read_text(encoding="utf-8"))
    assert rows[0]["experience_requirement"] == {"minimum_years": None, "maximum_years": None}
    assert rows[0]["freshness_status"] == "within_configured_window"



def test_ai_usage_and_cost_are_reported_only_when_rates_are_configured(tmp_path, monkeypatch):
    install_sources(monkeypatch, [make_job()])

    class Matcher:
        last_usage = {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
        def __init__(self, provider, timeout): pass
        def cache_key(self, job): return "unused-" + job.identity
        def match_batch(self, batch):
            return {job.identity: MatchResult(job_id=job.identity, score=80, reason="evidence") for job in batch}
        def close(self): pass

    monkeypatch.setattr(orchestrator_module, "AIResumeMatcher", Matcher)
    config = make_config(tmp_path, provider="gemini")
    config.matching.input_cost_usd_per_million_tokens = 2.0
    config.matching.output_cost_usd_per_million_tokens = 4.0
    summary = SearchOrchestrator(config).run(str(tmp_path / "reports"))
    assert summary["ai"]["token_usage"] == {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
    assert summary["ai"]["estimated_cost_usd"] == 0.0004
    assert summary["ai"]["cost_estimate_configured"] is True



def test_all_failed_greenhouse_sites_do_not_count_as_success(tmp_path, monkeypatch):
    class FailedGreenhouse:
        name = "greenhouse"
        board_tokens = ["broken"]
        site_status = {}
        def __init__(self, *args, **kwargs): pass
        def fetch(self):
            self.site_status = {"broken": "failed: ValueError"}
            return []
        def close(self): pass

    class EmptyWorkday(FakeSource):
        def __init__(self, *args, **kwargs):
            super().__init__("workday", [])
            self.site_status = {}

    class EmptyLever(FakeSource):
        def __init__(self, *args, **kwargs):
            super().__init__("lever", [])
            self.site_slugs = []

    monkeypatch.setattr(orchestrator_module, "GreenhouseAdapter", FailedGreenhouse)
    monkeypatch.setattr(orchestrator_module, "LeverAdapter", EmptyLever)
    monkeypatch.setattr(orchestrator_module, "WorkdayAdapter", EmptyWorkday)
    config = make_config(tmp_path)
    config.sources.lever = []
    config.sources.workday = []
    summary = SearchOrchestrator(config).run(str(tmp_path / "reports"))
    assert summary["sources"]["greenhouse"] == "failed: 0/1 sites responded"
    assert summary["sources"]["greenhouse:broken"] == "failed: ValueError"
    assert summary["source_health"]["successful"] == 0
    assert summary["run_status"] == "no_sources_succeeded"
