"""Configuration loading with safe defaults and validation."""
from pathlib import Path
from typing import Any
import os
import yaml
from pydantic import BaseModel, Field


class ProfileConfig(BaseModel):
    titles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    minimum_experience_years: float | None = Field(default=None, ge=0, le=80)
    maximum_experience_years: float | None = Field(default=None, ge=0, le=80)
    skills: list[str] = Field(default_factory=list)


class SearchConfig(BaseModel):
    max_pages_per_source: int = Field(default=5, ge=1, le=50)
    request_timeout_seconds: float = Field(default=20, gt=0, le=120)
    max_concurrency: int = Field(default=4, ge=1, le=20)
    posted_within_days: int = Field(default=14, ge=0, le=3650)
    minimum_local_score: int = Field(default=2, ge=0, le=100)


class StorageConfig(BaseModel):
    path: str = "data/jobs.sqlite3"


class MatchingConfig(BaseModel):
    provider: str = "none"
    threshold: int = Field(default=65, ge=0, le=100)
    max_jobs_per_ai_batch: int = Field(default=8, ge=1, le=30)


class SourcesConfig(BaseModel):
    greenhouse: list[str] = Field(default_factory=list)
    lever: list[str] = Field(default_factory=list)
    workday: list[str] = Field(default_factory=list)


class NotificationConfig(BaseModel):
    github_issues: bool = False
    repository: str = ""


class AppConfig(BaseModel):
    profile: ProfileConfig = Field(default_factory=ProfileConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    matching: MatchingConfig = Field(default_factory=MatchingConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)

    @classmethod
    def load(cls, path: str = "config.yml") -> "AppConfig":
        file = Path(path)
        data: Any = yaml.safe_load(file.read_text(encoding="utf-8")) if file.exists() else {}
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ValueError("Configuration root must be a YAML mapping")
        cfg = cls.model_validate(data)
        if cfg.profile.minimum_experience_years is not None and cfg.profile.maximum_experience_years is not None:
            if cfg.profile.minimum_experience_years > cfg.profile.maximum_experience_years:
                raise ValueError("Minimum experience cannot exceed maximum experience")
        return cfg

    @staticmethod
    def github_token() -> str | None:
        return os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
