"""Decide how to answer an application, then optionally submit it.

Unknown questions, missing resume uploads, external sites, and security
challenges never result in a guessed answer or a submit click.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from src.browser.browser_manager import needs_login, text_has_challenge
from src.exceptions import SecurityChallengeError
from src.utils.answers import answer_for, interest_reply, is_experience_question, is_known_question
from src.utils.logger import get_logger
from src.utils.text import unique_keep

logger = get_logger("apply")

# The job header renders this after the page's first HTML arrives.
# A second hidden #apply-button is also in the DOM; only a visible action is clicked.
# The label is not always "Apply": it may be Apply on company site, Easy Apply, or something else.
APPLY_BUTTON_SELECTOR = (
    "#apply-button, button.apply-button, button[class*='apply-button'], "
    "button:has-text('Apply'), a:has-text('Apply'), "
    "button:has-text('Interest'), a:has-text('Interest')"
)
INTERESTED_BUTTON_SELECTOR = (
    "button:has-text('I am interested'), a:has-text('I am interested'), "
    "button:has-text(\"I'm interested\"), a:has-text(\"I'm interested\"), "
    "button:has-text('Show interest'), a:has-text('Show interest')"
)
_INTEREST_SUCCESS = (
    "interest shared",
    "shown interest",
    "interest has been",
    "recruiter will",
    "we will contact",
    "thank you for your response",
    "thank you for your responses",
    "successfully applied",
    "application submitted",
)

IGNORE_FRAGMENTS = (
    "upload resume",
    "upload cv",
    "search jobs",
    "password",
    "email",
    "phone",
    "mobile",
    "full name",
)
SCREENING_HINTS = (
    "ctc",
    "salary",
    "notice",
    "relocat",
    "experience",
    "current location",
    "willing",
    "expected",
    "authorization",
)


@dataclass
class ApplicationForm:
    questions: list[str] = field(default_factory=list)
    has_resume_upload: bool = False
    has_captcha: bool = False
    requires_login: bool = False
    is_external: bool = False
    submit_available: bool = False


@dataclass
class ApplyPlan:
    action: str
    reason: str
    unknown_questions: list[str] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)
    upload: bool = False


@dataclass
class ApplyResult:
    status: str
    detail: str
    unknown_questions: list[str] = field(default_factory=list)


def apply_button_priority(label: str) -> int | None:
    """Rank a job-page action. Plain Apply wins when several actions are shown."""
    text = " ".join((label or "").lower().split())
    if not text or "already applied" in text or text in {"login", "sign in"}:
        return None
    if text in {"apply", "apply now"}:
        return 0
    if "company site" in text:
        return 3
    if "interest" in text:
        return 1
    return 2


def interest_choice(reply: str, options: list[str]) -> str | None:
    """Pick the button that matches the prepared answer. A Yes reply picks Yes."""
    wanted = " ".join((reply or "").lower().split())
    cleaned = [" ".join(option.split()) for option in options if option and option.strip()]
    if not wanted or not cleaned:
        return None
    for option in cleaned:
        lowered = option.lower()
        if lowered == wanted or wanted.startswith(lowered) or lowered.startswith(wanted):
            return option
    if wanted.startswith("yes"):
        for option in cleaned:
            if option.lower().startswith("yes"):
                return option
    return None


def is_screening_question(label: str) -> bool:
    lowered = " ".join(label.lower().split())
    if len(lowered) < 4:
        return False
    if any(fragment in lowered for fragment in IGNORE_FRAGMENTS):
        return False
    if "?" in lowered:
        return True
    return any(hint in lowered for hint in SCREENING_HINTS)


def on_naukri(url: str) -> bool:
    host = urllib.parse.urlparse(url or "").netloc.lower()
    return host.endswith("naukri.com")


def should_use_naukri_chat_apply(actions, opened: ApplicationForm) -> bool:
    """True when Apply opened the recruiter chat instead of a file-upload form."""
    if opened.is_external or not on_naukri(actions.url()):
        return False
    files = actions.page.locator("input[type='file']")
    try:
        for index in range(min(files.count(), 4)):
            if files.nth(index).is_visible():
                return False
    except Exception:
        pass
    for selector in ("[class*='chatbot']", "[class*='Drawer']", "[class*='drawer']"):
        box = actions.page.locator(selector)
        try:
            if box.count() and box.first.is_visible():
                return True
        except Exception:
            continue
    body = actions.body_text().lower()
    if any(token in body for token in ("kindly answer", "recruiter's questions", "thank you for showing interest")):
        return True
    return bool(opened.questions)


def extract_form(html: str, url: str) -> ApplicationForm:
    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text(" ", strip=True)
    questions: list[str] = []
    for node in soup.select("label, .question, [data-question]"):
        value = node.get_text(" ", strip=True)
        if is_screening_question(value):
            questions.append(value)
    return ApplicationForm(
        questions=unique_keep(questions),
        has_resume_upload=soup.select_one('input[type="file"]') is not None,
        has_captcha=text_has_challenge(text, url),
        requires_login=needs_login(text, url),
        is_external=bool(url) and url.startswith("http") and not on_naukri(url),
        submit_available=soup.select_one("button, input[type=submit]") is not None,
    )


def build_apply_plan(
    form: ApplicationForm,
    answers: dict,
    *,
    mode: str,
    approved: bool,
    resume_ready: bool,
) -> ApplyPlan:
    if form.has_captcha:
        return ApplyPlan("stop", "captcha")
    if form.requires_login:
        return ApplyPlan("stop", "login_required")
    if form.is_external:
        if not resume_ready:
            return ApplyPlan("stop", "resume_upload_not_found")
        filled = {
            question: value
            for question in form.questions
            if (value := answer_for(question, answers))
        }
        return ApplyPlan("company", "company_site", answers=filled, upload=True)
    if not resume_ready or not form.has_resume_upload:
        return ApplyPlan("stop", "resume_upload_not_found")

    filled: dict[str, str] = {}
    unknown: list[str] = []
    for question in form.questions:
        if is_known_question(question):
            value = answer_for(question, answers)
            if value:
                filled[question] = value
                continue
        unknown.append(question)
    if unknown:
        return ApplyPlan("stop", "unknown_question", unknown_questions=unknown, answers=filled)
    if mode == "approval" and not approved:
        return ApplyPlan("pending", "approval_required", answers=filled)
    return ApplyPlan("submit", "", answers=filled, upload=True)


class PlaywrightActions:
    """Clicks used only after ``build_apply_plan`` returns ``submit``."""

    def __init__(self, page) -> None:
        self.page = page
        self.submitted = False
        self._chat_resume_uploaded = False

    def click_apply(self) -> str:
        clicked = self._click_best_apply(12000)
        if clicked:
            self._wait_for_apply_surface()
            if "interest" in clicked.lower():
                return "interested"
            return "apply"
        if self._click_visible(INTERESTED_BUTTON_SELECTOR, 4000):
            self._wait_for_apply_surface()
            return "interested"
        raise RuntimeError("Apply button was not found")

    def _click_best_apply(self, timeout: int) -> str:
        try:
            self.page.wait_for_selector(APPLY_BUTTON_SELECTOR, state="visible", timeout=timeout)
        except Exception:
            return ""
        buttons = self.page.locator(APPLY_BUTTON_SELECTOR)
        chosen = None
        chosen_rank = None
        chosen_label = ""
        try:
            count = buttons.count()
        except Exception:
            return ""
        for index in range(count):
            button = buttons.nth(index)
            try:
                if not button.is_visible():
                    continue
                label = " ".join((button.inner_text() or "").split())
            except Exception:
                continue
            rank = apply_button_priority(label)
            if rank is None:
                continue
            if chosen_rank is None or rank < chosen_rank:
                chosen = button
                chosen_rank = rank
                chosen_label = label
        if chosen is None:
            return ""
        chosen.click()
        return chosen_label

    def _click_visible(self, selector: str, timeout: int) -> bool:
        try:
            self.page.wait_for_selector(selector, state="visible", timeout=timeout)
        except Exception:
            return False
        buttons = self.page.locator(selector)
        for index in range(buttons.count()):
            button = buttons.nth(index)
            try:
                if not button.is_visible():
                    continue
            except Exception:
                continue
            button.click()
            return True
        return False

    def answer_interest(self, answers: dict, resume_path: str = "") -> ApplyResult:
        """Answer the questions that follow I am interested. A CAPTCHA still stops the run."""
        self._chat_resume_uploaded = False
        for _ in range(24):
            if text_has_challenge(self.body_text(), self.url()):
                raise SecurityChallengeError("A security challenge appeared after I am interested. Stopping.")
            body = self.body_text().lower()
            if any(token in body for token in _INTEREST_SUCCESS):
                self._click_save()
                return ApplyResult("successful", "interest_shared")
            question = self._interest_question()
            if self._should_offer_resume_upload(question):
                self._try_upload_resume_once(resume_path)
            reply = interest_reply(question, answers) if question else "Yes"
            if question and not reply:
                return ApplyResult("needs_review", "interest_question_unanswered")
            reply = reply or "Yes"
            if self._has_yes_no_choice_ui() and self._click_matching_choice(reply):
                self._click_save()
                self._wait_for_chat_step(question)
                continue
            if self._type_chat_answer(reply):
                self._wait_for_chat_step(question)
                continue
            if self._click_save():
                self._wait_for_chat_step(question)
                body = self.body_text().lower()
                if any(token in body for token in _INTEREST_SUCCESS):
                    return ApplyResult("successful", "interest_shared")
                continue
            if self._finish_interest_if_done():
                return ApplyResult("successful", "interest_shared")
            self._pause()
        self._click_save()
        self._pause()
        confirmation = self.body_text().lower()
        if any(token in confirmation for token in _INTEREST_SUCCESS):
            return ApplyResult("successful", "interest_shared")
        return ApplyResult("needs_review", "interest_questions_unanswered")

    def _chat_root(self):
        for selector in ("[class*='chatbot']", "[class*='Drawer']", "[class*='drawer']"):
            box = self.page.locator(selector)
            try:
                if box.count() and box.first.is_visible():
                    return box.first
            except Exception:
                continue
        return self.page.locator("body")

    def _interest_question(self) -> str:
        try:
            text = self._chat_root().inner_text()
        except Exception:
            text = self.body_text()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in reversed(lines):
            if "?" in line or is_screening_question(line):
                return line[:300]
        return ""

    def _has_yes_no_choice_ui(self) -> bool:
        root = self._chat_root()
        try:
            yes = root.locator("label:has-text('Yes'), [role='radio']:has-text('Yes')").first
            no = root.locator("label:has-text('No'), [role='radio']:has-text('No')").first
            return yes.is_visible() and no.is_visible()
        except Exception:
            return False

    def _choice_labels(self) -> list[str]:
        labels: list[str] = []
        root = self._chat_root()
        for selector in ("label", "button", "[role='button']", "[role='radio']"):
            try:
                count = min(root.locator(selector).count(), 16)
            except Exception:
                continue
            for index in range(count):
                node = root.locator(selector).nth(index)
                try:
                    if not node.is_visible():
                        continue
                    label = " ".join((node.inner_text() or "").split())
                except Exception:
                    continue
                lowered = label.lower()
                if not label or "apply" in lowered or "interest" in lowered or lowered in {
                    "save",
                    "login",
                    "send",
                }:
                    continue
                if label not in labels:
                    labels.append(label)
        return labels

    def _click_matching_choice(self, reply: str) -> bool:
        chosen = interest_choice(reply, self._choice_labels())
        if not chosen:
            return False
        root = self._chat_root()
        for selector in (
            f"label:has-text('{chosen}')",
            f"[role='radio']:has-text('{chosen}')",
        ):
            options = root.locator(selector)
            try:
                if options.count() and options.first.is_visible():
                    options.first.click()
                    return True
            except Exception:
                continue
        buttons = root.locator("button, [role='button']")
        try:
            count = min(buttons.count(), 12)
        except Exception:
            return False
        for index in range(count):
            button = buttons.nth(index)
            try:
                label = " ".join((button.inner_text() or "").split())
                if label == chosen and button.is_visible():
                    button.click()
                    return True
            except Exception:
                continue
        return False

    def _type_chat_answer(self, reply: str) -> bool:
        root = self._chat_root()
        fields = root.locator("textarea, input[type='text'], div[contenteditable='true']")
        try:
            count = min(fields.count(), 6)
        except Exception:
            return False
        for index in range(count):
            field = fields.nth(index)
            try:
                if not field.is_visible():
                    continue
                field.fill(reply)
                field.press("Enter")
                return True
            except Exception:
                continue
        return False

    def _wait_for_chat_step(self, previous_question: str) -> None:
        """Wait until the chat shows the next question or a success message."""
        for _ in range(20):
            body = self.body_text().lower()
            if any(token in body for token in _INTEREST_SUCCESS):
                return
            current = self._interest_question()
            if previous_question and current and current != previous_question:
                return
            if previous_question and not current:
                return
            self._pause()

    def _click_save(self) -> bool:
        return self._click_visible("button:has-text('Save')", 800)

    def _finish_interest_if_done(self) -> bool:
        """Click Save when the chat shows a closing message or no further question."""
        body = self.body_text().lower()
        if any(token in body for token in _INTEREST_SUCCESS):
            self._click_save()
            self._pause()
            return True
        if not self._interest_question() and self._click_save():
            self._pause()
            body = self.body_text().lower()
            return any(token in body for token in _INTEREST_SUCCESS)
        return False

    def _should_offer_resume_upload(self, question: str) -> bool:
        """Upload only when the chat asks for a resume, not on experience questions."""
        text = " ".join((question or "").lower().split())
        if not text:
            return False
        if is_experience_question(question) and not any(
            token in text for token in ("resume", "upload", "attach", " cv", "curriculum")
        ):
            return False
        return any(token in text for token in ("upload", "attach", "resume", " cv", "curriculum vitae"))

    def _try_upload_resume_once(self, resume_path: str) -> None:
        if not resume_path or self._chat_resume_uploaded:
            return
        files = self.page.locator("input[type='file']")
        try:
            count = min(files.count(), 4)
        except Exception:
            return
        for index in range(count):
            control = files.nth(index)
            try:
                if not control.is_visible():
                    continue
                accept = (control.get_attribute("accept") or "").lower()
                if accept and "pdf" not in accept and "doc" not in accept:
                    continue
                control.set_input_files(resume_path)
                self._chat_resume_uploaded = True
                logger.info("Uploaded the generated resume in the apply chat")
                return
            except Exception:
                continue

    def _pause(self) -> None:
        try:
            self.page.wait_for_timeout(600)
        except Exception:
            return

    def fill_external(self, answers: dict, resume_path: str):
        from src.browser.company_form import fill_company_site

        return fill_company_site(self.page, answers, resume_path)

    def _wait_for_apply_surface(self) -> None:
        """Give the apply drawer a moment to replace the job header."""
        try:
            self.page.wait_for_function(
                """() => {
                  const root = document.body;
                  if (!root) return false;
                  if (root.querySelector("input[type='file'], [class*='chatbot'], [class*='Drawer'], [class*='drawer']")) {
                    return true;
                  }
                  return /submit application|successfully applied|already applied/i.test(root.innerText || '');
                }""",
                timeout=8000,
            )
        except Exception:
            return

    def fill(self, label: str, value: str) -> None:
        locator = self.page.get_by_label(label, exact=False)
        if locator.count():
            locator.first.fill(value)

    def upload(self, path: str) -> None:
        self.page.locator("input[type='file']").first.set_input_files(path)

    def submit(self) -> None:
        for selector in (
            "button:has-text('Submit')",
            "button:has-text('Submit application')",
            "input[type='submit']",
        ):
            locator = self.page.locator(selector)
            if locator.count():
                locator.first.click()
                self.submitted = True
                return
        raise RuntimeError("Submit control was not found. The application was not submitted.")

    def body_text(self) -> str:
        return self.page.inner_text("body")

    def url(self) -> str:
        return self.page.url

    def html(self) -> str:
        return self.page.content()


def _result_from_plan(plan: ApplyPlan) -> ApplyResult:
    if plan.action == "pending":
        return ApplyResult("pending_approval", plan.reason, plan.unknown_questions)
    status = {
        "captcha": "captcha_blocked",
        "login_required": "login_required",
        "external_apply": "external_apply",
        "unknown_question": "needs_answer",
        "resume_upload_not_found": "needs_review",
    }.get(plan.reason, "skipped")
    return ApplyResult(status, plan.reason, plan.unknown_questions)


def execute_plan(actions, plan: ApplyPlan, resume_path: str, *, allow_submit: bool) -> ApplyResult:
    """Execute a plan that was already decided. Stop plans never click submit."""
    if plan.action != "submit":
        return _result_from_plan(plan)
    if not allow_submit:
        return ApplyResult("skipped", "submit_disabled", plan.unknown_questions)
    return _fill_and_submit(actions, plan, resume_path)


def _fill_and_submit(actions, plan: ApplyPlan, resume_path: str) -> ApplyResult:
    for label, value in plan.answers.items():
        actions.fill(label, value)
    if plan.upload:
        try:
            actions.upload(resume_path)
        except Exception as exc:
            return ApplyResult("needs_review", f"resume_upload_failed: {exc}")
    if text_has_challenge(actions.body_text(), actions.url()):
        raise SecurityChallengeError("A security challenge appeared before submit. Stopping.")
    actions.submit()
    confirmation = actions.body_text().lower()
    if any(token in confirmation for token in ("successfully applied", "application submitted", "applied successfully")):
        return ApplyResult("successful", "submitted")
    return ApplyResult("failed", "submit_clicked_without_confirmation")


def run_application(
    actions,
    *,
    html: str,
    url: str,
    answers: dict,
    mode: str,
    approved: bool,
    resume_path: str,
    allow_submit: bool,
) -> ApplyResult:
    """Open Apply, re-read the form, and submit only when every answer is known."""
    initial = extract_form(html, url)
    early = build_apply_plan(
        ApplicationForm(
            questions=initial.questions,
            has_resume_upload=True,
            has_captcha=initial.has_captcha,
            requires_login=initial.requires_login,
            is_external=initial.is_external,
            submit_available=initial.submit_available,
        ),
        answers,
        mode=mode,
        approved=approved,
        resume_ready=bool(resume_path),
    )
    if early.action == "company":
        if not allow_submit:
            return ApplyResult("skipped", "submit_disabled")
        return actions.fill_external(answers, resume_path)
    if early.action != "submit":
        return _result_from_plan(early)
    if not allow_submit:
        return ApplyResult("skipped", "submit_disabled")

    try:
        clicked = actions.click_apply()
    except RuntimeError as exc:
        logger.info("Apply button was not available: %s", exc)
        return ApplyResult("needs_review", "apply_button_not_found")
    if clicked == "interested":
        return actions.answer_interest(answers, resume_path)
    if text_has_challenge(actions.body_text(), actions.url()):
        raise SecurityChallengeError("A security challenge appeared after Apply was clicked. Stopping.")
    if not on_naukri(actions.url()):
        return actions.fill_external(answers, resume_path)

    opened = extract_form(actions.html(), actions.url())
    if opened.has_captcha:
        raise SecurityChallengeError("A security challenge appeared on the application form. Stopping.")
    if should_use_naukri_chat_apply(actions, opened):
        logger.info("Apply opened the Naukri recruiter chat. Answering like I am interested.")
        return actions.answer_interest(answers, resume_path)
    plan = build_apply_plan(
        opened if opened.has_resume_upload or opened.questions else ApplicationForm(
            questions=opened.questions,
            has_resume_upload=initial.has_resume_upload,
            has_captcha=False,
            requires_login=opened.requires_login,
            is_external=False,
            submit_available=True,
        ),
        answers,
        mode="automatic",
        approved=True,
        resume_ready=bool(resume_path),
    )
    if plan.action != "submit":
        if plan.reason == "resume_upload_not_found" and should_use_naukri_chat_apply(actions, opened):
            logger.info("No upload field after Apply. Using the recruiter chat flow.")
            return actions.answer_interest(answers, resume_path)
        return _result_from_plan(plan)
    return _fill_and_submit(actions, plan, resume_path)
