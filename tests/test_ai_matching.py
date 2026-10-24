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

def test_openai_compatible_provider_rejects_insecure_remote_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_BASE_URL", "http://api.example.com/v1")
    monkeypatch.setenv("AI_MODEL", "example-model")
    monkeypatch.setenv("RESUME_TEXT", "C++ Linux engineer")
    with pytest.raises(ValueError, match="HTTPS"):
        AIResumeMatcher("openai_compatible")

def make_job(source_id: str = "REQ-1") -> Job:
    return Job(source="workday", source_id=source_id, company="Example", title="C++ Engineer",
               location="Bengaluru", url=f"https://example.com/jobs/{source_id}", description="C++ Linux")


def configure_ai(monkeypatch: pytest.MonkeyPatch, provider: str = "gemini") -> None:
    monkeypatch.setenv("RESUME_TEXT", "C++ Linux engineer")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "claude-key")
    monkeypatch.setenv("AI_API_KEY", "compatible-key")
    monkeypatch.setenv("AI_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("AI_MODEL", "compatible-model")


def test_extract_json_rejects_invalid_json_and_non_object():
    with pytest.raises(ValueError):
        AIResumeMatcher._extract_json('{"bad": }')
    with pytest.raises(ValueError, match="JSON object"):
        AIResumeMatcher._extract_json('[{"matches": []}]')


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="AI provider"):
        AIResumeMatcher("ollama")


def test_remote_http_endpoint_is_rejected_but_localhost_is_allowed(monkeypatch):
    configure_ai(monkeypatch)
    monkeypatch.setenv("AI_BASE_URL", "http://api.example.com/v1")
    with pytest.raises(ValueError, match="HTTPS"):
        AIResumeMatcher("openai_compatible")
    monkeypatch.setenv("AI_BASE_URL", "http://localhost:11434/v1")
    matcher = AIResumeMatcher("openai_compatible")
    matcher.close()


@pytest.mark.parametrize("url", ["relative/path", "ftp://api.example.com/v1", "https:///missing-host"])
def test_compatible_endpoint_must_be_absolute_http_url(monkeypatch, url):
    configure_ai(monkeypatch)
    monkeypatch.setenv("AI_BASE_URL", url)
    with pytest.raises(ValueError, match="absolute HTTP"):
        AIResumeMatcher("openai_compatible")


def test_blank_model_uses_default(monkeypatch):
    configure_ai(monkeypatch)
    monkeypatch.setenv("GEMINI_MODEL", "")
    matcher = AIResumeMatcher("gemini")
    try:
        assert matcher.model == "gemini-3.5-flash-lite"
    finally:
        matcher.close()


def test_resume_file_missing_is_reported(monkeypatch, tmp_path):
    configure_ai(monkeypatch)
    monkeypatch.delenv("RESUME_TEXT", raising=False)
    monkeypatch.setenv("RESUME_FILE", str(tmp_path / "absent.txt"))
    with pytest.raises(ValueError, match="does not exist"):
        AIResumeMatcher("gemini")


def test_resume_text_file_is_trimmed(monkeypatch, tmp_path):
    configure_ai(monkeypatch)
    path = tmp_path / "resume.txt"
    path.write_text("  C++ engineer  \n", encoding="utf-8")
    monkeypatch.delenv("RESUME_TEXT", raising=False)
    monkeypatch.setenv("RESUME_FILE", str(path))
    matcher = AIResumeMatcher("gemini")
    try:
        assert matcher.resume_text == "C++ engineer"
    finally:
        matcher.close()


def test_match_batch_empty_input_does_not_call_provider(monkeypatch):
    configure_ai(monkeypatch)
    matcher = AIResumeMatcher("gemini")
    monkeypatch.setattr(matcher, "_request", lambda _: pytest.fail("request should not run"))
    try:
        assert matcher.match_batch([]) == {}
    finally:
        matcher.close()


