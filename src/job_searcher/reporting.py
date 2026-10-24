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
    """Write a compact employer-grouped digest for easy weekly review and sharing."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    digest_path = root / f"scan-{run_id}-digest.md"
    lines = [f"# Job Discovery Digest — scan {run_id}", "", f"Matching postings: {len(rows)}", ""]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
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
            reason = str(row.get("reason") or "No explanation supplied").replace("\\n", " ")
            lines.append(f"- [{title}]({url}) — {location} — **{score}/100** — {reason}")
        lines.append("")
    digest_path.write_text("\\n".join(lines).rstrip() + "\\n", encoding="utf-8")
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
