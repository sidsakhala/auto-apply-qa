"""One search-analyze-tailor-apply cycle."""

from __future__ import annotations

import random
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from src.database.repository import Repository
from src.exceptions import ConfigurationError, ResumeIntegrityError, SecurityChallengeError
from src.jobs.deduplicator import description_hash, identity
from src.jobs.jd_analyzer import analyze_jd
from src.jobs.matcher import evaluate_job
from src.jobs.models import JobPosting
from src.jobs.parser import posting_from_dict
from src.jobs.search import build_search_queries
from src.llm.base import LLMProvider
from src.reporting.report import write_run_report
from src.resume.generator import generate_docx
from src.resume.overleaf_pdf import generate_overleaf_pdf
from src.resume.placeholder import ensure_master_resume
from src.resume.source import base_resume_pdf, load_scoring_resume, scoring_resume_path
from src.resume.tailor import tailor_resume
from src.resume.validator import is_template_resume
from src.utils.config import AppConfig
from src.utils.logger import get_logger
from src.utils.text import safe_filename, sha256_file

logger = get_logger("pipeline")


@dataclass
class RunSummary:
    started_at: str
    finished_at: str = ""
    jobs_found: int = 0
    duplicates: int = 0
    qualified: int = 0
    resumes_generated: int = 0
    applications: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    already_processed: int = 0
    rejected: int = 0
    stopped_reason: str = ""
    top_jobs: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _resume_filename(company: str, role: str, job_id: str) -> str:
    return f"{safe_filename(company)}_{safe_filename(role)}_{safe_filename(job_id)}.docx"


def materialize_resume(
    config: AppConfig,
    repo: Repository,
    resume,
    posting: JobPosting,
    analysis,
    skill_match,
    resume_scores,
    job_score,
    llm: LLMProvider | None,
) -> tuple[str, bool]:
    master_version = sha256_file(scoring_resume_path(config))
    jd_hash = description_hash(posting.description or posting.description_or_card())
    existing = repo.find_resume_version(posting.job_id, jd_hash, master_version)
    existing_path = Path(existing["file_path"]) if existing and existing.get("file_path") else None
    if existing_path and existing_path.exists() and existing_path.suffix == ".pdf":
        return str(existing_path), False

    tailored = tailor_resume(
        resume,
        analysis,
        profile=config.profile,
        llm=llm,
        jd_text=posting.description or posting.description_or_card(),
        role_score=job_score.role_relevance,
        resume_scores=resume_scores,
        skill_match=skill_match,
    )
    destination = config.generated_dir / _resume_filename(posting.company, posting.title, posting.job_id)
    if not (existing_path and existing_path.exists()):
        generate_docx(
            tailored,
            destination,
            master_path=config.master_resume,
            generated_dir=config.generated_dir,
            job_id=posting.job_id,
        )
    else:
        destination = existing_path
    pdf_destination = destination.with_suffix(".pdf")
    jd_text = posting.description or posting.description_or_card()
    from src.utils.skills import find_skills
    from src.utils.text import unique_keep

    pdf_tailored = {
        **tailored,
        "jd_skills": unique_keep(
            [*find_skills(jd_text), *analysis.required_skills, *analysis.preferred_skills]
        ),
    }
    try:
        pdf = generate_overleaf_pdf(config, resume, pdf_tailored, pdf_destination)
    except (ConfigurationError, ResumeIntegrityError) as exc:
        if "Overleaf source was modified" in str(exc):
            raise
        logger.warning("Overleaf PDF was not created: %s", exc)
        pdf = None
    if pdf is None:
        base = base_resume_pdf(config)
        if base is not None:
            pdf_destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(base, pdf_destination)
            pdf = pdf_destination
    stored = pdf or destination
    repo.add_resume_version(
        {
            "job_id": posting.job_id,
            "company": posting.company,
            "role": posting.title,
            "created_at": _now(),
            "master_resume_version": master_version,
            "jd_hash": jd_hash,
            "resume_match_score": resume_scores.overall,
            "file_path": str(stored),
            "comparison_json": tailored["comparison"],
        }
    )
    created = not (existing_path and existing_path.exists() and existing_path == Path(stored))
    return str(stored), created


