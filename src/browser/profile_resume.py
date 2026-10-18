"""Upload the base resume to the Naukri profile once per calendar day.

The file is the Overleaf master, with the date in the filename. A later run
on the same day leaves the profile resume alone and goes on to search.
"""

from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path

from src.browser.browser_manager import text_has_challenge
from src.exceptions import SecurityChallengeError
from src.resume.overleaf_pdf import compile_base_pdf
from src.resume.source import base_resume_pdf, load_scoring_resume
from src.utils.logger import get_logger

logger = get_logger("profile_resume")

PROFILE_URL = "https://www.naukri.com/mnjuser/profile"
_FILE_INPUTS = ("#attachCV", "input[name='uploadCV']", "input[type='file']")
_UPDATE = (
    "button:has-text('Update resume')",
    "a:has-text('Update resume')",
    "button:has-text('Upload resume')",
    "a:has-text('Upload resume')",
    "span:has-text('Update resume')",
)
_REPLACE = (
    "button:has-text('Replace')",
    "button:has-text('Upload')",
    "button:has-text('Delete and upload')",
)


def stamp_path(config) -> Path:
    return config.database.parent / "profile_resume_date.txt"


def dated_pdf_path(config, name: str, day: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", name or "").strip("_") or "resume"
    return config.generated_dir.parent / "profile" / f"{safe}_{day}.pdf"


def already_uploaded(config, day: str) -> bool:
    path = stamp_path(config)
    return path.exists() and path.read_text(encoding="utf-8").strip() == day


def refresh_profile_resume(page, config, *, day: str | None = None) -> str:
    """Upload today's base PDF when this date has not been uploaded yet."""
    day = day or date.today().isoformat()
    if already_uploaded(config, day):
        logger.info("Naukri profile resume already uploaded for %s", day)
        return "already"
    resume = load_scoring_resume(config)
    destination = dated_pdf_path(config, resume.name, day)
    base = base_resume_pdf(config)
    if base is not None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(base, destination)
        pdf = destination
    else:
        pdf = compile_base_pdf(config, destination)
    if pdf is None:
        logger.warning("Base resume PDF was not available, so Naukri was not updated")
        return "missing"
    upload_profile_resume(page, pdf)
    stamp = stamp_path(config)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(day + "\n", encoding="utf-8")
    logger.info("Uploaded the base resume to Naukri for %s", day)
    return "uploaded"


def upload_profile_resume(page, pdf: Path) -> None:
    page.goto(PROFILE_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if text_has_challenge(page.inner_text("body"), page.url):
        raise SecurityChallengeError("A security challenge appeared on the Naukri profile. Stopping.")
    control = _resume_file_input(page)
    if control is None:
        _click_first(page, _UPDATE)
        control = _resume_file_input(page)
    if control is None:
        raise RuntimeError("Naukri did not show a resume file field")
    control.set_input_files(str(pdf))
    logger.info("Attached %s to the Naukri profile", pdf.name)
    _click_first(page, _REPLACE)
    page.wait_for_timeout(2000)
    if text_has_challenge(page.inner_text("body"), page.url):
        raise SecurityChallengeError("A security challenge appeared while uploading the resume. Stopping.")


def _resume_file_input(page):
    for selector in _FILE_INPUTS:
        locator = page.locator(selector)
        try:
            count = min(locator.count(), 6)
        except Exception:
            continue
        for index in range(count):
            node = locator.nth(index)
            try:
                accept = (node.get_attribute("accept") or "").lower()
            except Exception:
                continue
            if accept and "pdf" not in accept and "doc" not in accept:
                continue
            return node
    return None


def _click_first(page, selectors: tuple[str, ...]) -> bool:
    for selector in selectors:
        locator = page.locator(selector)
        try:
            count = min(locator.count(), 4)
        except Exception:
            continue
        for index in range(count):
            button = locator.nth(index)
            try:
                if button.is_visible():
                    button.click()
                    return True
            except Exception:
                continue
    return False
