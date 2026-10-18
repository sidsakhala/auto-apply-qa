"""Duplicate keys for a Naukri job."""

from __future__ import annotations

from src.jobs.models import JobPosting
from src.utils.text import normalize_key, normalize_url, sha256_text


def combo_key(company: str, title: str, location: str) -> str:
    return "|".join((normalize_key(company), normalize_key(title), normalize_key(location)))


def description_hash(description: str) -> str:
    if not description.strip():
        return ""
    return sha256_text(description)


def identity(posting: JobPosting) -> dict[str, str]:
    return {
        "job_id": posting.job_id.strip(),
        "url": normalize_url(posting.url),
        "jd_hash": description_hash(posting.description),
        "dedup_key": combo_key(posting.company, posting.title, posting.location),
    }


def same_job(left: dict[str, str], right: dict[str, str]) -> bool:
    if left.get("job_id") and left["job_id"] == right.get("job_id"):
        return True
    if left.get("url") and left["url"] == right.get("url"):
        return True
    if left.get("jd_hash") and left["jd_hash"] == right.get("jd_hash"):
        return True
    if left.get("dedup_key") and left["dedup_key"] == right.get("dedup_key") and left["dedup_key"] != "||":
        return True
    return False
