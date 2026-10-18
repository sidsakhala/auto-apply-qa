"""Fill a company career site after Naukri hands off, or when the posting itself is external.

The generated resume for that job is uploaded. Password fields are filled from
COMPANY_SITE_PASSWORD and are not stored on the job record.
"""

from __future__ import annotations

import os
import re

from src.browser.browser_manager import text_has_challenge
from src.exceptions import SecurityChallengeError
from src.utils.answers import answer_for
from src.utils.logger import get_logger

logger = get_logger("apply")

_CONTINUE = (
    "button:has-text('Save and Continue')",
    "button:has-text('Submit application')",
    "button:has-text('Submit')",
    "button:has-text('Continue')",
    "button:has-text('Next')",
    "input[type='submit']",
)
_APPLY = (
    "button:has-text('Apply on company site')",
    "a:has-text('Apply on company site')",
    "button:has-text('Apply for this job')",
    "a:has-text('Apply for this job')",
    "button:has-text('Apply now')",
    "a:has-text('Apply now')",
    "button:text-is('Apply')",
    "a:text-is('Apply')",
)


def choose_option(options: list[str], answer: str) -> str | None:
    """Pick the form option that matches the prepared answer."""
    wanted = " ".join((answer or "").lower().split())
    cleaned = [" ".join(option.split()) for option in options if option and option.strip()]
    if not wanted or not cleaned:
        return None
    for option in cleaned:
        if option.lower() == wanted:
            return option
    if "never" in wanted:
        for option in cleaned:
            if "never" in option.lower():
                return option
    for option in cleaned:
        if wanted in option.lower() or option.lower() in wanted:
            return option
    if wanted in {"yes", "no"}:
        for option in cleaned:
            if option.lower().startswith(wanted):
                return option
    return None


def fill_company_site(page, answers: dict, resume_path: str):
    """Walk a company application and fill the fields that are on screen."""
    from src.browser.application import ApplyResult

    password = os.environ.get("COMPANY_SITE_PASSWORD", "")
    for step in range(6):
        if text_has_challenge(page.inner_text("body"), page.url):
            raise SecurityChallengeError("A security challenge appeared on the company site. Stopping.")
        if step == 0:
            _click_visible(page, _APPLY)
        _upload_resume(page, resume_path)
        _fill_passwords(page, password)
        _fill_labels(page, answers, resume_path)
        _select_question_options(page, answers)
        _fill_workday_dropdowns(page, answers)
        _fill_split_dates(page, answers)
        if not _click_visible(page, _CONTINUE):
            break
        page.wait_for_timeout(1500)
    confirmation = page.inner_text("body").lower()
    if any(token in confirmation for token in ("successfully applied", "application submitted", "thank you for applying")):
        return ApplyResult("successful", "company_site_submitted")
    left = _unanswered_prompts(page)
    if left:
        logger.info("Company form still has empty prompts: %s", "; ".join(left[:8]))
        return ApplyResult("needs_review", "company_site_unanswered")
    return ApplyResult("needs_review", "company_site_filled")


def _click_visible(page, selectors: tuple[str, ...]) -> bool:
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(min(locator.count(), 8)):
            button = locator.nth(index)
            try:
                if button.is_visible():
                    button.click()
                    return True
            except Exception:
                continue
    return False


def _upload_resume(page, resume_path: str) -> None:
    if not resume_path:
        return
    files = page.locator("input[type='file']")
    for index in range(min(files.count(), 4)):
        control = files.nth(index)
        try:
            control.set_input_files(resume_path)
            logger.info("Uploaded the generated resume")
            return
        except Exception:
            continue


def _fill_passwords(page, password: str) -> None:
    if not password:
        return
    fields = page.locator("input[type='password']")
    for index in range(min(fields.count(), 3)):
        field = fields.nth(index)
        try:
            if field.is_visible():
                field.fill(password)
        except Exception:
            continue


def _fill_labels(page, answers: dict, resume_path: str) -> None:
    labels = page.locator("label")
    for index in range(min(labels.count(), 80)):
        label = labels.nth(index)
        try:
            if not label.is_visible():
                continue
            text = " ".join(label.inner_text().split())
        except Exception:
            continue
        if not text or "password" in text.lower():
            continue
        if re.search(r"\b(resume|cv)\b", text, re.IGNORECASE):
            _upload_resume(page, resume_path)
            continue
        value = answer_for(text, answers)
        if not value:
            continue
        _fill_labeled_control(page, label, text, value)


def _fill_labeled_control(page, label, text: str, value: str) -> None:
    control = label.locator("input, textarea, select")
    if not control.count():
        control = page.get_by_label(text, exact=False)
    if not control.count():
        return
    target = control.first
    try:
        if not target.is_visible():
            return
        tag = (target.evaluate("element => element.tagName") or "").lower()
        kind = (target.get_attribute("type") or "").lower()
        if kind == "file":
            return
        if tag == "select":
            options = target.locator("option").all_inner_texts()
            chosen = choose_option(options, value)
            if chosen:
                target.select_option(label=chosen)
            return
        if kind in {"checkbox", "radio"}:
            if value.lower() in {"yes", "true"}:
                target.check()
            return
        target.fill(value)
    except Exception:
        logger.info("Could not fill %s", text[:80])


