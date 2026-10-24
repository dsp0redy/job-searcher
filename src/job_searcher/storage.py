"""SQLite persistence for jobs, match cache, and scan history."""
from __future__ import annotations
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any
from .models import Job

LOG = logging.getLogger(__name__)


class JobStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    identity TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
                    company TEXT NOT NULL, title TEXT NOT NULL, location TEXT NOT NULL,
                    url TEXT NOT NULL, description TEXT NOT NULL, posted_at TEXT,
                    employment_type TEXT, experience_min REAL, experience_max REAL,
                    discovered_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS match_cache (
                    cache_key TEXT PRIMARY KEY, provider TEXT NOT NULL, result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS scan_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT, status TEXT NOT NULL, summary_json TEXT NOT NULL DEFAULT '{}'
                );
            """)

    def upsert_jobs(self, jobs: list[Job]) -> int:
        """Insert/update postings; return number of identities not previously stored."""
        inserted = 0
        with self._connect() as db:
            for job in jobs:
                payload = job.model_dump_json()
                exists = db.execute("SELECT 1 FROM jobs WHERE identity=?", (job.identity,)).fetchone()
                db.execute("""INSERT INTO jobs(identity,source,source_id,company,title,location,url,
                    description,posted_at,employment_type,experience_min,experience_max,discovered_at,payload)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(identity) DO UPDATE SET
                    title=excluded.title,location=excluded.location,url=excluded.url,
                    description=excluded.description,posted_at=excluded.posted_at,payload=excluded.payload""",
                    (job.identity, job.source, job.source_id, job.company, job.title, job.location,
                     str(job.url), job.description, job.posted_at.isoformat() if job.posted_at else None,
                     job.employment_type, job.experience_min, job.experience_max,
                     job.discovered_at.isoformat(), payload))
                inserted += int(exists is None)
        return inserted

    def get_match(self, cache_key: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT result_json FROM match_cache WHERE cache_key=?", (cache_key,)).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            LOG.warning("Ignoring malformed cached match for key %s", cache_key[:12])
            return None
        return payload if isinstance(payload, dict) else None

    def save_match(self, cache_key: str, provider: str, result: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO match_cache(cache_key,provider,result_json) VALUES(?,?,?) "
                       "ON CONFLICT(cache_key) DO UPDATE SET provider=excluded.provider,result_json=excluded.result_json",
                       (cache_key, provider, json.dumps(result, ensure_ascii=False)))

    def start_run(self) -> int:
        with self._connect() as db:
            cursor = db.execute("INSERT INTO scan_runs(status) VALUES('running')")
            return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str, summary: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute("UPDATE scan_runs SET finished_at=CURRENT_TIMESTAMP,status=?,summary_json=? WHERE run_id=?",
                       (status, json.dumps(summary, ensure_ascii=False), run_id))
