from __future__ import annotations

import json

from job_searcher.ai_matching import AIResumeMatcher
from job_searcher.models import Job


def _job(source_id: str) -> Job:
    return Job(
        source="workday",
        source_id=source_id,
        company="Example",
        title="C++ Engineer",
        location="Bengaluru",
        url=f"https://example.com/jobs/{source_id}",
        description="C++ and Linux systems engineering",
    )


def _configure(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("RESUME_TEXT", "C++ Linux systems engineer with gRPC experience")


def test_malformed_ai_response_gets_one_correction_attempt(monkeypatch) -> None:
    _configure(monkeypatch)
    matcher = AIResumeMatcher("gemini")
    job = _job("REQ-1")
    calls: list[str] = []
    good_response = {
        "matches": [{
            "job_id": job.identity,
            "score": 82,
            "reason": "Resume evidence matches C++ and Linux requirements",
        }]
    }

    def fake_request(prompt: str) -> str:
        calls.append(prompt)
        if len(calls) == 1:
            return "not valid JSON"
        return json.dumps(good_response)

    monkeypatch.setattr(matcher, "_request", fake_request)
    try:
        results = matcher.match_batch([job])
    finally:
        matcher.close()

    assert len(calls) == 2
    assert "CORRECTION REQUIRED" in calls[1]
    assert results[job.identity].score == 82


def test_partial_ai_response_retries_only_missing_job_ids(monkeypatch) -> None:
    _configure(monkeypatch)
    matcher = AIResumeMatcher("gemini")
    first = _job("REQ-1")
    second = _job("REQ-2")
    calls: list[str] = []

    def fake_request(prompt: str) -> str:
        calls.append(prompt)
        if len(calls) == 1:
            return json.dumps({
                "matches": [{
                    "job_id": first.identity,
                    "score": 80,
                    "reason": "Relevant C++ and Linux experience",
                }]
            })
        assert second.identity in prompt
        assert first.identity not in prompt.split("CORRECTION REQUIRED:", 1)[1]
        return json.dumps({
            "matches": [{
                "job_id": second.identity,
                "score": 75,
                "reason": "Relevant Linux systems experience",
            }]
        })

    monkeypatch.setattr(matcher, "_request", fake_request)
    try:
        results = matcher.match_batch([first, second])
    finally:
        matcher.close()

    assert len(calls) == 2
    assert set(results) == {first.identity, second.identity}


def test_ai_matching_returns_recovered_matches_if_correction_fails(monkeypatch) -> None:
    _configure(monkeypatch)
    matcher = AIResumeMatcher("gemini")
    job = _job("REQ-1")
    missing_job = _job("REQ-2")
    calls = 0

    def fake_request(prompt: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            return json.dumps({
                "matches": [{
                    "job_id": job.identity,
                    "score": 80,
                    "reason": "Relevant C++ and Linux experience",
                }]
            })
        return "still not valid JSON"

    monkeypatch.setattr(matcher, "_request", fake_request)
    try:
        results = matcher.match_batch([job, missing_job])
    finally:
        matcher.close()

    assert calls == 2
    assert list(results) == [job.identity]
    assert results[job.identity].score == 80
