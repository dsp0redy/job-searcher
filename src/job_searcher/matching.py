"""Cheap, deterministic relevance scoring before any optional AI integration."""
from __future__ import annotations

import re
from typing import Any, cast

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


def _location_groups(locations: list[str]) -> list[str]:
    """Collapse configured cities that are aliases of one another (Bengaluru/Bangalore)."""
    groups: set[frozenset[str]] = set()
    unique: list[str] = []
    for item in locations:
        candidate = item.strip()
        if not candidate:
            continue
        group = frozenset(_CITY_ALIASES.get(candidate.casefold(), (candidate.casefold(),)))
        if group not in groups:
            groups.add(group)
            unique.append(candidate)
    return unique


def is_too_senior(title: str, profile: ProfileConfig) -> bool:
    """True when the title contains a configured seniority keyword as a whole word/phrase."""
    folded = title.casefold()
    return any(
        re.search(r"(?<![a-z0-9])" + re.escape(word.strip().casefold()) + r"(?![a-z0-9])", folded)
        for word in profile.exclude_title_keywords if word.strip()
    )


def is_allowed_location(location: str, profile: ProfileConfig) -> bool:
    """Hard gate for the configured location allowlist; generic country names never imply a city."""
    allowed = [item.strip() for item in profile.locations if item.strip()]
    if not allowed:
        return True
    # Treat city aliases as equivalent, but do not allow a country-only or remote-only
    # label to pass a city-specific allowlist.
    return any(_contains_location(location, item) for item in allowed)


_RANGE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\s*(?:years?|yrs?)\b", re.IGNORECASE)
_MIN_RE = re.compile(
    r"(?:(?:at least|minimum(?: of)?|over|more than)\s*)?(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b"
    r"(?:\s+of)?\s+(?:relevant\s+)?experience\b|"
    r"(?:at least|minimum(?: of)?|over|more than)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b",
    re.IGNORECASE,
)
_PLUS_RE = re.compile(r"(?<!\d)(\d{1,2})\s*\+\s*(?:years?|yrs?)\b", re.IGNORECASE)


def extract_experience_range(text: str) -> tuple[float | None, float | None]:
    """Extract the most restrictive explicit years-of-experience requirement.

    A posting can mention several figures ("8 years of experience ... ideal 2-4 years").
    All explicit requirements are collected and the one with the highest minimum wins, so
    a too-senior role is not mistaken for a junior one. Nothing is guessed when absent.
    """
    found: list[tuple[float, float | None]] = []
    range_spans: list[tuple[int, int]] = []
    for match in _RANGE_RE.finditer(text):
        range_spans.append(match.span())
        low, high = float(match.group(1)), float(match.group(2))
        if low <= high:
            found.append((low, high))

    def overlaps_range(span: tuple[int, int]) -> bool:
        return any(span[0] < end and start < span[1] for start, end in range_spans)

    for match in _MIN_RE.finditer(text):
        if not overlaps_range(match.span()):
            # The regex requires one numeric capture in either alternative.
            found.append((float(cast(str, match.group(1) or match.group(2))), None))
    for match in _PLUS_RE.finditer(text):  # "N+ years" can never sit inside an "A-B years" range
        found.append((float(match.group(1)), None))
    if not found:
        return None, None
    return max(found, key=lambda pair: pair[0])


def is_experience_compatible(
    minimum_required: float | None,
    maximum_required: float | None,
    profile: ProfileConfig,
) -> bool:
    """Reject explicit experience ranges that cannot overlap the candidate's configured range."""
    if (
        minimum_required is not None
        and profile.maximum_experience_years is not None
        and minimum_required > profile.maximum_experience_years
    ):
        return False
    if (
        maximum_required is not None
        and profile.minimum_experience_years is not None
        and maximum_required < profile.minimum_experience_years
    ):
        return False
    return True


def score_job(job: Job, profile: ProfileConfig) -> dict[str, Any]:
    """Return transparent local score and evidence; never invent candidate qualifications."""
    title = job.title.casefold()
    title_hits = [x for x in profile.titles if x.casefold() in title]
    location_hits = [
        x for x in _location_groups(profile.locations)
        if _contains_location(job.location, x)
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

