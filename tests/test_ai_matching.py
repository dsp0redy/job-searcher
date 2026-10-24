from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from job_searcher.ai_matching import AIResumeMatcher, MatchResult
from job_searcher.models import Job


def test_extract_json_accepts_surrounding_text() -> None:
    parsed = AIResumeMatcher._extract_json('Result follows: {"matches": []} done')
    assert parsed == {"matches": []}


def test_extract_json_rejects_missing_object() -> None:
    with pytest.raises(ValueError):
        AIResumeMatcher._extract_json("no json here")


def test_match_result_rejects_out_of_range_scores() -> None:
    with pytest.raises(ValidationError):
        MatchResult(job_id="job-1", score=101, reason="not valid")


def test_matcher_uses_batch_response_and_ignores_unknown_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("RESUME_TEXT", "C++ Linux engineer with gRPC experience")
    matcher = AIResumeMatcher("gemini")
    job = Job(
        source="workday",
        source_id="REQ-1",
        company="Example",
        title="C++ Engineer",
        location="Bengaluru",
        url="https://example.com/jobs/1",
        description="C++ and Linux",
    )
    response = {
        "matches": [
            {"job_id": job.identity, "score": 82, "reason": "Strong C++ and Linux overlap",
             "missing_skills": ["QNX"], "improvements": ["Add verified QNX project details"]},
            {"job_id": "not-a-real-job", "score": 99, "reason": "Ignore this result"},
        ]
    }
    monkeypatch.setattr(matcher, "_request", lambda prompt: json.dumps(response))
    try:
        results = matcher.match_batch([job])
    finally:
        matcher.close()

    assert list(results) == [job.identity]
    assert results[job.identity].score == 82
    assert results[job.identity].missing_skills == ["QNX"]


def test_ai_provider_requires_secret_and_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("RESUME_TEXT", raising=False)
    monkeypatch.delenv("RESUME_FILE", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        AIResumeMatcher("gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    with pytest.raises(ValueError, match="RESUME_TEXT"):
        AIResumeMatcher("gemini")


def test_matcher_can_load_a_local_text_resume_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("C++ Linux developer", encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("RESUME_TEXT", raising=False)
    monkeypatch.setenv("RESUME_FILE", str(resume_file))
    matcher = AIResumeMatcher("gemini")
    try:
        assert matcher.resume_text == "C++ Linux developer"
    finally:
        matcher.close()


def test_cache_key_changes_when_resume_text_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("RESUME_FILE", raising=False)
    monkeypatch.setenv("RESUME_TEXT", "C++ developer")
    first = AIResumeMatcher("gemini")
    job = Job(
        source="greenhouse",
        source_id="REQ-7",
        company="Example",
        title="Linux Engineer",
        location="India",
        url="https://example.com/jobs/7",
    )
    first_key = first.cache_key(job)
    first.close()

    monkeypatch.setenv("RESUME_TEXT", "Python developer")
    second = AIResumeMatcher("gemini")
    try:
        assert second.cache_key(job) != first_key
    finally:
        second.close()


def test_post_retries_transient_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("RESUME_TEXT", "C++ Linux engineer")
    matcher = AIResumeMatcher("gemini")
    calls = 0

    def flaky_post(url: str, **kwargs: object) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("temporary timeout")
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(matcher.client, "post", flaky_post)
    monkeypatch.setattr("job_searcher.ai_matching.time.sleep", lambda _: None)
    try:
        response = matcher._post_with_retries("https://example.com", json={})
        assert response.status_code == 200
        assert calls == 2
    finally:
        matcher.close()




def test_openai_compatible_provider_requires_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("RESUME_TEXT", "C++ Linux engineer")
    with pytest.raises(ValueError, match="AI_BASE_URL"):
        AIResumeMatcher("openai_compatible")


def test_openai_compatible_provider_uses_configured_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_BASE_URL", "https://api.example.com/v1/")
    monkeypatch.setenv("AI_MODEL", "example-model")
    monkeypatch.setenv("RESUME_TEXT", "C++ Linux engineer")
    matcher = AIResumeMatcher("openai_compatible")
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        calls.append((url, kwargs))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"matches": []}'}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(matcher.client, "post", fake_post)
    try:
        assert matcher._request("test prompt") == '{"matches": []}'
        assert calls[0][0] == "https://api.example.com/v1/chat/completions"
        assert calls[0][1]["headers"]["Authorization"] == "Bearer test-key"
        assert calls[0][1]["json"]["model"] == "example-model"
    finally:
        matcher.close()


def test_openai_compatible_provider_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.setenv("AI_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("AI_MODEL", "example-model")
    monkeypatch.setenv("RESUME_TEXT", "C++ Linux engineer")
    with pytest.raises(ValueError, match="AI_API_KEY"):
        AIResumeMatcher("openai_compatible")