def _record_fields(posting: JobPosting, analysis, skill_match, resume_scores, job_score, ident: dict) -> dict:
    return {
        "job_id": posting.job_id,
        "job_title": posting.title,
        "company": posting.company,
        "location": posting.location,
        "salary": analysis.salary or posting.salary_text,
        "experience": analysis.experience_required or posting.experience_text,
        "job_url": posting.url,
        "description": posting.description,
        "job_description_hash": ident["jd_hash"],
        "dedup_key": ident["dedup_key"],
        "normalized_url": ident["url"],
        "match_score": job_score.total,
        "resume_match_score": resume_scores.overall,
        "score_json": job_score.to_dict(),
        "analysis_json": analysis.to_dict(),
        "skill_match_json": skill_match.to_dict(),
        "date_found": _now(),
    }


def _can_apply(config: AppConfig, repo: Repository, applications_this_run: int) -> tuple[bool, str]:
    limits = config.rate_limits
    if limits.max_applications_per_run > 0 and applications_this_run >= limits.max_applications_per_run:
        return False, "run_limit"
    today = datetime.now().date().isoformat()
    if limits.max_applications_per_day > 0 and repo.count_applied_on(today) >= limits.max_applications_per_day:
        return False, "day_limit"
    return True, ""


def _pause(config: AppConfig, sleeper) -> None:
    limits = config.rate_limits
    sleeper(random.uniform(limits.min_delay_seconds, limits.max_delay_seconds))


def _live_postings(config: AppConfig, browser, sleeper) -> tuple[list[JobPosting], str]:
    from src.browser.job_search import NaukriSearch

    queries = build_search_queries(config.profile, limit=config.search.max_search_queries)
    try:
        return (
            NaukriSearch(
                browser,
                config.search,
                profile=config.profile,
                sleeper=sleeper,
            ).collect(queries),
            "",
        )
    except SecurityChallengeError as exc:
        logger.warning("%s", exc)
        return list(getattr(exc, "found", []) or []), "captcha"


def _live_apply(browser, config: AppConfig, job: dict, resume_path: str, approved: bool):
    from src.browser.application import PlaywrightActions, run_application

    url = job.get("job_url") or ""
    browser.goto(url)
    return run_application(
        PlaywrightActions(browser.page),
        html=browser.content(),
        url=browser.page.url,
        answers=config.answers,
        mode=config.application_mode,
        approved=approved,
        resume_path=resume_path,
        allow_submit=True,
    )


