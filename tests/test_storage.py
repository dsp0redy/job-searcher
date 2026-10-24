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
