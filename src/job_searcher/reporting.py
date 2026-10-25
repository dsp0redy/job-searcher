"""Safe machine-readable and human-readable scan reports."""
from __future__ import annotations
import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


def _safe_csv_cell(value: object) -> object:
    """Prevent spreadsheet formula execution when CSV reports are opened interactively."""
    if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def write_reports(output_dir: str, run_id: int, rows: list[dict[str, Any]]) -> tuple[Path, Path, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / f"scan-{run_id}.json"
    csv_path = root / f"scan-{run_id}.csv"
    md_path = root / f"scan-{run_id}.md"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["identity", "source", "company", "title", "location", "url", "score", "reason", "skill_hits"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            csv_row = {**row, "skill_hits": ", ".join(row.get("skill_hits", []))}
            writer.writerow({key: _safe_csv_cell(value) for key, value in csv_row.items()})
    lines = [f"# Job Search Report — run {run_id}", "", f"Candidates: {len(rows)}", ""]
    for row in sorted(rows, key=lambda r: int(r.get("score", 0)), reverse=True):
        lines.extend([f"## {row.get('title', 'Untitled')} — {row.get('company', '')}",
                      f"- **Identity:** {row.get('identity', '')}",
                      f"- **Score:** {row.get('score', 0)}/100",
                      f"- **Location:** {row.get('location', 'Unknown')}",
                      f"- **Source:** {row.get('source', 'Unknown')}",
                      f"- **Evidence:** {row.get('reason', '')}",
                      f"- **Matched skills:** {', '.join(row.get('skill_hits', [])) or 'None'}",
                      f"- **Apply:** {row.get('url', '')}", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, csv_path, md_path



def write_digest(output_dir: str, run_id: int, rows: list[dict[str, Any]]) -> Path:
    """Write an employer-grouped digest aggregating recent scan snapshots from the last seven days."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    digest_path = root / f"scan-{run_id}-digest.md"
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    combined: dict[str, dict[str, Any]] = {}

    def row_key(row: dict[str, Any]) -> str:
        return str(
            row.get("identity")
            or row.get("url")
            or f"{row.get('company', '')}|{row.get('title', '')}|{row.get('location', '')}"
        )

    for snapshot in root.glob("scan-*.json"):
        if snapshot.name == f"scan-{run_id}.json":
            continue
        try:
            modified = datetime.fromtimestamp(snapshot.stat().st_mtime, timezone.utc)
            if modified < cutoff:
                continue
            payload = json.loads(snapshot.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOG.warning("Skipping unreadable historical report %s (%s)", snapshot.name, type(exc).__name__)
            continue
        if not isinstance(payload, list):
            continue
        for item in payload:
            if isinstance(item, dict):
                combined[row_key(item)] = item

    # The current scan wins over historical rows for the same job identity.
    for row in rows:
        combined[row_key(row)] = row

    digest_rows = list(combined.values())
    lines = [
        "# Job Discovery Digest — last seven days",
        "",
        f"Unique postings in recent scan snapshots: {len(digest_rows)}",
        "",
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in digest_rows:
        company = str(row.get("company") or "Unknown employer")
        grouped.setdefault(company, []).append(row)
    if not grouped:
        lines.append("No postings passed the configured location, freshness, experience, and relevance filters.")
    for company in sorted(grouped, key=str.casefold):
        lines.extend([f"## {company}", ""])
        for row in sorted(grouped[company], key=lambda item: int(item.get("score", 0)), reverse=True):
            title = str(row.get("title") or "Untitled role").replace("[", "\\[").replace("]", "\\]")
            url = str(row.get("url") or "")
            location = str(row.get("location") or "Unknown")
            score = int(row.get("score", 0))
            reason = str(row.get("reason") or "No explanation supplied").replace("\n", " ")
            lines.append(f"- [{title}]({url}) — {location} — **{score}/100** — {reason}")
        lines.append("")
    digest_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return digest_path

def prune_old_reports(output_dir: str, retention_days: int) -> int:
    """Remove only old scan report files, preserving unrelated files in the output directory."""
    if retention_days < 1 or retention_days > 3650:
        raise ValueError("retention_days must be between 1 and 3650")
    root = Path(output_dir)
    if not root.is_dir():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = 0
    for path in root.glob("scan-*"):
        if not path.is_file():
            continue
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if modified < cutoff:
                path.unlink()
                removed += 1
        except OSError as exc:
            LOG.warning("Could not prune old report %s (%s)", path.name, type(exc).__name__)
    return removed


def write_application_queue(
    output_dir: str, rows: list[dict[str, Any]], minimum_score: int = 70
) -> Path:
    """Write a downstream handoff containing only sufficiently strong, usable matches.

    The score is a relevance score, not an ATS pass probability. AI-failed or
    deferred candidates are excluded so a fallback local score is not mistaken
    for a completed AI evaluation.
    """
    if not 0 <= minimum_score <= 100:
        raise ValueError("minimum_score must be between 0 and 100")
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    eligible = []
    for row in rows:
        score = row.get("score", 0)
        status = row.get("ai_status", "disabled")
        if not isinstance(score, int) or isinstance(score, bool):
            continue
        if score < minimum_score or status not in {"matched", "disabled"}:
            continue
        eligible.append({
            "identity": row.get("identity", ""),
            "company": row.get("company", ""),
            "title": row.get("title", ""),
            "location": row.get("location", "Unknown"),
            "url": row.get("url", ""),
            "score": score,
            "score_basis": "ai_match" if status == "matched" else "local_heuristic",
            "ai_status": status,
            "reason": row.get("reason", ""),
            "skill_hits": row.get("skill_hits", []),
            "missing_skills": row.get("missing_skills", []),
        })
    eligible.sort(key=lambda item: (-item["score"], str(item["company"]).casefold(), str(item["title"]).casefold()))
    queue_path = root / "application-queue.json"
    payload = {
        "schema_version": 1,
        "minimum_score": minimum_score,
        "score_note": "Relevance score out of 100; not an ATS score or probability of an interview.",
        "requires_human_review": True,
        "auto_submit": False,
        "count": len(eligible),
        "jobs": eligible,
    }
    queue_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    return queue_path
