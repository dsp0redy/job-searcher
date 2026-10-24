"""Validated domain models shared by adapters and pipeline stages."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class Job(BaseModel):
    """Canonical job posting independent of the source platform."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    source: str = Field(min_length=1, max_length=40)
    source_id: str = Field(min_length=1, max_length=300)
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    location: str = Field(default="Unknown", max_length=300)
    url: HttpUrl
    description: str = Field(default="", max_length=100_000)
    posted_at: datetime | None = None
    employment_type: str | None = None
    experience_min: float | None = Field(default=None, ge=0, le=80)
    experience_max: float | None = Field(default=None, ge=0, le=80)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("posted_at", "discovered_at")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @property
    def identity(self) -> str:
        """Stable identity; source ID is preferred over URL changes."""
        raw = f"{self.source.casefold()}:{self.company.casefold()}:{self.source_id.casefold()}"
        return sha256(raw.encode("utf-8")).hexdigest()