def run_cycle(
    config: AppConfig,
    *,
    job_source=None,
    applier=None,
    apply_enabled: bool = False,
    interactive: bool = False,
    llm: LLMProvider | None = None,
    sleeper=time.sleep,
    prompter=None,
    write_report: bool = True,
) -> RunSummary:
    """Search, score, tailor, and optionally apply. Inject ``job_source`` in tests."""
    config.ensure_dirs()
    ensure_master_resume(config.master_resume)
    if not config.master_resume.exists():
        raise ConfigurationError(f"Master resume is missing: {config.master_resume}")

    resume = load_scoring_resume(config)
    template = is_template_resume(resume)
    if template:
        logger.warning(
            "The master resume is still the placeholder. Tailoring can run. Applications will not."
        )
    repo = Repository(config.database)
    summary = RunSummary(started_at=_now())
    before_hash = sha256_file(scoring_resume_path(config))

    def process(postings: list[JobPosting], apply_fn) -> None:
        summary.jobs_found = len(postings)
        seen: list[dict] = []
        for posting in postings:
            ident = identity(posting)
            if repo.find_duplicate(
                job_id=ident["job_id"],
                url=ident["url"],
                jd_hash=ident["jd_hash"],
                dedup_key=ident["dedup_key"],
            ) or any(_same(ident, previous) for previous in seen):
                summary.duplicates += 1
                summary.already_processed += 1
                continue
            seen.append(ident)
            _process_posting(
                config,
                repo,
                resume,
                posting,
                ident,
                summary,
                llm=llm,
                apply_fn=apply_fn,
                apply_enabled=apply_enabled and summary.stopped_reason != "captcha",
                interactive=interactive,
                template=template,
                sleeper=sleeper,
                prompter=prompter,
            )
            if job_score_row := repo.get_job(posting.job_id):
                if job_score_row.get("match_score") is not None and not str(
                    job_score_row["application_status"]
                ).startswith("rejected"):
                    summary.top_jobs.append(
                        {
                            "title": posting.title,
                            "company": posting.company,
                            "location": posting.location,
                            "salary": job_score_row.get("salary") or "Not Disclosed",
                            "score": job_score_row.get("match_score"),
                            "url": posting.url,
                            "resume": job_score_row.get("generated_resume_path") or "",
                        }
                    )

    if job_source is None or (apply_enabled and applier is None):
        from src.browser.browser_manager import BrowserManager

        with BrowserManager(config.browser, config.root) as browser:
            try:
                from src.browser.naukri_login import credentials, ensure_naukri_login

                email, password = credentials()
                ensure_naukri_login(browser.page, email=email, password=password)
            except SecurityChallengeError as exc:
                logger.warning("%s", exc)
                summary.stopped_reason = "captcha"
                summary.finished_at = _now()
                if write_report:
                    write_run_report(summary, config)
                return summary
            if job_source is None:
                try:
                    from src.browser.profile_resume import refresh_profile_resume

                    refresh_profile_resume(browser.page, config)
                except SecurityChallengeError as exc:
                    logger.warning("%s", exc)
                    summary.stopped_reason = "captcha"
                    summary.finished_at = _now()
                    if write_report:
                        write_run_report(summary, config)
                    return summary
                except Exception:
                    logger.exception("Could not upload the Naukri profile resume. Search will continue.")
                postings, stopped = _live_postings(config, browser, sleeper)
                summary.stopped_reason = stopped
            else:
                postings = list(job_source())
            apply_fn = applier
            if apply_fn is None and apply_enabled:
                apply_fn = lambda job, path, approved: _live_apply(browser, config, job, path, approved)
            process(postings, apply_fn)
            _apply_ready_queue(config, repo, summary, apply_fn, sleeper)
    else:
        process(list(job_source()), applier)
        _apply_ready_queue(config, repo, summary, applier, sleeper)

    if sha256_file(scoring_resume_path(config)) != before_hash:
        raise ResumeIntegrityError("The master resume changed during the run. This is a bug.")

    summary.top_jobs.sort(key=lambda item: item.get("score") or 0, reverse=True)
    opening_cap = 5 if apply_enabled else 500
    summary.top_jobs = summary.top_jobs[:opening_cap]
    summary.finished_at = _now()
    if write_report:
        write_run_report(summary, config, list_only=not apply_enabled)
    logger.info(
        "Run finished. found=%s qualified=%s resumes=%s applications=%s skipped=%s",
        summary.jobs_found,
        summary.qualified,
        summary.resumes_generated,
        summary.applications,
        summary.skipped,
    )
    return summary


def _same(left: dict, right: dict) -> bool:
    from src.jobs.deduplicator import same_job

    return same_job(left, right)


