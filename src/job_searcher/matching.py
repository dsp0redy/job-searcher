"""Cheap, deterministic relevance scoring before any optional AI integration."""
from __future__ import annotations

import re
from hashlib import sha256
from typing import Any

from .config import ProfileConfig
from .models import Job

_CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "bengaluru": ("bengaluru", "bangalore"),
    "bangalore": ("bengaluru", "bangalore"),
    "hyderabad": ("hyderabad",),
}


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.]+", value.casefold()))


def _contains_location(text: str, location: str) -> bool:
    """Match a configured city as a whole phrase, including common city aliases."""
    candidate = location.strip().casefold()
    if not candidate:
        return False
    aliases = _CITY_ALIASES.get(candidate, (candidate,))
    folded = text.casefold()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", folded) for alias in aliases)


def is_allowed_location(location: str, profile: ProfileConfig) -> bool:
    """Hard gate for the configured location allowlist; generic country names never imply a city."""
    allowed = [item.strip() for item in profile.locations if item.strip()]
    if not allowed:
        return True
    # Treat city aliases as equivalent, but do not allow a country-only or remote-only
    # label to pass a city-specific allowlist.
    return any(_contains_location(location, item) for item in allowed)


def score_job(job: Job, profile: ProfileConfig) -> dict[str, Any]:
    """Return transparent local score and evidence; never invent candidate qualifications."""
    title = job.title.casefold()
    title_hits = [x for x in profile.titles if x.casefold() in title]
    location_hits = [
        x for x in profile.locations
        if x.strip() and _contains_location(job.location, x)
    ]
    corpus = _tokens(f"{job.title} {job.description}")
    skill_hits = [skill for skill in profile.skills if _tokens(skill) and _tokens(skill) <= corpus]
    location_allowed = is_allowed_location(job.location, profile)
    score = min(100, len(title_hits) * 30 + len(location_hits) * 15 + len(skill_hits) * 8)
    if not location_allowed or (not profile.titles and not profile.locations and not profile.skills):
        score = 0
    return {
        "score": score,
        "title_hits": title_hits,
        "location_hits": location_hits,
        "skill_hits": skill_hits,
        "location_allowed": location_allowed,
        "reason": (
            "Local keyword evidence only; not an interview probability."
            if location_allowed else "Excluded: job location is outside the configured location allowlist."
        ),
    }


def cache_key(job: Job, profile: ProfileConfig, provider: str = "local-v1") -> str:
    text = "|".join([
        job.identity, job.title, job.description, ",".join(profile.skills),
        ",".join(profile.locations), provider,
    ])
    return sha256(text.encode("utf-8")).hexdigest()