def test_match_batch_discards_invalid_duplicate_and_missing_ids(monkeypatch):
    configure_ai(monkeypatch)
    matcher = AIResumeMatcher("gemini")
    job = make_job()
    response = {"matches": [
        {"job_id": job.identity, "score": 70, "reason": "first"},
        {"job_id": job.identity, "score": 90, "reason": "duplicate"},
        {"job_id": "unknown", "score": 90, "reason": "unknown"},
        {"job_id": job.identity, "score": 101, "reason": "invalid score"},
        "not an object",
    ]}
    monkeypatch.setattr(matcher, "_request", lambda _: json.dumps(response))
    try:
        results = matcher.match_batch([job])
        assert results[job.identity].score == 70
    finally:
        matcher.close()


@pytest.mark.parametrize("raw", [
    "not json",
    '{"matches": "not a list"}',
    '{"matches": [{"job_id": "x", "score": 50, "reason": "missing required id"}]}',
])
def test_match_batch_malformed_responses_fail_closed(monkeypatch, raw):
    configure_ai(monkeypatch)
    matcher = AIResumeMatcher("gemini")
    monkeypatch.setattr(matcher, "_request", lambda _: raw)
    try:
        assert matcher.match_batch([make_job()]) == {}
    finally:
        matcher.close()


def test_retryable_http_status_retries_then_succeeds(monkeypatch):
    configure_ai(monkeypatch)
    matcher = AIResumeMatcher("gemini")
    calls = 0
    def post(url, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            request = httpx.Request("POST", url)
            raise httpx.HTTPStatusError("rate limited", request=request, response=httpx.Response(429, request=request))
        return httpx.Response(200, request=httpx.Request("POST", url))
    monkeypatch.setattr(matcher.client, "post", post)
    monkeypatch.setattr("job_searcher.ai_matching.time.sleep", lambda _: None)
    try:
        assert matcher._post_with_retries("https://example.com") .status_code == 200
        assert calls == 2
    finally:
        matcher.close()


def test_non_retryable_http_status_is_not_retried(monkeypatch):
    configure_ai(monkeypatch)
    matcher = AIResumeMatcher("gemini")
    calls = 0
    def post(url, **kwargs):
        nonlocal calls
        calls += 1
        request = httpx.Request("POST", url)
        raise httpx.HTTPStatusError("bad request", request=request, response=httpx.Response(400, request=request))
    monkeypatch.setattr(matcher.client, "post", post)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            matcher._post_with_retries("https://example.com")
        assert calls == 1
    finally:
        matcher.close()


def test_retry_exhaustion_raises_after_three_attempts(monkeypatch):
    configure_ai(monkeypatch)
    matcher = AIResumeMatcher("gemini")
    calls = 0
    def post(url, **kwargs):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=httpx.Request("POST", url))
    monkeypatch.setattr(matcher.client, "post", post)
    monkeypatch.setattr("job_searcher.ai_matching.time.sleep", lambda _: None)
    try:
        with pytest.raises(httpx.ConnectError):
            matcher._post_with_retries("https://example.com")
        assert calls == 3
    finally:
        matcher.close()


@pytest.mark.parametrize(("provider", "response_json", "expected"), [
    ("gemini", {"candidates": [{"content": {"parts": [{"text": "{\"matches\": []}"}]}}]}, "{\"matches\": []}"),
    ("claude", {"content": [{"type": "text", "text": "one"}, {"type": "tool", "text": "ignored"}, {"type": "text", "text": "two"}]}, "one\ntwo"),
    ("openai_compatible", {"choices": [{"message": {"content": "{\"matches\": []}"}}]}, "{\"matches\": []}"),
])
def test_provider_request_payloads(provider, response_json, expected, monkeypatch):
    configure_ai(monkeypatch)
    matcher = AIResumeMatcher(provider)
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json=response_json, request=httpx.Request("POST", url))
    monkeypatch.setattr(matcher.client, "post", post)
    try:
        assert matcher._request("prompt") == expected
        assert calls
        if provider == "claude":
            assert calls[0][1]["headers"]["anthropic-version"] == "2023-06-01"
        if provider == "gemini":
            assert calls[0][1]["headers"]["x-goog-api-key"] == "gemini-key"
            assert "params" not in calls[0][1]
    finally:
        matcher.close()


def test_cache_key_changes_when_job_description_changes(monkeypatch):
    configure_ai(monkeypatch)
    matcher = AIResumeMatcher("gemini")
    job = make_job()
    changed = job.model_copy(update={"description": "Different"})
    try:
        assert matcher.cache_key(job) != matcher.cache_key(changed)
    finally:
        matcher.close()

