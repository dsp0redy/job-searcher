from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from job_searcher.config import (
    AppConfig, MatchingConfig, NotificationConfig, ProfileConfig, SearchConfig, StorageConfig,
)


def test_load_missing_file_uses_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    config = AppConfig.load(str(tmp_path / "missing.yml"))
    assert config.matching.provider == "none"
    assert config.sources.greenhouse == []


def test_load_empty_yaml_uses_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    path = tmp_path / "empty.yml"
    path.write_text("", encoding="utf-8")
    assert AppConfig.load(str(path)).profile.skills == []


def test_load_rejects_non_mapping_yaml(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    path = tmp_path / "bad.yml"
    path.write_text("- item\n", encoding="utf-8")
    with pytest.raises(ValueError, match="root must be a YAML mapping"):
        AppConfig.load(str(path))


def test_environment_provider_override_is_case_insensitive(tmp_path, monkeypatch):
    path = tmp_path / "config.yml"
    path.write_text("matching:\n  provider: none\n", encoding="utf-8")
    monkeypatch.setenv("AI_PROVIDER", "GEMINI")
    assert AppConfig.load(str(path)).matching.provider == "gemini"


def test_environment_override_handles_null_matching_mapping(tmp_path, monkeypatch):
    path = tmp_path / "config.yml"
    path.write_text("matching: null\n", encoding="utf-8")
    monkeypatch.setenv("AI_PROVIDER", "claude")
    assert AppConfig.load(str(path)).matching.provider == "claude"


def test_environment_override_rejects_non_mapping_matching(tmp_path, monkeypatch):
    path = tmp_path / "config.yml"
    path.write_text("matching: []\n", encoding="utf-8")
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    with pytest.raises(ValueError, match="matching.*mapping"):
        AppConfig.load(str(path))


def test_load_rejects_invalid_yaml(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    path = tmp_path / "bad.yml"
    path.write_text("profile: [unterminated", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        AppConfig.load(str(path))


def test_github_environment_helpers(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "primary")
    monkeypatch.setenv("GH_TOKEN", "fallback")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    assert AppConfig.github_token() == "primary"
    assert AppConfig.github_repository() == "owner/repo"
    monkeypatch.delenv("GITHUB_TOKEN")
    assert AppConfig.github_token() == "fallback"
    monkeypatch.delenv("GH_TOKEN")
    assert AppConfig.github_token() is None


def test_profile_experience_range_validation():
    assert ProfileConfig(minimum_experience_years=2, maximum_experience_years=3)
    with pytest.raises(ValidationError, match="Minimum experience"):
        ProfileConfig(minimum_experience_years=4, maximum_experience_years=3)


@pytest.mark.parametrize("kwargs", [
    {"minimum_experience_years": -1},
    {"maximum_experience_years": 81},
    {"minimum_experience_years": "not-a-number"},
])
def test_profile_rejects_invalid_experience(kwargs):
    with pytest.raises(ValidationError):
        ProfileConfig(**kwargs)


@pytest.mark.parametrize("kwargs", [
    {"max_pages_per_source": 0},
    {"request_timeout_seconds": 0},
    {"max_concurrency": 21},
    {"posted_within_days": -1},
    {"minimum_local_score": 101},
])
def test_search_config_rejects_out_of_range_values(kwargs):
    with pytest.raises(ValidationError):
        SearchConfig(**kwargs)


@pytest.mark.parametrize("provider", ["none", "gemini", "claude", "openai_compatible"])
def test_matching_config_accepts_supported_providers(provider):
    assert MatchingConfig(provider=provider).provider == provider


def test_matching_config_rejects_unknown_provider():
    with pytest.raises(ValidationError):
        MatchingConfig(provider="ollama")


def test_notification_defaults_are_safe():
    config = NotificationConfig()
    assert config.github_issues is False
    assert config.repository == ""



@pytest.mark.parametrize("retention_days", [0, 3651])
def test_storage_retention_window_is_validated(retention_days):
    with pytest.raises(ValidationError):
        StorageConfig(retention_days=retention_days)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"input_cost_usd_per_million_tokens": -1},
        {"output_cost_usd_per_million_tokens": 100001},
    ],
)
def test_ai_cost_rates_are_validated(kwargs):
    with pytest.raises(ValidationError):
        MatchingConfig(**kwargs)
