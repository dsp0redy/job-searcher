from __future__ import annotations

import csv
import json

from job_searcher.reporting import _safe_csv_cell, write_reports


def test_safe_csv_cell_escapes_formula_prefixes_and_preserves_safe_values():
    for prefix in ("=", "+", "-", "@"):
        assert _safe_csv_cell(prefix + "1+1") == "'" + prefix + "1+1"
    assert _safe_csv_cell("  =1+1") == "'  =1+1"
    assert _safe_csv_cell("ordinary text") == "ordinary text"
    assert _safe_csv_cell(42) == 42
    assert _safe_csv_cell(None) is None


def test_write_reports_generates_json_csv_and_markdown(tmp_path):
    rows = [{
        "source": "greenhouse", "company": "Acme", "title": "C++ Engineer",
        "location": "Bengaluru", "url": "https://example.com/job/1", "score": 88,
        "reason": "C++ and Linux", "skill_hits": ["C++", "Linux"], "ignored": "not in csv",
    }, {
        "source": "lever", "company": "Beta", "title": "Engineer", "location": "India",
        "url": "https://example.com/job/2", "score": 40, "reason": "",
        "skill_hits": [],
    }]
    json_path, csv_path, md_path = write_reports(str(tmp_path / "reports"), 7, rows)
    assert json.loads(json_path.read_text(encoding="utf-8")) == rows
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    assert len(csv_rows) == 2
    assert csv_rows[0]["skill_hits"] == "C++, Linux"
    assert "ignored" not in csv_rows[0]
    markdown = md_path.read_text(encoding="utf-8")
    assert "Candidates: 2" in markdown
    assert "C++ Engineer — Acme" in markdown
    assert markdown.index("C++ Engineer") < markdown.index("Engineer — Beta")


def test_reports_escape_spreadsheet_formulas(tmp_path):
    rows = [{
        "source": "greenhouse", "company": "=HYPERLINK(\"https://evil.example\")",
        "title": "+cmd", "location": "-1", "url": "https://example.com",
        "score": 50, "reason": "@formula", "skill_hits": ["=DANGER"],
    }]
    _, csv_path, _ = write_reports(str(tmp_path), 1, rows)
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["company"].startswith("'=")
    assert row["title"] == "'+cmd"
    assert row["location"] == "'-1"
    assert row["reason"] == "'@formula"
    assert row["skill_hits"] == "'=DANGER"


def test_empty_report_is_valid(tmp_path):
    json_path, csv_path, md_path = write_reports(str(tmp_path), 2, [])
    assert json.loads(json_path.read_text(encoding="utf-8")) == []
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        assert list(csv.reader(stream)) == [["source", "company", "title", "location", "url", "score", "reason", "skill_hits"]]
    assert "Candidates: 0" in md_path.read_text(encoding="utf-8")
