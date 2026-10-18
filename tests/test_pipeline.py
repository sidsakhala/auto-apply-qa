"""Duplicates, storage, application decisions, the scheduler, and the offline pipeline."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from src.browser.naukri_login import ensure_naukri_login
from src.browser.company_form import choose_option
from src.browser.application import (
    ApplicationForm,
    ApplyResult,
    PlaywrightActions,
    apply_button_priority,
    build_apply_plan,
    extract_form,
    interest_choice,
    run_application,
    should_use_naukri_chat_apply,
)
from src.browser.naukri import page_has_challenge, parse_profile_job_html, parse_search_html, search_url
from src.database.repository import Repository
from src.jobs.deduplicator import identity, same_job
from src.jobs.parser import posting_from_dict
from src.pipeline.runner import generate_for_job, run_cycle
from src.resume.parser import parse_resume
from src.scheduler.scheduler import JOB_ID, build_scheduler
from src.utils.answers import answer_for, interest_reply
from src.utils.text import sha256_file
from tests.support import SAMPLE_JD, make_config


SEARCH_HTML = """
<html><body>
  <div class="srp-jobtuple-wrapper">
    <a class="title" href="https://www.naukri.com/ai-engineer-pune-100000001">AI Engineer</a>
    <a class="comp-name">Example Labs</a>
    <span class="loc">Pune</span>
    <span class="sal">₹12-18 LPA</span>
    <span class="exp">1-3 Yrs</span>
  </div>
  <article class="jobTuple">
    <a class="title" href="https://www.naukri.com/ml-engineer-hyderabad-100000002">Machine Learning Engineer</a>
    <a class="comp-name">Northwind</a>
    <span class="loc">Hyderabad</span>
    <span class="sal">Not disclosed</span>
    <span class="exp">1-2 Yrs</span>
  </article>
