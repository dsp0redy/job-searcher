from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from job_searcher.adapters.base import JobSource
from job_searcher.adapters.greenhouse import GreenhouseAdapter
from job_searcher.adapters.lever import LeverAdapter


class FakeResponse:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise httpx.HTTPStatusError("bad status", request=httpx.Request("GET", "https://example.com"), response=httpx.Response(self.status))

    def json(self) -> object:
        return self.payload


class ConcreteSource(JobSource):
    name = "test"

    def fetch(self):
        return []


def test_base_get_json_returns_decoded_payload(monkeypatch):
    source = ConcreteSource()
    monkeypatch.setattr(source.client, "get", lambda *args, **kwargs: FakeResponse({"ok": True}))
    try:
        assert source.get_json("https://example.com") == {"ok": True}
    finally:
        source.close()


def test_base_get_json_propagates_http_failure(monkeypatch):
    source = ConcreteSource()
    monkeypatch.setattr(source.client, "get", lambda *args, **kwargs: FakeResponse({}, 503))
    try:
        with pytest.raises(httpx.HTTPStatusError):
            source.get_json("https://example.com")
    finally:
        source.close()


def test_greenhouse_skips_blank_boards_and_invalid_rows(monkeypatch):
    adapter = GreenhouseAdapter(["  ", "board"])
    payload = {"jobs": [
        None,
        {},
        {"id": 1, "title": "Missing URL"},
        {"id": 2, "title": "C++ Engineer", "absolute_url": "https://example.com/2",
         "location": None, "content": None},
    ]}
    calls = []
    monkeypatch.setattr(adapter, "get_json", lambda url, params: (calls.append(url), FakeResponse(payload).json())[1])
    try:
        jobs = adapter.fetch()
    finally:
        adapter.close()
    assert len(calls) == 1
    assert len(jobs) == 1
    assert jobs[0].location == "Unknown"
    assert jobs[0].description == ""


def test_greenhouse_bad_schema_does_not_abort_other_boards(monkeypatch):
    adapter = GreenhouseAdapter(["bad", "good"])
    def response(url, params):
        if "/bad/" in url:
            return {"unexpected": []}
        return {"jobs": [{"id": 1, "title": "Engineer", "absolute_url": "https://example.com/1"}]}
    monkeypatch.setattr(adapter, "get_json", response)
    try:
        jobs = adapter.fetch()
    finally:
        adapter.close()
    assert len(jobs) == 1
    assert jobs[0].company == "good"


def test_greenhouse_network_error_isolated_per_board(monkeypatch):
    adapter = GreenhouseAdapter(["bad", "good"])
    def response(url, params):
        if "/bad/" in url:
            raise httpx.ConnectError("offline")
        return {"jobs": [{"id": 1, "title": "Engineer", "absolute_url": "https://example.com/1"}]}
    monkeypatch.setattr(adapter, "get_json", response)
    try:
        assert len(adapter.fetch()) == 1
    finally:
        adapter.close()


def test_lever_skips_blank_slugs_and_invalid_rows(monkeypatch):
    adapter = LeverAdapter([" ", "board"])
    payload = [
        None, {}, {"id": None, "text": "x", "hostedUrl": "https://example.com"},
        {"id": "1", "text": "C++ Engineer", "hostedUrl": "https://example.com/1",
         "categories": {}, "descriptionPlain": "Linux", "additionalPlain": "gRPC",
         "createdAt": 1_790_000_000_000},
        {"id": "2", "text": "Unknown date", "hostedUrl": "https://example.com/2",
         "categories": {"location": "India"}, "createdAt": "not a timestamp"},
        {"id": "3", "text": "Bad timestamp", "hostedUrl": "https://example.com/3",
         "createdAt": 10**100},
    ]
    calls = []
    monkeypatch.setattr(adapter, "get_json", lambda url, params: (calls.append(url), payload)[1])
    try:
        jobs = adapter.fetch()
    finally:
        adapter.close()
    assert len(calls) == 1
    assert len(jobs) == 3
    assert jobs[0].description == "Linux\ngRPC"
    assert jobs[0].posted_at == datetime.fromtimestamp(1_790_000_000, tz=timezone.utc)
    assert jobs[1].location == "India"
    assert jobs[1].posted_at is None
    assert jobs[2].posted_at is None


def test_lever_bad_schema_and_network_error_are_isolated(monkeypatch):
    adapter = LeverAdapter(["bad-schema", "network", "good"])
    def response(url, params):
        if "bad-schema" in url:
            return {"not": "a list"}
        if "network" in url:
            raise httpx.ConnectError("offline")
        return [{"id": "1", "text": "Engineer", "hostedUrl": "https://example.com/1"}]
    monkeypatch.setattr(adapter, "get_json", response)
    try:
        jobs = adapter.fetch()
    finally:
        adapter.close()
    assert len(jobs) == 1
    assert jobs[0].company == "good"