def test_extract_json_rejects_unclosed_object():
    with pytest.raises(ValueError):
        AIResumeMatcher._extract_json("prefix {")


def test_pdf_resume_file_is_read_and_empty_text_rejected(monkeypatch, tmp_path):
    from pypdf import PdfWriter

    configure_ai(monkeypatch)
    pdf_path = tmp_path / "resume.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as stream:
        writer.write(stream)
    monkeypatch.delenv("RESUME_TEXT", raising=False)
    monkeypatch.setenv("RESUME_FILE", str(pdf_path))
    with pytest.raises(ValueError, match="RESUME_TEXT or RESUME_FILE"):
        AIResumeMatcher("gemini")


def test_match_batch_handles_provider_payload_shape_errors(monkeypatch):
    configure_ai(monkeypatch)
    matcher = AIResumeMatcher("gemini")
    monkeypatch.setattr(matcher, "_request", lambda _: '{"matches": []}')
    try:
        assert matcher.match_batch([make_job()]) == {}
    finally:
        matcher.close()


def test_retryable_server_error_raises_after_final_attempt(monkeypatch):
    configure_ai(monkeypatch)
    matcher = AIResumeMatcher("gemini")
    calls = 0
    def post(url, **kwargs):
        nonlocal calls
        calls += 1
        request = httpx.Request("POST", url)
        raise httpx.HTTPStatusError("server error", request=request, response=httpx.Response(503, request=request))
    monkeypatch.setattr(matcher.client, "post", post)
    monkeypatch.setattr("job_searcher.ai_matching.time.sleep", lambda _: None)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            matcher._post_with_retries("https://example.com")
        assert calls == 3
    finally:
        matcher.close()

def test_compatible_provider_requires_model(monkeypatch):
    configure_ai(monkeypatch)
    monkeypatch.setenv("AI_MODEL", " ")
    with pytest.raises(ValueError, match="AI_MODEL"):
        AIResumeMatcher("openai_compatible")

def test_retry_loop_has_defensive_empty_range_guard(monkeypatch):
    import job_searcher.ai_matching as ai_module
    configure_ai(monkeypatch)
    matcher = AIResumeMatcher("gemini")
    monkeypatch.setattr(ai_module, "range", lambda *_: [], raising=False)
    try:
        with pytest.raises(RuntimeError, match="retries exhausted"):
            matcher._post_with_retries("https://example.com")
    finally:
        matcher.close()




@pytest.mark.parametrize(
    ("provider", "payload", "expected"),
    [
        ("gemini", {"usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 30, "totalTokenCount": 150}},
         {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}),
        ("claude", {"usage": {"input_tokens": 90, "output_tokens": 20}},
         {"input_tokens": 90, "output_tokens": 20, "total_tokens": 110}),
        ("openai_compatible", {"usage": {"prompt_tokens": 70, "completion_tokens": 10, "total_tokens": 80}},
         {"input_tokens": 70, "output_tokens": 10, "total_tokens": 80}),
    ],
)
def test_capture_provider_usage(provider, payload, expected, monkeypatch):
    configure_ai(monkeypatch)
    matcher = AIResumeMatcher(provider)
    try:
        matcher._capture_usage(payload)
        assert matcher.last_usage == expected
    finally:
        matcher.close()


@pytest.mark.parametrize("payload", [None, [], {"usage": "invalid"}, {"usage": {"input_tokens": -1, "output_tokens": True}}])
def test_capture_usage_handles_missing_or_invalid_metadata(payload, monkeypatch):
    configure_ai(monkeypatch)
    matcher = AIResumeMatcher("claude")
    try:
        matcher._capture_usage(payload)
        assert matcher.last_usage == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    finally:
        matcher.close()


def test_match_result_accepts_whole_number_floats_but_not_fractions_or_strings():
    from pydantic import ValidationError

    from job_searcher.ai_matching import MatchResult

    assert MatchResult(job_id="a", score=85.0, reason="ok").score == 85
    for bad in (85.5, "85", True):
        with pytest.raises(ValidationError):
            MatchResult(job_id="a", score=bad, reason="ok")