</body></html>
"""


class _EmptyLocator:
    def count(self) -> int:
        return 0

    def nth(self, index: int):
        raise IndexError(index)


class _FakePage:
    def locator(self, selector: str) -> _EmptyLocator:
        return _EmptyLocator()


class FakeActions:
    def __init__(self, pages: list[tuple[str, str, str]]) -> None:
        self.pages = pages
        self.index = 0
        self.calls: list[str] = []
        self.page = _FakePage()

    def click_apply(self) -> str:
        self.calls.append("apply")
        self.index = min(self.index + 1, len(self.pages) - 1)
        return "apply"

    def answer_interest(self, answers: dict, resume_path: str = ""):
        self.calls.append("answer_interest")
        return ApplyResult("successful", "interest_shared")

    def fill(self, label: str, value: str) -> None:
        self.calls.append(f"fill:{label}:{value}")

    def upload(self, path: str) -> None:
        self.calls.append(f"upload:{path}")

    def submit(self) -> None:
        self.calls.append("submit")

    def body_text(self) -> str:
        return self.pages[self.index][2]

    def url(self) -> str:
        return self.pages[self.index][1]

    def html(self) -> str:
        return self.pages[self.index][0]


class _Button:
    def __init__(self, visible: bool, label: str = "Apply") -> None:
        self.visible = visible
        self.clicked = False
        self.label = label

    def is_visible(self) -> bool:
        return self.visible

    def inner_text(self) -> str:
        return self.label

    def click(self) -> None:
        self.clicked = True


class _Locator:
    def __init__(self, buttons: list[_Button]) -> None:
        self.buttons = buttons

    def count(self) -> int:
        return len(self.buttons)

    def nth(self, index: int) -> _Button:
        return self.buttons[index]


class _Page:
    def __init__(self, buttons: list[_Button], *, present: bool = True, interested: bool = False) -> None:
        self.buttons = buttons
        self.present = present
        self.interested = interested

    def wait_for_selector(self, selector: str, state: str = "visible", timeout: int = 0) -> None:
        if "interested" in selector.lower():
            if not self.interested:
                raise TimeoutError(selector)
            return
        if not self.present:
            raise TimeoutError(selector)

    def locator(self, selector: str) -> _Locator:
        return _Locator(self.buttons)

    def wait_for_function(self, script: str, timeout: int = 0) -> None:
        raise TimeoutError("no drawer in this test")


def test_click_apply_waits_and_uses_the_visible_button():
    hidden = _Button(False)
    visible = _Button(True)
    actions = PlaywrightActions(_Page([hidden, visible]))
    actions.click_apply()
    assert visible.clicked
    assert not hidden.clicked

    missing = PlaywrightActions(_Page([], present=False))
    try:
        missing.click_apply()
    except RuntimeError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("a missing Apply button should fail this click")

    interested = _Button(True)
    fallback = PlaywrightActions(_Page([interested], present=False, interested=True))
    assert fallback.click_apply() == "interested"
    assert interested.clicked

    company = _Button(True, "Apply on company site")
    plain = _Button(True, "Apply")
    preferred = PlaywrightActions(_Page([company, plain]))
    assert preferred.click_apply() == "apply"
    assert plain.clicked
    assert not company.clicked

    easy = _Button(True, "Easy Apply")
    only_easy = PlaywrightActions(_Page([easy]))
    assert only_easy.click_apply() == "apply"
    assert easy.clicked

    site_only = _Button(True, "Apply on company site")
    company_only = PlaywrightActions(_Page([site_only]))
    assert company_only.click_apply() == "apply"
    assert site_only.clicked
    assert apply_button_priority("Walk-in") == 2
    assert apply_button_priority("Already applied") is None


def test_interest_choice_picks_the_positive_answer():
    assert interest_choice("Yes", ["No", "Yes"]) == "Yes"
    assert interest_choice("Yes", ["No", "Yes, I will attend"]) == "Yes, I will attend"
    assert interest_choice("2", ["No", "Yes"]) is None
    assert interest_choice("Yes, I consent", ["No", "Yes, I consent"]) == "Yes, I consent"


def test_interest_chat_answers_like_the_recruiter_questions():
    answers = {"willing_to_relocate": "Yes", "skill_experience": "2.5 years"}
    assert interest_reply("Will you attend the walk-in?", answers) == "Yes"
    assert interest_reply("How many years of experience do you have in RAG (Retrieval-Augmented Generation)?", answers) == "2.5"
    notice = (
        "Are you currently serving Notice Period , if yes -please mention LWD , "
        "If not what is official notice period"
    )
    assert interest_reply(notice, answers) == "18 November"
    assert interest_reply("10th class passed out year and percentage", answers) == "2017 and 68%"
    assert interest_reply("Overall experience and relevant experience", answers) == "2.5 years"
    assert interest_reply("Highest educational qualification with passed out year and percentage", answers) == "2024 - MCA - 79%"
    assert interest_reply("Are you available for face to face interview on 10th Oct?", answers) == "Yes"
    assert (
        interest_reply(
            "Will you be Available for Face 2 Face Interview on 12 October Monday at Hyderabad?",
            answers,
        )
        == "Yes"
    )
    assert interest_reply("Are you currently residing in Bengaluru or willing to relocate to Bengaluru?", answers) == "Yes"


PROFILE_JOBS_HTML = """
<html><body>
  <div class="reco-card">
    <a href="/job-listings-ai-engineer-example-100000010">AI Engineer</a>
    <span class="exp">1-3 Yrs</span>
    <span class="loc">Pune</span>
  </div>
  <div class="reco-card">
    <a href="/job-listings-senior-ai-engineer-example-100000011">Senior AI Engineer</a>
    <span class="exp">8-12 Yrs</span>
  </div>