def _process_posting(
    config,
    repo,
    resume,
    posting: JobPosting,
    ident: dict,
    summary: RunSummary,
    *,
    llm,
    apply_fn,
    apply_enabled: bool,
    interactive: bool,
    template: bool,
    sleeper,
    prompter,
) -> None:
    analysis = analyze_jd(posting, llm)
    skill_match, resume_scores, job_score, decision = evaluate_job(
        resume,
        analysis,
        config.profile,
        weights=config.weights,
        minimum=config.minimum_match_score,
    )
    fields = _record_fields(posting, analysis, skill_match, resume_scores, job_score, ident)
    fields["application_status"] = decision.status
    fields["skip_reason"] = decision.reason
    repo.upsert_job(fields)

    if not decision.proceed_to_resume:
        summary.rejected += 1
        logger.info("Rejected %s at %s (%s)", posting.title, posting.company, decision.status)
        return

    summary.qualified += 1
    if template:
        repo.update_job(posting.job_id, application_status="skipped", skip_reason="placeholder_resume")
        summary.skipped += 1
        return

    try:
        path, created = materialize_resume(
            config, repo, resume, posting, analysis, skill_match, resume_scores, job_score, llm
        )
    except ResumeIntegrityError:
        logger.exception("Resume integrity check failed for %s", posting.job_id)
        repo.update_job(posting.job_id, application_status="skipped", skip_reason="resume_integrity")
        summary.skipped += 1
        return
    if created:
        summary.resumes_generated += 1
    version = repo.find_resume_version(posting.job_id, ident["jd_hash"], sha256_file(scoring_resume_path(config)))
    repo.update_job(
        posting.job_id,
        generated_resume_path=path,
        comparison_json=(version or {}).get("comparison_json", ""),
        resume_match_score=resume_scores.overall,
        application_status="resume_ready",
    )

    if not apply_enabled:
        return

    if "naukri.com" not in (posting.url or ""):
        repo.update_job(posting.job_id, application_status="skipped", skip_reason="no_naukri_url")
        summary.skipped += 1
        return

    approved = config.application_mode == "automatic"
    if config.application_mode == "approval":
        if not interactive:
            repo.update_job(posting.job_id, application_status="pending_approval", skip_reason="approval_required")
            return
        ask = prompter or _default_prompt
        approved = bool(ask(posting, job_score.total))
        if not approved:
            repo.update_job(posting.job_id, application_status="skipped", skip_reason="user_declined")
            summary.skipped += 1
            return

    allowed, limit_reason = _can_apply(config, repo, summary.applications)
    if not allowed:
        repo.update_job(posting.job_id, application_status="skipped", skip_reason=limit_reason)
        summary.skipped += 1
        return
    if apply_fn is None:
        repo.update_job(posting.job_id, application_status="pending_approval", skip_reason="no_applier")
        return

    _pause(config, sleeper)
    _safe_apply(apply_fn, repo.get_job(posting.job_id), path, approved, repo, summary, posting.job_id)


def _safe_apply(apply_fn, job: dict, path: str, approved: bool, repo, summary: RunSummary, job_id: str) -> None:
    """Record one attempt. A missing button or a page error does not stop the cycle."""
    try:
        result = apply_fn(job, path, approved)
    except SecurityChallengeError as exc:
        logger.warning("%s", exc)
        repo.update_job(job_id, application_status="captcha_blocked", skip_reason=str(exc))
        summary.stopped_reason = "captcha"
        return
    except Exception as exc:
        logger.exception("Apply failed for %s", job_id)
        repo.update_job(job_id, application_status="needs_review", skip_reason=str(exc)[:300])
        summary.skipped += 1
        return
    _record_application(repo, summary, job_id, result)


def _record_application(repo, summary: RunSummary, job_id: str, result) -> None:
    status = result.status
    if status in {"successful", "applied"}:
        summary.applications += 1
        summary.successful += 1 if status == "successful" else 0
        repo.update_job(
            job_id,
            application_status=status,
            date_applied=_now(),
            skip_reason=result.detail,
        )
    elif status == "failed":
        summary.applications += 1
        summary.failed += 1
        repo.update_job(job_id, application_status="failed", skip_reason=result.detail, date_applied=_now())
    else:
        summary.skipped += 1
        repo.update_job(
            job_id,
            application_status=status,
            skip_reason=result.detail,
            unknown_questions=result.unknown_questions,
        )


def _apply_ready_queue(config, repo, summary: RunSummary, apply_fn, sleeper) -> None:
    """Submit stored matches that an earlier search prepared but did not send."""
    if config.application_mode != "automatic" or apply_fn is None or summary.stopped_reason == "captcha":
        return
    if is_template_resume(load_scoring_resume(config)):
        return
    ready = [
        job
        for job in repo.list_jobs()
        if job.get("application_status") == "resume_ready"
        and "naukri.com" in (job.get("job_url") or "")
        and job.get("generated_resume_path")
        and Path(job["generated_resume_path"]).exists()
    ]
    ready.sort(key=lambda job: float(job.get("match_score") or 0), reverse=True)
    for job in ready:
        if summary.stopped_reason == "captcha":
            return
        allowed, _reason = _can_apply(config, repo, summary.applications)
        if not allowed:
            return
        _pause(config, sleeper)
        _safe_apply(apply_fn, job, job["generated_resume_path"], True, repo, summary, job["job_id"])
        if summary.stopped_reason == "captcha":
            return