def _select_question_options(page, answers: dict) -> None:
    groups = page.locator("fieldset, [role='radiogroup'], [role='group']")
    for index in range(min(groups.count(), 40)):
        group = groups.nth(index)
        try:
            if not group.is_visible():
                continue
            question = " ".join(group.inner_text().split())
        except Exception:
            continue
        if not question:
            continue
        value = answer_for(question[:500], answers)
        if not value:
            continue
        option_labels = group.locator("label")
        options = []
        for label_index in range(min(option_labels.count(), 12)):
            try:
                options.append(" ".join(option_labels.nth(label_index).inner_text().split()))
            except Exception:
                continue
        chosen = choose_option(options, value)
        if not chosen:
            continue
        try:
            group.get_by_text(chosen, exact=False).first.click()
        except Exception:
            logger.info("Could not select %s", chosen[:80])


def _fill_workday_dropdowns(page, answers: dict) -> None:
    """Open button menus that a normal label cannot type into, then pick the saved answer."""
    buttons = page.locator(
        "button[aria-haspopup='listbox'], [role='combobox'], input[aria-haspopup='listbox']"
    )
    try:
        count = min(buttons.count(), 30)
    except Exception:
        return
    for index in range(count):
        button = buttons.nth(index)
        try:
            if not button.is_visible():
                continue
            current = " ".join((button.inner_text() or "").split())
            if current and "select" not in current.lower():
                continue
            label = _dropdown_label(button)
        except Exception:
            continue
        value = answer_for(label, answers) if label else None
        if not value:
            logger.info("Company form left a dropdown unanswered: %s", (label or "unlabeled")[:80])
            continue
        if not _choose_list_option(page, button, value):
            logger.info("Company form left a dropdown unanswered: %s", label[:80])


def _fill_split_dates(page, answers: dict) -> None:
    """Fill month and year boxes for a start date such as 11/2024."""
    raw = answer_for("From", answers) or ""
    parts = [part for part in raw.replace("-", "/").split("/") if part.strip()]
    if len(parts) < 2:
        return
    month, year = parts[0].zfill(2), parts[-1]
    groups = page.locator("[data-automation-id*='date'], [data-automation-id*='Date'], fieldset")
    try:
        count = min(groups.count(), 12)
    except Exception:
        return
    for index in range(count):
        group = groups.nth(index)
        try:
            if not group.is_visible():
                continue
            label = " ".join(group.inner_text().split()).lower()
        except Exception:
            continue
        if not any(token in label for token in ("from", "start date", "start month")):
            continue
        _type_into(group, "input[aria-label*='Month' i], input[placeholder*='MM' i]", month)
        _type_into(group, "input[aria-label*='Year' i], input[placeholder*='YYYY' i]", year)


def _type_into(root, selector: str, value: str) -> None:
    field = root.locator(selector)
    try:
        if field.count() and field.first.is_visible():
            field.first.fill(value)
    except Exception:
        return


def _unanswered_prompts(page) -> list[str]:
    labels: list[str] = []
    buttons = page.locator("button[aria-haspopup='listbox'], [role='combobox']")
    try:
        count = min(buttons.count(), 20)
    except Exception:
        return labels
    for index in range(count):
        button = buttons.nth(index)
        try:
            if not button.is_visible():
                continue
            current = " ".join((button.inner_text() or "").split()).lower()
            if current and "select" not in current:
                continue
            label = _dropdown_label(button)
        except Exception:
            continue
        if label:
            labels.append(label[:80])
    return labels


def _dropdown_label(button) -> str:
    label = button.get_attribute("aria-label") or ""
    if not label:
        label = button.evaluate(
            """element => {
                const labelled = element.getAttribute('aria-labelledby') || '';
                const fromIds = labelled.split(/\\s+/).map(id => document.getElementById(id)?.innerText || '').join(' ');
                if (fromIds.trim()) return fromIds;
                const field = element.closest('[data-automation-id], div');
                return field ? field.innerText : '';
            }"""
        )
    return " ".join((label or "").split())[:200]


def _choose_list_option(page, button, value: str) -> bool:
    try:
        button.click()
        page.wait_for_timeout(300)
        options = page.locator("[role='option']")
        texts: list[str] = []
        for index in range(min(options.count(), 20)):
            option = options.nth(index)
            try:
                if option.is_visible():
                    texts.append(" ".join(option.inner_text().split()))
            except Exception:
                continue
        chosen = choose_option(texts, value)
        if not chosen:
            page.keyboard.press("Escape")
            return False
        page.get_by_role("option", name=chosen, exact=False).first.click()
        return True
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            return False
        return False
