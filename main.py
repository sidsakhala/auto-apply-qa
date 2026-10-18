"""Command line entry points for the Naukri job agent."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from src.database.repository import Repository
from src.llm.factory import get_provider
from src.pipeline.runner import approve_job, generate_for_job, import_jd_file, run_cycle
from src.resume.placeholder import ensure_master_resume
from src.scheduler.scheduler import serve
from src.utils.config import load_config
from src.utils.logger import setup_logging


def _print_jobs(jobs: list[dict], limit: int = 40, *, show_url: bool = False) -> None:
    if not jobs:
        print("No jobs stored yet.")
        return
    print(f"{'Score':>6}  {'Status':<22}  {'Location':<16}  Role @ Company")
    for job in jobs[:limit]:
        score = job.get("match_score")
        score_text = f"{score:5.1f}" if isinstance(score, (int, float)) else "  n/a"
        print(
            f"{score_text:>6}  {str(job.get('application_status') or ''):<22}  "
            f"{str(job.get('location') or '')[:16]:<16}  "
            f"{job.get('job_title')} @ {job.get('company')}"
        )
        if show_url and job.get("url"):
            print(f"        {job['url']}")


def _print_openings(summary) -> None:
    openings = summary.top_jobs or []
    if not openings:
        print("\nNo new qualified openings in this run.")
        return
    print(f"\nQualified openings ({len(openings)}):")
    for index, job in enumerate(openings, start=1):
        score = job.get("score")
        score_text = f"{score:g}" if isinstance(score, (int, float)) else "n/a"
        print(
            f"{index:>3}. [{score_text}] {job.get('title')} @ {job.get('company')} "
            f"({job.get('location') or 'location n/a'})"
        )
        url = (job.get("url") or "").strip()
        if url:
            print(f"      {url}")
        resume = (job.get("resume") or "").strip()
        if resume:
            print(f"      Resume: {resume}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover Naukri jobs and tailor your master resume per JD.")
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Search and score jobs; apply only if apply_jobs is true in config (or use --apply)",
    )
    parser.add_argument("--schedule", action="store_true", help="Run now and then on the configured interval")
    parser.add_argument("--search", action="store_true", help="Search and list openings only; never apply")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Tailor resumes and submit applications for this run (overrides apply_jobs: false)",
    )
    parser.add_argument("--jobs", action="store_true", help="List stored jobs")
    parser.add_argument("--applications", action="store_true", help="List jobs that reached the application step")
    parser.add_argument("--stats", action="store_true", help="Print tracker totals")
    parser.add_argument("--generate-resume", metavar="JOB_ID", help="Write a tailored DOCX and Overleaf PDF for a stored job")
    parser.add_argument("--import-jd", metavar="FILE", help="Score a local JD JSON file and tailor a resume")
    parser.add_argument("--approve", metavar="JOB_ID", help="Submit one previously qualified job")
    parser.add_argument("--login", action="store_true", help="Open Naukri so you can log in manually")
    parser.add_argument("--dashboard", action="store_true", help="Start the Streamlit dashboard")
    return parser


def _login(config) -> None:
    from src.browser.browser_manager import BrowserManager
    from src.browser.naukri_login import credentials, ensure_naukri_login
    from src.exceptions import SecurityChallengeError

    email, password = credentials()
    print("Opening Naukri and signing in.")
    print("If a CAPTCHA or one-time code appears, complete it in the browser. The agent will not bypass it.")
    with BrowserManager(config.browser, config.root) as browser:
        try:
            ensure_naukri_login(browser.page, email=email, password=password)
            print("Signed in. The session is stored in data/browser_profile.")
        except SecurityChallengeError as exc:
            print(exc)
            input("Press Enter after the browser shows you are logged in.")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config = load_config()
    config.ensure_dirs()
    setup_logging(config.logs)
    ensure_master_resume(config.master_resume)
    llm = get_provider()

    if args.dashboard:
        app = config.root / "dashboard" / "app.py"
        return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app)], cwd=config.root)

    if args.login:
        _login(config)
        return 0

    if args.import_jd:
        job_id = import_jd_file(config, Path(args.import_jd), llm=llm)
        print(f"Imported {job_id}")
        return 0

    if args.generate_resume:
        path = generate_for_job(config, args.generate_resume, llm=llm)
        print(path)
        return 0

    if args.approve:
        status = approve_job(config, args.approve)
        print(status)
        return 0

    if args.jobs or args.applications or args.stats:
        repo = Repository(config.database)
        if args.stats:
            print(json.dumps(repo.stats(config.minimum_match_score), indent=2))
        if args.jobs:
            _print_jobs(repo.list_jobs(), show_url=True)
        if args.applications:
            rows = [
                job
                for job in repo.list_jobs()
                if job.get("application_status")
                in {
                    "successful",
                    "applied",
                    "failed",
                    "pending_approval",
                    "needs_answer",
                    "needs_review",
                    "captcha_blocked",
                    "external_apply",
                }
            ]
            _print_jobs(rows)
        return 0

    if args.schedule:
        def _scheduled() -> None:
            run_cycle(
                config,
                apply_enabled=config.apply_jobs,
                interactive=config.apply_jobs,
                llm=get_provider(),
            )

        serve(_scheduled, hours=config.schedule_hours)
        return 0

    if args.run_now or args.search or args.apply:
        apply_enabled = bool(args.apply) or (bool(args.run_now) and config.apply_jobs and not args.search)
        summary = run_cycle(
            config,
            apply_enabled=apply_enabled,
            interactive=apply_enabled,
            llm=llm,
        )
        if not apply_enabled:
            _print_openings(summary)
        print(json.dumps(summary.to_dict(), indent=2))
        if summary.stopped_reason == "captcha":
            print("Stopped because a security challenge was shown. Solve it manually and run again.")
            return 2
        return 0

    _build_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
