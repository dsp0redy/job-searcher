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

def test_corrupt_match_cache_is_treated_as_cache_miss(tmp_path):
    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    with store._connect() as db:
        db.execute(
            "INSERT INTO match_cache(cache_key,provider,result_json) VALUES(?,?,?)",
            ("broken", "gemini", "{invalid"),
        )
    assert store.get_match("broken") is None


def test_non_object_match_cache_is_treated_as_cache_miss(tmp_path):
    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    with store._connect() as db:
        db.execute(
            "INSERT INTO match_cache(cache_key,provider,result_json) VALUES(?,?,?)",
            ("array", "gemini", "[]"),
        )
    assert store.get_match("array") is None




def test_review_queue_status_round_trip_and_update(tmp_path):
    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    job = Job(source="lever", source_id="review-1", company="Acme", title="Engineer",
              url="https://example.com/review-1")
    store.upsert_jobs([job])
    assert store.get_review_status(job.identity) is None
    first = store.set_review_status(job.identity, "saved", "Review later")
    assert first["status"] == "saved"
    assert first["notes"] == "Review later"
    updated = store.set_review_status(job.identity, "applied", "Applied on company site")
    assert updated["status"] == "applied"
    assert store.get_review_status(job.identity)["notes"] == "Applied on company site"


def test_review_queue_rejects_unknown_job_and_invalid_status(tmp_path):
    import pytest

    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    with pytest.raises(KeyError, match="Unknown job identity"):
        store.set_review_status("missing", "saved")
    job = Job(source="lever", source_id="review-2", company="Acme", title="Engineer",
              url="https://example.com/review-2")
    store.upsert_jobs([job])
    with pytest.raises(ValueError, match="status must be one of"):
        store.set_review_status(job.identity, "interview")


def test_retention_prunes_old_jobs_match_cache_and_scan_history(tmp_path):
    from datetime import datetime, timedelta, timezone

    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    old = datetime.now(timezone.utc) - timedelta(days=90)
    job = Job(source="lever", source_id="old", company="Acme", title="Engineer",
              url="https://example.com/old", discovered_at=old)
    store.upsert_jobs([job])
    store.set_review_status(job.identity, "saved")
    store.save_match("old-cache", "gemini", {"score": 80})
    run_id = store.start_run()
    store.finish_run(run_id, "success", {})
    with store._connect() as db:
        db.execute("UPDATE match_cache SET created_at=?", (old.strftime("%Y-%m-%d %H:%M:%S"),))
        db.execute(
            "UPDATE scan_runs SET started_at=?, finished_at=? WHERE run_id=?",
            (old.strftime("%Y-%m-%d %H:%M:%S"), old.strftime("%Y-%m-%d %H:%M:%S"), run_id),
        )
    assert store.prune_old_data(30) == {"jobs": 1, "match_cache": 1, "scan_runs": 1}
    assert store.get_review_status(job.identity) is None
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_retention_rejects_out_of_range_days(tmp_path):
    import pytest

    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    for days in (0, 3651):
        with pytest.raises(ValueError, match="retention_days"):
            store.prune_old_data(days)


def test_sqlite_backup_is_restorable_and_rejects_same_path(tmp_path):
    import sqlite3
    import pytest

    database = tmp_path / "jobs.sqlite3"
    store = JobStore(str(database))
    job = Job(source="lever", source_id="backup-1", company="Acme", title="Engineer",
              url="https://example.com/backup-1")
    store.upsert_jobs([job])
    backup = store.backup_to(str(tmp_path / "backup" / "jobs-copy.sqlite3"))
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    with pytest.raises(ValueError, match="must differ"):
        store.backup_to(str(database))



def test_schema_version_is_recorded_and_newer_database_is_rejected(tmp_path):
    import sqlite3
    import pytest

    database = tmp_path / "versioned.sqlite3"
    store = JobStore(str(database))
    with store._connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == JobStore.CURRENT_SCHEMA_VERSION
    newer = tmp_path / "newer.sqlite3"
    with sqlite3.connect(newer) as db:
        db.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="newer than supported"):
        JobStore(str(newer))
