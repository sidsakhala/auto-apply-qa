"""Map screening questions to answers from the candidate's saved details.

Experience questions are answered with 2 years. Other questions are answered
from the resume and application settings. Identity fields that are not on the
resume, such as date of birth, are left unanswered.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from src.utils.skills import find_skills

RULES: list[tuple[tuple[str, ...], str]] = [
    (("current ctc", "current salary", "present salary", "present ctc"), "current_ctc"),
    (("expected ctc", "expected salary"), "expected_ctc"),
    (("notice period", "notice-period"), "notice_period"),
    (("relocat", "willing to move", "ready to move", "open to moving"), "willing_to_relocate"),
    (("preferred location", "preferred city", "job location"), "preferred_locations"),
    (("current location", "present location"), "current_location"),
    (("total experience", "years of experience", "overall experience"), "total_experience"),
    (("work authorization", "authorized to work", "visa status"), "work_authorization"),
]

_PROFILE_REPLY = (
    "I am an AI Engineer with 2 years of experience, currently at Modak Analytics, "
    "and I am interested in this role."
)
_PRIVATE = re.compile(
    r"\b(?:date of birth|birth date|dob|marital|religion|"
    r"medical|criminal|convicted|offense|offence|aadhaar|aadhar|pan card|pan number)\b",
    re.IGNORECASE,
)
_ROLE_DESCRIPTION = (
    "AI Engineer with 2.1 years of experience architecting and deploying production-grade Agentic AI systems, "
    "LLM applications, and enterprise AI platforms. Strong expertise in LangGraph, LangChain, MCP, RAG, "
    "LLM orchestration, context engineering, AI memory, and PostgreSQL/pgvector. Experienced in integrating "
    "6+ LLM providers, building 150+ MCP tools, and developing scalable FastAPI-based agent services with "
    "streaming, observability, and reliability controls. Proven track record of reducing context usage by ~93%, "
    "token consumption by 65%, and LLM inference costs by 70-80% through intelligent architecture and optimization"
)
_SKILL_ASK = re.compile(
    r"\b(?:do you know|have you worked|familiar|proficient|hands[- ]on|knowledge of|worked on|worked with)\b",
    re.IGNORECASE,
)
_RESUME_SKILLS: set[str] | None = None


def is_experience_question(question: str) -> bool:
    """True for every screening question about experience, skill-specific or not."""
    return bool(re.search(r"\b(?:experience|experienced|exp)\b", question or "", re.IGNORECASE))


def is_known_question(question: str) -> bool:
    if "password" in (question or "").lower():
        return False
    if is_experience_question(question):
        return True
    if _company_answer(question, {}):
        return True
    lowered = question.lower()
    if any(any(key in lowered for key in keys) for keys, _field in RULES):
        return True
    return _reply_accordingly(question) is not None


def _configured(answers: dict, field: str) -> str | None:
    value = answers.get(field)
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, list):
        rendered = ", ".join(str(item) for item in value if str(item).strip())
        return rendered or None
    return str(value)


def _experience_answer(answers: dict) -> str:
    return _configured(answers, "skill_experience") or _configured(answers, "total_experience") or "2 years"


def _resume_skills() -> set[str]:
    global _RESUME_SKILLS
    if _RESUME_SKILLS is None:
        path = Path(__file__).resolve().parents[2] / "resume" / "overleaf" / "My_Resume" / "main.tex"
        text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        _RESUME_SKILLS = set(find_skills(text))
    return _RESUME_SKILLS


def _skill_reply(question: str) -> str | None:
    asked = find_skills(question)
    if not asked and not _SKILL_ASK.search(question):
        return None
    if asked and all(skill in _resume_skills() for skill in asked):
        return "Yes"
    return "No"


def _field(answers: dict, key: str, default: str) -> str:
    return _configured(answers, key) or default


def is_lwd_question(question: str) -> bool:
    lowered = " ".join((question or "").lower().split())
    return any(
        token in lowered
        for token in ("last working day", "last working date", "last day of work", " lwd", "lwd ")
    )


def is_serving_notice_question(question: str) -> bool:
    lowered = " ".join((question or "").lower().split())
    return any(token in lowered for token in ("serving notice", "on notice period", "serving notice period"))


def last_working_day_value(answers: dict | None = None) -> str:
    """Last working day about one month from today, unless set in application_answers.yaml."""
    custom = _configured(answers or {}, "last_working_day")
    if custom:
        return custom
    return (date.today() + timedelta(days=30)).strftime("%d/%m/%Y")


def is_combined_notice_lwd_question(question: str) -> bool:
    lowered = " ".join((question or "").lower().split())
    return "notice period" in lowered and (
        "lwd" in lowered or "last working" in lowered or "official notice" in lowered
    )


def recruiter_screening_answer(question: str, answers: dict) -> str | None:
    """Answers for long Naukri recruiter chat questionnaires."""
    lowered = " ".join((question or "").lower().split())
    if not lowered:
        return None
    if is_combined_notice_lwd_question(question):
        return _field(answers, "recruiter_notice_reply", "18 November")
    if any(token in lowered for token in ("10th", "10 th", "tenth", "matric")) and any(
        token in lowered for token in ("year", "percent", "passed", "class")
    ):
        return _field(answers, "class_10", "2017 and 68%")
    if any(token in lowered for token in ("12th", "twelfth", "diploma")) and any(
        token in lowered for token in ("year", "percent", "passed")
    ):
        return _field(answers, "class_12", "2019 and 65%")
    if "graduation" in lowered and any(
        token in lowered for token in ("year", "percent", "passed", "b.tech", "b.e", "bcs", "bachelor")
    ):
        return _field(answers, "graduation", "BCS -2022-77%")
    if "live offer" in lowered or "offer in hand" in lowered or "offers in hand" in lowered:
        return _field(answers, "live_offer", "NA")
    if "location" in lowered and "current" in lowered and "preferred" in lowered:
        return _field(answers, "current_and_preferred_location", "Hyderabad")
    if "overall experience" in lowered and "relevant" in lowered:
        return _field(answers, "overall_relevant_experience", "2.5 years")
    if "highest educational" in lowered or (
        "highest" in lowered and "qualification" in lowered and "passed" in lowered
    ):
        return _field(answers, "highest_qualification", "2024 - MCA - 79%")
    return None


def _company_answer(question: str, answers: dict) -> str | None:
    """Answers for company career-site fields and the questions those forms ask."""
    lowered = " ".join((question or "").lower().split())
    if not lowered:
        return None
    if is_lwd_question(question):
        return last_working_day_value(answers)
    if any(token in lowered for token in ("disability", "reasonable accommodation")):
        return "No"
    if "pronoun" in lowered:
        return _field(answers, "pronouns", "He/Him/His")
    if re.search(r"\bgender\b", lowered):
        return _field(answers, "gender", "Male")
    if "hispanic" in lowered or "latino" in lowered:
        return "No"
    if re.search(r"\brace\b", lowered):
        return _field(answers, "race", "Asian")
    if "veteran" in lowered:
        return _field(answers, "veteran_status", "I am not a protected veteran")
    if "household" in lowered or "family member" in lowered:
        return "No"
    if any(token in lowered for token in ("outside business", "intend to continue")):
        return "No"
    if any(token in lowered for token in ("non-competition", "noncompetition", "non-solicit", "nonsolicit")):
        return "No"
    if any(token in lowered for token in ("advisory board", "serving on the board", "board of any")):
        return "No"
    if any(name in lowered for name in ("belarus", "cuba", "iran", "north korea", "syria", "zaporiz", "crimea", "donetsk", "luhansk")):
        return "No"
    if "sponsorship" in lowered or "sponsor" in lowered:
        return "No"
    if any(token in lowered for token in ("worked for", "worked at", "in any capacity", "associate, an intern")):
        return "I have never worked for this employer"
    if any(token in lowered for token in ("come into the office", "work in the office", "able to meet the requirements")):
        return "Yes"
    if any(token in lowered for token in ("authorization to work", "authorised to work", "authorized to work", "right to work")):
        if "countries" in lowered or "country" in lowered and "unrestricted" in lowered:
            return "India"
        return "Yes"
    if any(token in lowered for token in ("capturing and storing your image", "storing your image")):
        return "Yes, I consent"
    if any(token in lowered for token in ("terms and conditions", "privacy notice", "privacy policy")):
        return "Yes, I have read and consent to the terms and conditions"
    if "i acknowledge" in lowered or "candidate privacy" in lowered:
        return "I acknowledge"
    if "how should we communicate" in lowered or "communicate with you" in lowered:
        return "Email"
    if "role description" in lowered:
        return _field(answers, "role_description", _ROLE_DESCRIPTION)
    if not _short_label(lowered):
        return None
    if "email" in lowered:
        return _field(answers, "email", "sudhanshu.sakhala2002@gmail.com")
    if "local given" in lowered or "preferred first" in lowered or "preferred name" in lowered:
        return _field(answers, "given_name", "Sudhanshu")
    if "local family" in lowered:
        return _field(answers, "family_name", "Sakhala")
    if "given name" in lowered or "first name" in lowered:
        return _field(answers, "given_name", "Sudhanshu")
    if "family name" in lowered or "last name" in lowered:
        return _field(answers, "family_name", "Sakhala")
    if "address line 1" in lowered:
        return _field(answers, "address_line_1", "room 413, Varnav living spaces , gowlidoddy")
    if "address line 2" in lowered:
        return _field(answers, "address_line_2", "Hyderabad")
    if "postal" in lowered or "zip code" in lowered or lowered.startswith("pin "):
        return _field(answers, "postal_code", "500032")
    if "phone device" in lowered:
        return _field(answers, "phone_device", "Personal Cellular")
    if "phone code" in lowered or "country code" in lowered:
        return _field(answers, "phone_country", "India (+91)")
    if "phone" in lowered or "mobile" in lowered:
        return _field(answers, "phone_number", "7744869769")
    if lowered.startswith("city") or lowered == "location" or "location (city)" in lowered:
        return _field(answers, "city", "Hyderabad")
    if lowered.startswith("state"):
        return _field(answers, "state", "Telangana")
    if lowered.startswith("country"):
        return _field(answers, "country", "India")
    if "job title" in lowered or lowered == "title":
        return _field(answers, "job_title", "AI Engineer")
    if "company" in lowered:
        return _field(answers, "employer", "Modak analytics llp")
    if "field of study" in lowered or "discipline" in lowered:
        return _field(answers, "field_of_study", "Computer Science")
    if "degree" in lowered:
        return _field(answers, "degree", "Master of Science (M.S.)")
    if any(token in lowered for token in ("gpa", "cgpa", "overall result")):
        return _field(answers, "gpa", "8.3")
    if any(token in lowered for token in ("school", "university", "college")):
        return _field(answers, "school", "Dr. Vishwanath Karad MIT World Peace University")
    if lowered in {"from", "start date"} or lowered.startswith("from "):
        return _field(answers, "work_from", "11/2024")
    if "currently work" in lowered:
        return "Yes"
    if "linkedin" in lowered:
        return _field(answers, "linkedin", "https://linkedin.com/in/sudhanshu-sakhala-800444191")
    return None


def _short_label(lowered: str) -> bool:
    return "?" not in lowered and len(lowered) <= 80


def _reply_accordingly(question: str) -> str | None:
    """Answer a question that is not one of the saved CTC, notice, or location fields."""
    lowered = " ".join((question or "").lower().split())
    if not lowered or _PRIVATE.search(lowered):
        return None
    if is_combined_notice_lwd_question(question):
        return _field(answers, "recruiter_notice_reply", "18 November")
    if is_serving_notice_question(question):
        return "Yes"
    if any(token in lowered for token in ("under a bond", "serving bond")):
        return "No"
    if any(token in lowered for token in ("immediate joiner", "join immediately", "immediate joining", "joining immediately")):
        return "No"
    if any(token in lowered for token in ("when can you join", "how soon can you join", "earliest joining", "joining time")):
        return "30 days"
    if "sponsor" in lowered:
        return "No"
    if any(token in lowered for token in ("full name", "your name", "candidate name")):
        return "Sudhanshu Sakhala"
    if "linkedin" in lowered:
        return "https://linkedin.com/in/sudhanshu-sakhala-800444191"
    if "email" in lowered:
        return "sudhanshu.sakhala2002@gmail.com"
    if any(token in lowered for token in ("phone", "mobile", "contact number")):
        return "+91-7744869769"
    if any(token in lowered for token in ("university", "college", "institute")):
        return "Dr. Vishwanath Karad MIT World Peace University"
    if any(token in lowered for token in ("cgpa", "gpa")):
        return "8.11/10"
    if any(token in lowered for token in ("qualification", "education", "degree", "graduat")):
        if "year" in lowered:
            return "2024"
        return "MCA"
    if any(token in lowered for token in ("current company", "present company", "employer", "company name", "organization", "organisation")):
        return "Modak Analytics"
    if any(token in lowered for token in ("designation", "current role", "job title", "current position", "current designation")):
        return "AI Engineer"
    skill_reply = _skill_reply(question)
    if skill_reply:
        return skill_reply
    if re.search(r"\b(?:willing|comfortable|interested|open to|ready to|happy to)\b", lowered):
        return "Yes"
    if re.search(r"\b(?:why|about yourself|introduce yourself|reason for|strength|weakness|describe yourself)\b", lowered):
        return _PROFILE_REPLY
    if re.match(r"(?:are|do|can|will|would|have|has|is|did|should)\b", lowered):
        return "Yes"
    return _PROFILE_REPLY


def _chat_experience_value(answers: dict) -> str:
    raw = _experience_answer(answers)
    match = re.search(r"[\d.]+", raw)
    return match.group(0) if match else raw


def interest_reply(question: str, answers: dict) -> str | None:
    """Short answers for the Naukri recruiter chat after I am interested."""
    screening = recruiter_screening_answer(question, answers)
    if screening:
        return screening
    if is_lwd_question(question):
        return last_working_day_value(answers)
    if is_serving_notice_question(question) and not is_combined_notice_lwd_question(question):
        return "Yes"
    if is_experience_question(question):
        return _chat_experience_value(answers)
    reply = answer_for(question, answers)
    if reply and reply.lower().startswith("yes"):
        return "Yes"
    return reply


def answer_for(question: str, answers: dict) -> str | None:
    """Return the reply for one screening question.

    A saved field that was left blank stays unanswered. Every other question
    gets a reply based on the resume and the saved application answers.
    """
    if "password" in (question or "").lower():
        return None
    screening = recruiter_screening_answer(question, answers)
    if screening:
        return screening
    if is_lwd_question(question):
        return last_working_day_value(answers)
    if is_serving_notice_question(question) and not is_combined_notice_lwd_question(question):
        return "Yes"
    if is_experience_question(question):
        return _experience_answer(answers)
    company = _company_answer(question, answers)
    if company:
        return company
    lowered = question.lower()
    for keys, field in RULES:
        if not any(key in lowered for key in keys):
            continue
        return _configured(answers, field)
    return _reply_accordingly(question)
