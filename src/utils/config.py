"""Load YAML configuration, the candidate profile, and application answers."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.exceptions import ConfigurationError

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class RateLimits:
    max_applications_per_run: int = 0
    max_applications_per_day: int = 0
    min_delay_seconds: float = 10
    max_delay_seconds: float = 30


# Values Naukri accepts on the Freshness filter.
FRESHNESS_DAYS = (1, 3, 7, 15, 30)


@dataclass
class SearchSettings:
    max_search_queries: int = 45
    max_pages: int = 1
    max_jobs_per_query: int = 15
    min_delay_seconds: float = 4
    max_delay_seconds: float = 8
    max_new_jobs_per_run: int = 40
    freshness_days: int = 1
    profile_jobs_enabled: bool = True
    max_profile_jobs: int = 30


@dataclass
class BrowserSettings:
    headless: bool = False
    slow_mo_ms: int = 50
    user_data_dir: str = "data/browser_profile"
    navigation_timeout_ms: int = 45000


@dataclass
class AppConfig:
    root: Path
    application_mode: str
    apply_jobs: bool
    minimum_match_score: float
    weights: dict[str, float]
    rate_limits: RateLimits
    search: SearchSettings
    browser: BrowserSettings
    schedule_hours: float
    master_resume: Path
    base_resume: Path | None
    generated_dir: Path
    database: Path
    reports: Path
    logs: Path
    overleaf_project_url: str = ""
    overleaf_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "resume" / "overleaf")
    profile: dict = field(default_factory=dict)
    answers: dict = field(default_factory=dict)

    def ensure_dirs(self) -> None:
        for path in (
            self.generated_dir,
            self.database.parent,
            self.reports,
            self.logs,
            self.root / self.browser.user_data_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigurationError(f"Missing configuration file: {path}")
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigurationError(f"{path} must contain a mapping")
    return data


def _weights(raw: dict) -> dict[str, float]:
    expected = {
        "role_relevance": 25,
        "skills_match": 25,
        "experience_match": 15,
        "salary": 15,
        "location": 10,
        "cloud_ai": 5,
        "other": 5,
    }
    weights = {key: float(raw.get(key, default)) for key, default in expected.items()}
    total = sum(weights.values())
    if abs(total - 100) > 0.01:
        raise ConfigurationError(f"Scoring weights must sum to 100, got {total}")
    return weights


def load_config(root: Path | None = None) -> AppConfig:
    root = (root or PROJECT_ROOT).resolve()
    load_dotenv(root / ".env")
    raw = _read_yaml(root / "config" / "config.yaml")
    profile = _read_yaml(root / "config" / "candidate_profile.yaml")
    answers = _read_yaml(root / "config" / "application_answers.yaml")

    paths = raw.get("paths") or {}
    limits = raw.get("rate_limits") or {}
    search = raw.get("search") or {}
    freshness_days = int(search.get("freshness_days", 1))
    if freshness_days not in FRESHNESS_DAYS:
        raise ConfigurationError(
            f"search.freshness_days must be one of {', '.join(str(day) for day in FRESHNESS_DAYS)}"
        )
    browser = raw.get("browser") or {}
    schedule = raw.get("schedule") or {}

    master = Path(os.getenv("MASTER_RESUME") or paths.get("master_resume") or "resume/master_resume.docx")
    base_raw = os.getenv("BASE_RESUME") or paths.get("base_resume") or ""
    database = Path(os.getenv("JOBS_DB") or paths.get("database") or "data/jobs.db")
    if not master.is_absolute():
        master = root / master
    base_resume: Path | None = None
    if str(base_raw).strip():
        base_resume = Path(base_raw)
        if not base_resume.is_absolute():
            base_resume = root / base_resume
    if not database.is_absolute():
        database = root / database

    mode = str(raw.get("application_mode", "approval")).strip().lower()
    if mode not in {"approval", "automatic"}:
        raise ConfigurationError("application_mode must be 'approval' or 'automatic'")

    generated = root / str(paths.get("generated_dir") or "resume/generated")
    reports = root / str(paths.get("reports") or "reports")
    logs = root / str(paths.get("logs") or "logs")
    overleaf_dir = root / str(paths.get("overleaf_dir") or "resume/overleaf")

    return AppConfig(
        root=root,
        application_mode=mode,
        apply_jobs=bool(raw.get("apply_jobs", False)),
        minimum_match_score=float(raw.get("minimum_match_score", 70)),
        weights=_weights(raw.get("scoring") or {}),
        rate_limits=RateLimits(
            max_applications_per_run=int(limits.get("max_applications_per_run", 0)),
            max_applications_per_day=int(limits.get("max_applications_per_day", 0)),
            min_delay_seconds=float(limits.get("min_delay_seconds", 10)),
            max_delay_seconds=float(limits.get("max_delay_seconds", 30)),
        ),
        search=SearchSettings(
            max_search_queries=int(search.get("max_search_queries", 45)),
            max_pages=int(search.get("max_pages", 1)),
            max_jobs_per_query=int(search.get("max_jobs_per_query", 15)),
            min_delay_seconds=float(search.get("min_delay_seconds", 4)),
            max_delay_seconds=float(search.get("max_delay_seconds", 8)),
            max_new_jobs_per_run=int(search.get("max_new_jobs_per_run", 40)),
            freshness_days=freshness_days,
            profile_jobs_enabled=bool(search.get("profile_jobs_enabled", True)),
            max_profile_jobs=int(search.get("max_profile_jobs", 30)),
        ),
        browser=BrowserSettings(
            headless=bool(browser.get("headless", False)),
            slow_mo_ms=int(browser.get("slow_mo_ms", 50)),
            user_data_dir=str(browser.get("user_data_dir", "data/browser_profile")),
            navigation_timeout_ms=int(browser.get("navigation_timeout_ms", 45000)),
        ),
        schedule_hours=float(schedule.get("interval_hours", 1)),
        master_resume=master,
        base_resume=base_resume,
        generated_dir=generated,
        database=database,
        reports=reports,
        logs=logs,
        overleaf_project_url=str(paths.get("overleaf_project") or "").strip(),
        overleaf_dir=overleaf_dir,
        profile=profile,
        answers=answers,
    )
