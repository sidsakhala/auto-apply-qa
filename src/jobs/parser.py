"""Turn a raw listing or an imported JSON object into a ``JobPosting``."""

from __future__ import annotations

import re

from src.jobs.models import JobPosting
from src.utils.text import sha256_text


def job_id_from_url(url: str) -> str:
    match = re.search(r"(\d{6,})", url or "")
    if match:
        return match.group(1)
    if url:
        return "url_" + sha256_text(url)[:16]
    return ""


def posting_from_dict(raw: dict) -> JobPosting:
    url = str(raw.get("job_url") or raw.get("url") or "").strip()
    job_id = str(raw.get("job_id") or raw.get("id") or "").strip() or job_id_from_url(url)
    if not job_id:
        basis = "|".join(
            str(raw.get(key) or "")
            for key in ("job_title", "title", "company", "location", "description")
        )
        job_id = "local_" + sha256_text(basis)[:16]
    return JobPosting(
        job_id=job_id,
        title=str(raw.get("job_title") or raw.get("title") or "").strip(),
        company=str(raw.get("company") or "").strip(),
        location=str(raw.get("location") or "").strip(),
        salary_text=str(raw.get("salary") or raw.get("salary_text") or "").strip(),
        experience_text=str(raw.get("experience") or raw.get("experience_text") or "").strip(),
        url=url,
        description=str(raw.get("description") or raw.get("job_description") or "").strip(),
    )
