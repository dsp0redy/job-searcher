from job_searcher.models import Job
from job_searcher.storage import JobStore


def test_upsert_counts_only_new_identities(tmp_path):
    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    job = Job(source="lever", source_id="1", company="Acme", title="Engineer",
              url="https://example.com/jobs/1")
    assert store.upsert_jobs([job]) == 1
    assert store.upsert_jobs([job]) == 0


def test_match_cache_round_trip(tmp_path):
    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    store.save_match("key", "local", {"score": 42})
    assert store.get_match("key") == {"score": 42}

def test_get_missing_match_returns_none(tmp_path):
    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    assert store.get_match("missing") is None


def test_upsert_updates_existing_job_payload(tmp_path):
    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    job = Job(source="lever", source_id="1", company="Acme", title="Engineer",
              url="https://example.com/jobs/1", description="old")
    updated = job.model_copy(update={"title": "Senior Engineer", "description": "new"})
    assert store.upsert_jobs([job]) == 1
    assert store.upsert_jobs([updated]) == 0
    with store._connect() as db:
        row = db.execute("SELECT title, description FROM jobs WHERE identity=?", (job.identity,)).fetchone()
    assert row["title"] == "Senior Engineer"
    assert row["description"] == "new"


def test_scan_run_lifecycle_persists_summary(tmp_path):
    import json

    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    run_id = store.start_run()
    store.finish_run(run_id, "success", {"postings_fetched": 3})
    with store._connect() as db:
        row = db.execute("SELECT status, finished_at, summary_json FROM scan_runs WHERE run_id=?", (run_id,)).fetchone()
    assert row["status"] == "success"
    assert row["finished_at"] is not None
    assert json.loads(row["summary_json"]) == {"postings_fetched": 3}


def test_save_match_replaces_existing_cache_entry(tmp_path):
    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    store.save_match("same-key", "gemini", {"score": 50})
    store.save_match("same-key", "claude", {"score": 90})
    assert store.get_match("same-key") == {"score": 90}