</body></html>
"""


def test_profile_job_html_parser():
    jobs = parse_profile_job_html(PROFILE_JOBS_HTML)
    assert len(jobs) == 2
    assert jobs[0].job_id == "100000010"
    assert jobs[1].title == "Senior AI Engineer"


def test_search_html_parser_and_captcha_text():
    jobs = parse_search_html(SEARCH_HTML)
    assert [job.job_id for job in jobs] == ["100000001", "100000002"]
    assert jobs[0].company == "Example Labs"
    assert jobs[0].location == "Pune"
    assert page_has_challenge("<html><body>Verify you are human</body></html>", "https://www.naukri.com/jobs")
    assert page_has_challenge(
        "<html><body>Access Denied. You don't have permission to access this server. errors.edgesuite.net</body></html>",
        "https://www.naukri.com/ai-engineer-jobs-in-pune",
    )
    assert not page_has_challenge("<html><body>AI Engineer jobs in Pune</body></html>", "https://www.naukri.com/jobs")
    assert search_url("SDET", "Pune") == "https://www.naukri.com/sdet-jobs-in-pune?jobAge=1"
    assert search_url("QA Automation Engineer", "Bangalore", 2) == (
        "https://www.naukri.com/qa-automation-engineer-jobs-in-bangalore-2?jobAge=1"
    )


def test_duplicate_keys_and_database_roundtrip(tmp_path):
    config = make_config(tmp_path)
    repo = Repository(config.database)
    first = posting_from_dict(SAMPLE_JD)
    other_url = posting_from_dict({**SAMPLE_JD, "job_id": "other", "job_url": "https://www.naukri.com/other-200000002"})
    assert same_job(identity(first), identity(other_url))
    ident = identity(first)
    repo.upsert_job(
        {
            "job_id": first.job_id,
            "job_title": first.title,
            "company": first.company,
            "location": first.location,
            "salary": first.salary_text,
            "experience": first.experience_text,
            "job_url": first.url,
            "description": first.description,
            "job_description_hash": ident["jd_hash"],
            "dedup_key": ident["dedup_key"],
            "normalized_url": ident["url"],
            "match_score": 91.0,
            "application_status": "resume_ready",
            "date_found": "2026-10-07T13:00:00",
        }
    )
    assert repo.find_duplicate(job_id="job-100")
    assert repo.find_duplicate(url=ident["url"])
    assert repo.find_duplicate(jd_hash=ident["jd_hash"])
    assert repo.find_duplicate(dedup_key=ident["dedup_key"])
    assert repo.get_job("missing") is None
    stored = repo.get_job("job-100")
    assert stored["company"] == "Example Labs"
    assert repo.stats()["jobs_found"] == 1


def test_naukri_login_uses_the_saved_session_or_submits_the_form():
    class _Box:
        def __init__(self) -> None:
            self.value = ""
            self.clicked = False

        def is_visible(self) -> bool:
            return True

        def fill(self, value: str) -> None:
            self.value = value

        def click(self) -> None:
            self.clicked = True

    class _Locator:
        def __init__(self, box: _Box | None) -> None:
            self.box = box

        def count(self) -> int:
            return 0 if self.box is None else 1

        def nth(self, index: int) -> _Box:
            assert self.box is not None
            return self.box

    class _Page:
        def __init__(self, signed_in: bool) -> None:
            self.signed_in = signed_in
            self.url = "https://www.naukri.com/mnjuser/homepage" if signed_in else "https://www.naukri.com/nlogin/login"
            self.email = _Box()
            self.password = _Box()
            self.button = _Box()

        def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
            if self.signed_in:
                self.url = "https://www.naukri.com/mnjuser/homepage"

        def wait_for_timeout(self, millis: int) -> None:
            if self.password.value:
                self.url = "https://www.naukri.com/mnjuser/homepage"
                self.signed_in = True

        def inner_text(self, selector: str) -> str:
            if self.signed_in:
                return "My Naukri Logout"
            return "Enter Email ID and password"

        def locator(self, selector: str) -> _Locator:
            if selector == "#usernameField":
                return _Locator(self.email)
            if selector == "#passwordField":
                return _Locator(self.password)
            if selector == "button:has-text('Login')":
                return _Locator(self.button)
            return _Locator(None)

    signed_in = _Page(True)
    assert ensure_naukri_login(signed_in, email="person@example.com", password="secret") == "already"
    assert signed_in.email.value == ""

    home = _Page(True)
    home.inner_text = lambda selector: "View profile"
    assert ensure_naukri_login(home, email="person@example.com", password="secret") == "already"
    assert home.email.value == ""

    fresh = _Page(False)
    assert ensure_naukri_login(fresh, email="person@example.com", password="secret") == "submitted"
    assert fresh.email.value == "person@example.com"
    assert fresh.password.value == "secret"
    assert fresh.button.clicked


def test_company_option_matches_the_prepared_answer():
    options = [
        "Associate",
        "Contractor/Temporary",
        "Intern",
        "I have never worked for/at Nationwide in any capacity",
    ]
    chosen = choose_option(options, "I have never worked for this employer")
    assert chosen.startswith("I have never")
    assert choose_option(["No", "Yes"], "Yes") == "Yes"


def test_application_answers_never_guess():
    answers = {
        "current_ctc": "6 LPA",
        "expected_ctc": "10 LPA",
        "willing_to_relocate": "Yes",
        "skill_experience": "2 years",
        "preferred_locations": ["Pune", "Hyderabad", "Bangalore"],
        "notice_period": "",
        "current_location": "",
        "total_experience": "",
    }
    assert answer_for("What is your current CTC?", answers) == "6 LPA"
    assert answer_for("Expected salary", answers) == "10 LPA"
    assert answer_for("Are you willing to relocate?", answers) == "Yes"
    assert answer_for("Are you ready to relocate?", answers) == "Yes"
    assert answer_for("How many years of experience do you have in Python?", answers) == "2.5 years"
    assert answer_for("Experience with Machine Learning", answers) == "2 years"
    assert answer_for("What is your total experience?", answers) == "2 years"
    assert answer_for("Relevant experience", answers) == "2 years"
    assert answer_for("How much experience do you have?", answers) == "2 years"
    assert answer_for("Work experience in years", answers) == "2 years"
    assert "Pune" in answer_for("Preferred location", answers)
    assert answer_for("What is your notice period?", answers) is None
    assert "AI Engineer" in answer_for("Why do you want to join us?", answers)
    assert answer_for("Do you know Python?", answers) == "Yes"
    assert answer_for("Do you know Java?", answers) == "No"
    assert answer_for("Highest qualification", answers) == "MCA"
    assert answer_for("Current company", answers) == "Modak analytics llp"
    assert answer_for("Degree", answers) == "Master of Science (M.S.)"
    assert answer_for("First Name", answers) == "Sudhanshu"
    assert answer_for("Family Name", answers) == "Sakhala"
    lwd = answer_for("If serving notice, what is your LAST WORKING DAY?", answers)
    assert lwd and "/" in lwd
    assert answer_for("What is your LWD?", answers) == lwd
    assert answer_for("Do you have a disability that you would like us to consider?", answers) == "No"
    assert "never" in answer_for("If you worked for Nationwide, was it as an associate, an intern, or a contractor?", answers).lower()
    assert answer_for("Are you comfortable working from the office?", answers) == "Yes"
    assert answer_for("Are you serving notice period?", answers) == "Yes"
    assert answer_for("What is your date of birth?", answers) is None


def test_chat_uploads_resume_only_when_the_question_asks_for_it():
    actions = PlaywrightActions(_FakePage())
    assert not actions._should_offer_resume_upload(
        "How many years of experience do you have in RAG (Retrieval-Augmented Generation)?"
    )
    assert not actions._should_offer_resume_upload("Are you willing to relocate?")
    assert actions._should_offer_resume_upload("Please upload your resume to continue")


def test_apply_uses_chat_flow_when_there_is_no_upload_field():
    job_page = (
        "<html><body><button>Apply</button></body></html>",
        "https://www.naukri.com/job-listings-example-100000001",
        "Apply",
    )
    chat_page = (
        "<html><body><div class='chatbot'>Questions</div>"
        "<label>Are you willing to relocate?</label></body></html>",
        "https://www.naukri.com/job-listings-example-100000001",
        "Kindly answer all the recruiter's questions to successfully apply.",
    )
    actions = FakeActions([job_page, chat_page])
    result = run_application(
        actions,
        html=job_page[0],
        url=job_page[1],
        answers={"willing_to_relocate": "Yes"},
        mode="automatic",
        approved=True,
        resume_path="/tmp/tailored.pdf",
        allow_submit=True,
    )
    assert result.status == "successful"
    assert "answer_interest" in actions.calls
    assert "submit" not in actions.calls


def test_captcha_unknown_question_and_approval_do_not_submit():
    captcha = build_apply_plan(
        ApplicationForm(has_captcha=True, has_resume_upload=True),
        {"current_ctc": "6 LPA"},
        mode="automatic",
        approved=True,
        resume_ready=True,
    )
    assert captcha.action == "stop" and captcha.reason == "captcha"

    form = extract_form(
        '<html><body><label>Why do you want this job?</label><input type="file"></body></html>',
        "https://www.naukri.com/job/1",
    )
    answered = build_apply_plan(form, {"current_ctc": "6 LPA"}, mode="automatic", approved=True, resume_ready=True)
    assert answered.action == "submit"
    assert "AI Engineer" in answered.answers["Why do you want this job?"]

    pending = build_apply_plan(form, {"current_ctc": "6 LPA"}, mode="approval", approved=False, resume_ready=True)
    assert pending.action == "pending"

    ready = extract_form(
        '<html><body><label>Current CTC</label><input type="file"></body></html>',
        "https://www.naukri.com/job/1",
    )
    approval = build_apply_plan(ready, {"current_ctc": "6 LPA"}, mode="approval", approved=False, resume_ready=True)
    assert approval.action == "pending"

    page = (
        '<html><body><label>Current CTC</label><input type="file"><button>Submit</button></body></html>',
        "https://www.naukri.com/apply/1",
        "application form",
    )
    actions = FakeActions([page, (*page[:2], "You have successfully applied")])
    result = run_application(
        actions,
        html=page[0],
        url=page[1],
        answers={"current_ctc": "6 LPA"},
        mode="automatic",
        approved=True,
        resume_path="/tmp/tailored.docx",
        allow_submit=True,
    )
    assert result.status == "successful"
    assert "submit" in actions.calls

    blocked = FakeActions(
        [(
            "<html><body>Verify you are human</body></html>",
            "https://www.naukri.com/challenge",
            "Verify you are human",
        )]
    )
    blocked_result = run_application(
        blocked,
        html=blocked.pages[0][0],
        url=blocked.pages[0][1],
        answers={"current_ctc": "6 LPA"},
        mode="automatic",
        approved=True,
        resume_path="/tmp/tailored.docx",
        allow_submit=True,
    )
    assert blocked_result.status == "captcha_blocked"
    assert "submit" not in blocked.calls
    assert "apply" not in blocked.calls


def test_scheduler_uses_an_hourly_interval():
    scheduler = build_scheduler(lambda: None, hours=1)
    scheduler.start()
    try:
        job = scheduler.get_job(JOB_ID)
        assert job is not None
        assert job.trigger.interval == timedelta(hours=1)
    finally:
        scheduler.shutdown(wait=False)


def test_pipeline_tailors_once_and_does_not_apply_twice(tmp_path):
    config = make_config(tmp_path)
    config.application_mode = "automatic"
    before = sha256_file(config.master_resume)
    good = posting_from_dict(SAMPLE_JD)
    poor = posting_from_dict(
        {
            **SAMPLE_JD,
            "job_id": "poor-1",
            "company": "Low Pay Labs",
            "salary": "₹3–4 LPA",
            "job_url": "https://www.naukri.com/poor-role-100000099",
            "description": SAMPLE_JD["description"].replace("₹12–18 LPA", "₹3–4 LPA") + "\nSalary: ₹3–4 LPA",
        }
    )
    calls: list[str] = []

    def applier(job, path, approved) -> ApplyResult:
        calls.append(job["job_id"])
        assert Path(path).exists()
        assert approved
        return ApplyResult("successful", "dry-run")

    first = run_cycle(
        config,
        job_source=lambda: [good, poor],
        applier=applier,
        apply_enabled=True,
        interactive=False,
        write_report=True,
    )
    assert sha256_file(config.master_resume) == before
    assert first.qualified == 1
    assert first.resumes_generated == 1
    assert first.applications == 1
    assert calls == ["job-100"]
    assert first.rejected == 1

    search_only = run_cycle(
        config,
        job_source=lambda: [
            posting_from_dict(
                {
                    **SAMPLE_JD,
                    "job_id": "search-only",
                    "company": "Search Only Labs",
                    "job_url": "https://www.naukri.com/search-only-100000088",
                    "description": SAMPLE_JD["description"].replace("Example Labs", "Search Only Labs"),
                }
            )
        ],
        apply_enabled=False,
        interactive=False,
        write_report=False,
    )
    assert search_only.qualified == 1
    assert search_only.resumes_generated == 1
    stored = Repository(config.database).get_job("search-only")
    assert stored["generated_resume_path"]
    assert Path(stored["generated_resume_path"]).exists()
    report = config.reports / "2026-10-07" 
    # The report folder uses today's date; assert any hourly report exists.
    html_reports = list(config.reports.glob("*/hourly_report.html"))
    assert html_reports
    assert "Qualified" in html_reports[0].read_text(encoding="utf-8")

    second = run_cycle(
        config,
        job_source=lambda: [good, poor],
        applier=applier,
        apply_enabled=True,
        write_report=False,
    )
    assert second.already_processed == 2
    assert calls == ["job-100", "search-only"]
    generated = generate_for_job(config, "job-100")
    assert generated.exists()
    resume = parse_resume(config.master_resume)
    assert resume.name == "Test Candidate"
    assert sha256_file(config.master_resume) == before
    _ = report


def test_profile_resume_uploads_once_per_day(tmp_path):
    from src.browser.profile_resume import dated_pdf_path, refresh_profile_resume
    from src.exceptions import SecurityChallengeError

    class _File:
        def __init__(self) -> None:
            self.path = ""

        def get_attribute(self, name: str) -> str:
            return ".pdf,.doc" if name == "accept" else ""

        def set_input_files(self, path: str) -> None:
            self.path = path

    class _Locator:
        def __init__(self, node) -> None:
            self.node = node

        def count(self) -> int:
            return 0 if self.node is None else 1

        def nth(self, index: int):
            return self.node

    class _Page:
        def __init__(self, body: str = "Resume") -> None:
            self.body = body
            self.file = _File()
            self.url = "https://www.naukri.com/mnjuser/profile"
            self.visits: list[str] = []

        def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
            self.visits.append(url)

        def wait_for_timeout(self, millis: int) -> None:
            return None

        def inner_text(self, selector: str) -> str:
            return self.body

        def locator(self, selector: str) -> _Locator:
            if selector == "#attachCV":
                return _Locator(self.file)
            return _Locator(None)

    config = make_config(tmp_path)
    day = "2026-10-09"
    pdf = dated_pdf_path(config, "Test Candidate", day)
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"x" * 1200)
    page = _Page()
    assert refresh_profile_resume(page, config, day=day) == "uploaded"
    assert page.file.path == str(pdf)
    assert page.visits == ["https://www.naukri.com/mnjuser/profile"]
    assert refresh_profile_resume(page, config, day=day) == "already"
    assert page.visits == ["https://www.naukri.com/mnjuser/profile"]

    blocked_pdf = dated_pdf_path(config, "Test Candidate", "2026-10-10")
    blocked_pdf.write_bytes(b"x" * 1200)
    blocked = _Page("Verify you are human")
    try:
        refresh_profile_resume(blocked, config, day="2026-10-10")
    except SecurityChallengeError:
        pass
    else:
        raise AssertionError("a security check should stop the profile upload")
    assert (tmp_path / "profile_resume_date.txt").read_text(encoding="utf-8").strip() == "2026-10-09"
