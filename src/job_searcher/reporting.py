"""Safe machine-readable and human-readable scan reports."""
from __future__ import annotations
import csv
import json
from pathlib import Path
from typing import Any


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
