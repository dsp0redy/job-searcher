"""Cheap, deterministic relevance scoring before any optional AI integration."""
from __future__ import annotations
import re
from hashlib import sha256
from typing import Any
from .config import ProfileConfig
from .models import Job


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.]+", value.casefold()))


def score_job(job: Job, profile: ProfileConfig) -> dict[str, Any]:
    """Return transparent local score and evidence; never invent candidate qualifications."""
    title = job.title.casefold()
    location = job.location.casefold()
    title_hits = [x for x in profile.titles if x.casefold() in title]
    location_hits = [x for x in profile.locations if x.casefold() in location or x.casefold() == "india" and "india" in location]
    corpus = _tokens(f"{job.title} {job.description}")
    skill_hits = [skill for skill in profile.skills if _tokens(skill) and _tokens(skill) <= corpus]
    score = min(100, len(title_hits) * 30 + len(location_hits) * 15 + len(skill_hits) * 8)
    if not profile.titles and not profile.locations and not profile.skills:
        score = 0
    return {"score": score, "title_hits": title_hits, "location_hits": location_hits,
            "skill_hits": skill_hits, "reason": "Local keyword evidence only; not an interview probability."}


def cache_key(job: Job, profile: ProfileConfig, provider: str = "local-v1") -> str:
    text = "|".join([job.identity, job.title, job.description, ",".join(profile.skills), provider])
    return sha256(text.encode("utf-8")).hexdigest()
