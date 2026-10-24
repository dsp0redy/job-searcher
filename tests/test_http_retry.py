from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from job_searcher.adapters.base import JobSource


class ConcreteSource(JobSource):
    name = "retry-test"

    def fetch(self):
        return []


def response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    request = httpx.Request("GET", "https://example.com/jobs")
    return httpx.Response(status, headers=headers, request=request)


def test_retry_after_numeric_is_respected_and_bounded():
    source = ConcreteSource()
    try:
        assert source._retry_delay(response(429, {"Retry-After": "4"}), 0) == 4.0
        assert source._retry_delay(response(429, {"Retry-After": "999"}), 0) == 30.0
        assert source._retry_delay(response(429, {"Retry-After": "-1"}), 0) == 0.0
    finally:
        source.close()


def test_retry_after_http_date_is_parsed(monkeypatch):
    import job_searcher.adapters.base as base_module

    source = ConcreteSource()
    try:
        future = datetime.now(timezone.utc) + timedelta(seconds=10)
        delay = source._retry_delay(response(429, {"Retry-After": format_datetime(future)}), 0)
        assert 0 <= delay <= 10
        monkeypatch.setattr(
            base_module, "parsedate_to_datetime", lambda _: datetime(2030, 1, 1)
        )
        assert source._retry_delay(response(429, {"Retry-After": "future"}), 0) > 0
    finally:
        source.close()


def test_retry_after_invalid_or_missing_uses_backoff():
    source = ConcreteSource()
    try:
        assert source._retry_delay(response(429), 1) == 2.0
        assert source._retry_delay(response(429, {"Retry-After": "not-a-date"}), 2) == 4.0
    finally:
        source.close()


def test_get_json_retries_rate_limit_then_succeeds(monkeypatch):
    source = ConcreteSource()
    calls = 0
    delays = []

    def get(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return response(429, {"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("GET", args[0]))

    monkeypatch.setattr(source.client, "get", get)
    monkeypatch.setattr("time.sleep", delays.append)
    try:
        assert source.get_json("https://example.com/jobs") == {"ok": True}
        assert calls == 2
        assert delays == [0.0]
    finally:
        source.close()


def test_get_json_does_not_retry_client_errors(monkeypatch):
    source = ConcreteSource()
    calls = 0

    def get(*args, **kwargs):
        nonlocal calls
        calls += 1
        return response(400)

    monkeypatch.setattr(source.client, "get", get)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            source.get_json("https://example.com/jobs")
        assert calls == 1
    finally:
        source.close()


def test_get_json_retries_server_errors_then_raises(monkeypatch):
    source = ConcreteSource()
    calls = 0

    def get(*args, **kwargs):
        nonlocal calls
        calls += 1
        return response(503)

    monkeypatch.setattr(source.client, "get", get)
    monkeypatch.setattr("time.sleep", lambda _: None)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            source.get_json("https://example.com/jobs")
        assert calls == source.MAX_ATTEMPTS
    finally:
        source.close()


def test_get_json_retries_transient_network_error(monkeypatch):
    source = ConcreteSource()
    calls = 0
    monkeypatch.setattr("time.sleep", lambda _: None)

    def get(url, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("temporary", request=httpx.Request("GET", url))
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("GET", url))

    monkeypatch.setattr(source.client, "get", get)
    try:
        assert source.get_json("https://example.com/jobs") == {"ok": True}
        assert calls == 2
    finally:
        source.close()


def test_get_json_raises_after_network_retries_are_exhausted(monkeypatch):
    source = ConcreteSource()
    calls = 0
    monkeypatch.setattr("time.sleep", lambda _: None)

    def get(url, **kwargs):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=httpx.Request("GET", url))

    monkeypatch.setattr(source.client, "get", get)
    try:
        with pytest.raises(httpx.ConnectError):
            source.get_json("https://example.com/jobs")
        assert calls == source.MAX_ATTEMPTS
    finally:
        source.close()



def test_get_json_defensive_guard_when_attempt_count_is_zero():
    source = ConcreteSource()
    source.MAX_ATTEMPTS = 0
    try:
        with pytest.raises(RuntimeError, match="retries exhausted"):
            source.get_json("https://example.com/jobs")
    finally:
        source.close()
