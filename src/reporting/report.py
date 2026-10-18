"""Hourly run reports as JSON and HTML."""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from src.utils.config import AppConfig


def _top_lines(summary) -> list[str]:
    lines = []
    for index, job in enumerate(summary.top_jobs, start=1):
        score = job.get("score")
        score_text = f"{score:g}%" if isinstance(score, (int, float)) else "n/a"
        url = (job.get("url") or "").strip()
        line = (
            f"{index}. {job.get('title')} @ {job.get('company') or 'Company n/a'} — "
            f"{job.get('location') or 'Location n/a'} — "
            f"{job.get('salary') or 'Not Disclosed'} — {score_text}"
        )
        if url:
            line = f"{line} — {url}"
        lines.append(line)
    return lines


def write_openings_list(summary, config: AppConfig) -> Path | None:
    """Plain-text list of qualified openings with URLs for list-only runs."""
    if not summary.top_jobs:
        return None
    now = datetime.now()
    folder = config.reports / now.date().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%H%M%S")
    path = folder / f"openings_{stamp}.txt"
    blocks: list[str] = []
    for index, job in enumerate(summary.top_jobs, start=1):
        url = (job.get("url") or "").strip()
        score = job.get("score")
        score_text = f"{score:g}" if isinstance(score, (int, float)) else "n/a"
        resume = (job.get("resume") or "").strip()
        blocks.append(
            f"{index}. {job.get('title')} @ {job.get('company')}\n"
            f"   Location: {job.get('location') or 'n/a'}\n"
            f"   Salary: {job.get('salary') or 'Not Disclosed'}\n"
            f"   Match: {score_text}\n"
            f"   URL: {url or 'n/a'}\n"
            f"   Resume: {resume or 'n/a'}\n"
        )
    path.write_text("\n".join(blocks), encoding="utf-8")
    latest = folder / "openings_latest.txt"
    latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def write_run_report(summary, config: AppConfig, *, list_only: bool = False) -> None:
    now = datetime.now()
    folder = config.reports / now.date().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    payload = summary.to_dict()
    payload["top_job_lines"] = _top_lines(summary)
    encoded = json.dumps(payload, indent=2, ensure_ascii=False)
    document = _html(payload)
    for name, body in (("hourly_report.json", encoded), ("hourly_report.html", document)):
        (folder / name).write_text(body, encoding="utf-8")
    stamp = now.strftime("%H%M%S")
    (folder / f"hourly_report_{stamp}.json").write_text(encoded, encoding="utf-8")
    (folder / f"hourly_report_{stamp}.html").write_text(document, encoding="utf-8")
    if list_only:
        write_openings_list(summary, config)


def _html(payload: dict) -> str:
    rows = "".join(
        "<li>"
        + html.escape(line)
        + "</li>"
        for line in payload.get("top_job_lines") or ["No qualified jobs in this run."]
    )
    def cell(key: str) -> str:
        return html.escape(str(payload.get(key, 0)))

    reason = html.escape(payload.get("stopped_reason") or "completed")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Hourly job report</title>
  <style>
    body {{ font-family: Calibri, sans-serif; margin: 2rem; color: #1c1c1c; }}
    h1 {{ font-size: 1.4rem; }}
    table {{ border-collapse: collapse; }}
    td {{ padding: 0.35rem 1rem 0.35rem 0; }}
  </style>
</head>
<body>
  <h1>Hourly Naukri run</h1>
  <p>Started {html.escape(str(payload.get("started_at", "")))}. Status: {reason}.</p>
  <table>
    <tr><td>Jobs found</td><td>{cell("jobs_found")}</td></tr>
    <tr><td>Already processed</td><td>{cell("already_processed")}</td></tr>
    <tr><td>Qualified</td><td>{cell("qualified")}</td></tr>
    <tr><td>Resumes generated</td><td>{cell("resumes_generated")}</td></tr>
    <tr><td>Applications</td><td>{cell("applications")}</td></tr>
    <tr><td>Successful</td><td>{cell("successful")}</td></tr>
    <tr><td>Failed</td><td>{cell("failed")}</td></tr>
    <tr><td>Skipped</td><td>{cell("skipped")}</td></tr>
    <tr><td>Rejected</td><td>{cell("rejected")}</td></tr>
  </table>
  <h2>Top jobs</h2>
  <ol>{rows}</ol>
</body>
</html>
"""