def _default_prompt(posting: JobPosting, score: float) -> bool:
    import sys

    print(f"\n{posting.title} — {posting.company} — {posting.location} — match {score}%")
    print(posting.url or "(no url)")
    if not sys.stdin.isatty():
        print("Approval mode needs an interactive terminal. Leaving this job pending.")
        return False
    answer = input("Apply to this job? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def import_jd_file(config: AppConfig, path: Path, llm: LLMProvider | None = None) -> str:
    import json

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "description" not in raw and "job_description" not in raw:
        raise ConfigurationError("JD file must be a JSON object with a description")
    posting = posting_from_dict(raw)
    run_cycle(
        config,
        job_source=lambda: [posting],
        apply_enabled=False,
        llm=llm,
        write_report=False,
    )
    return posting.job_id


def generate_for_job(config: AppConfig, job_id: str, llm: LLMProvider | None = None) -> Path:
    ensure_master_resume(config.master_resume)
    repo = Repository(config.database)
    job = repo.get_job(job_id)
    if job is None:
        raise ConfigurationError(
            f"No job {job_id} is stored. Import a JD or run a search before generating a resume."
        )
    posting = posting_from_dict(
        {
            "job_id": job["job_id"],
            "job_title": job["job_title"],
            "company": job["company"],
            "location": job["location"],
            "salary": job["salary"],
            "experience": job["experience"],
            "job_url": job["job_url"],
            "description": job["description"],
        }
    )
    before = sha256_file(scoring_resume_path(config))
    resume = load_scoring_resume(config)
    analysis = analyze_jd(posting, llm)
    skill_match, resume_scores, job_score, _decision = evaluate_job(
        resume,
        analysis,
        config.profile,
        weights=config.weights,
        minimum=config.minimum_match_score,
    )
    path, created = materialize_resume(
        config, repo, resume, posting, analysis, skill_match, resume_scores, job_score, llm
    )
    version = repo.find_resume_version(
        posting.job_id, description_hash(posting.description), sha256_file(scoring_resume_path(config))
    )
    repo.update_job(
        job_id,
        generated_resume_path=path,
        resume_match_score=resume_scores.overall,
        match_score=job_score.total,
        comparison_json=(version or {}).get("comparison_json", ""),
        skill_match_json=skill_match.to_dict(),
        analysis_json=analysis.to_dict(),
        score_json=job_score.to_dict(),
    )
    if sha256_file(scoring_resume_path(config)) != before:
        raise ResumeIntegrityError("Refusing to continue because the master resume was modified")
    logger.info("%s tailored resume %s", "Generated" if created else "Reused", path)
    return Path(path)


def approve_job(config: AppConfig, job_id: str, applier=None) -> str:
    """Apply to one stored job after the user has approved it."""
    repo = Repository(config.database)
    job = repo.get_job(job_id)
    if job is None:
        raise ConfigurationError(f"No job {job_id} is stored")
    resume = load_scoring_resume(config)
    if is_template_resume(resume):
        raise ConfigurationError("Replace resume/master_resume.docx before applying. The placeholder cannot be submitted.")
    if not job.get("generated_resume_path"):
        generate_for_job(config, job_id)
        job = repo.get_job(job_id)
    if "naukri.com" not in (job.get("job_url") or ""):
        raise ConfigurationError("This job has no Naukri URL. Apply manually using the generated resume.")
    allowed, reason = _can_apply(config, repo, 0)
    if not allowed:
        raise ConfigurationError(f"Application limit reached ({reason})")

    def _apply(current, path, approved):
        if applier:
            return applier(current, path, approved)
        from src.browser.browser_manager import BrowserManager

        with BrowserManager(config.browser, config.root) as browser:
            return _live_apply(browser, config, current, path, approved)

    result = _apply(job, job["generated_resume_path"], True)
    repo.update_job(
        job_id,
        application_status=result.status,
        skip_reason=result.detail,
        unknown_questions=result.unknown_questions,
        date_applied=_now() if result.status in {"successful", "applied", "failed"} else job.get("date_applied") or "",
        attempt_count=int(job.get("attempt_count") or 0) + 1,
    )
    return result.status
