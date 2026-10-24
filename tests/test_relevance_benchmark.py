from __future__ import annotations

import json
from pathlib import Path

from job_searcher.config import ProfileConfig
from job_searcher.matching import extract_experience_range, is_allowed_location, is_experience_compatible, score_job
from job_searcher.models import Job


def test_reviewed_relevance_fixture_meets_precision_and_recall_targets():
    fixture_path = Path(__file__).parent / "fixtures" / "relevance_regression.json"
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))
    profile = ProfileConfig(
        titles=["C++ Engineer", "Firmware Engineer", "Linux Systems Engineer"],
        locations=["Bengaluru", "Bangalore", "Hyderabad"],
        minimum_experience_years=2,
        maximum_experience_years=5,
        skills=["C++", "Linux", "gRPC", "firmware", "embedded"],
    )
    true_positive = false_positive = false_negative = 0
    for case in cases:
        job = Job(
            source="fixture",
            source_id=case["id"],
            company="Reviewed fixture",
            title=case["title"],
            location=case["location"],
            url=f"https://example.com/{case['id']}",
            description=case["description"],
        )
        local = score_job(job, profile)
        minimum, maximum = extract_experience_range(f"{job.title} {job.description}")
        predicted = (
            is_allowed_location(job.location, profile)
            and is_experience_compatible(minimum, maximum, profile)
            and int(local["score"]) >= 35
        )
        expected = case["expected_relevant"]
        if predicted and expected:
            true_positive += 1
        elif predicted and not expected:
            false_positive += 1
        elif not predicted and expected:
            false_negative += 1
    precision = true_positive / max(true_positive + false_positive, 1)
    recall = true_positive / max(true_positive + false_negative, 1)
    assert precision >= 0.95
    assert recall >= 0.95
