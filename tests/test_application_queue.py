from __future__ import annotations

import json

import pytest

from job_searcher.reporting import write_application_queue


def test_application_queue_filters_and_sorts_eligible_jobs(tmp_path):
    rows = [
        {"identity": "low", "company": "LowCo", "title": "Engineer", "url": "https://example.com/low",
         "score": 69, "ai_status": "matched"},
        {"identity": "failed", "company": "FailedCo", "title": "Engineer", "url": "https://example.com/failed",
         "score": 99, "ai_status": "failed"},
        {"identity": "deferred", "company": "DeferredCo", "title": "Engineer", "url": "https://example.com/deferred",
         "score": 98, "ai_status": "deferred"},
        {"identity": "bad-score", "company": "BadCo", "title": "Engineer", "url": "https://example.com/bad",
         "score": "95", "ai_status": "matched"},
        {"identity": "bool-score", "company": "BoolCo", "title": "Engineer", "url": "https://example.com/bool",
         "score": True, "ai_status": "matched"},
        {"identity": "local", "company": "Beta", "title": "Local Engineer", "url": "https://example.com/local",
         "score": 75, "ai_status": "disabled", "skill_hits": ["C++"]},
        {"identity": "ai", "company": "Acme", "title": "C++ Engineer", "url": "https://example.com/ai",
         "score": 90, "ai_status": "matched", "missing_skills": ["Rust"]},
    ]
    path = write_application_queue(str(tmp_path), rows, 70)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["minimum_score"] == 70
    assert payload["requires_human_review"] is True
    assert payload["auto_submit"] is False
    assert payload["count"] == 2
    assert [job["identity"] for job in payload["jobs"]] == ["ai", "local"]
    assert payload["jobs"][0]["score_basis"] == "ai_match"
    assert payload["jobs"][1]["score_basis"] == "local_heuristic"
    assert "not an ATS score" in payload["score_note"]
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_application_queue_accepts_missing_status_as_local_and_zero_threshold(tmp_path):
    path = write_application_queue(str(tmp_path), [{"score": 0}], 0)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["jobs"][0]["ai_status"] == "disabled"
    assert payload["jobs"][0]["score_basis"] == "local_heuristic"


@pytest.mark.parametrize("threshold", [-1, 101])
def test_application_queue_rejects_invalid_threshold(tmp_path, threshold):
    with pytest.raises(ValueError, match="minimum_score"):
        write_application_queue(str(tmp_path), [], threshold)
