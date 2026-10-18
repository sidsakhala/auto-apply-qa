"""Deterministic JD understanding, with an optional LLM pass.

Salary, experience, and skill names are checked against the JD text. A model
cannot introduce a skill the posting does not contain.
"""

from __future__ import annotations

import re

from src.jobs.experience import strictest_experience
from src.jobs.models import JDAnalysis, JobPosting
from src.jobs.relevance import ai_signals, domain_for
from src.llm.base import LLMProvider
from src.llm.prompts import JD_SYSTEM, jd_user_prompt
from src.utils.logger import get_logger
from src.utils.salary import parse_salary
from src.utils.skills import canonicalize, find_skills
from src.utils.text import normalize_space, unique_keep

logger = get_logger("jd")

_SECTION = re.compile(
    r"^(responsibilities|what you(?:'|’)ll do|what you will do|requirements|"
    r"required skills|must have|qualifications|preferred|preferred skills|"
    r"good to have|nice to have|education|about the role)\s*:?\s*$",
    re.IGNORECASE,
)
_EDU = re.compile(
    r"\b(b\.?\s?tech|b\.?\s?e|bachelor|master|m\.?\s?tech|mba|ph\.?\s?d|degree|graduate)\b",
    re.IGNORECASE,
)


def _section_name(line: str) -> str | None:
    match = _SECTION.match(line.strip())
    if not match:
        return None
    name = match.group(1).lower()
    if "prefer" in name or "good to have" in name or "nice to have" in name:
        return "preferred"
    if "responsib" in name or "what you" in name or "about the role" in name:
        return "responsibilities"
    if "educat" in name:
        return "education"
    return "required"


def _lines(text: str) -> list[str]:
    result = []
    for raw in text.splitlines():
        line = normalize_space(raw.lstrip("-*• \t"))
        if line:
            result.append(line)
    return result


def _split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {
        "required": [],
        "preferred": [],
        "responsibilities": [],
        "education": [],
        "body": [],
    }
    current = "body"
    for line in _lines(text):
        detected = _section_name(line)
        if detected:
            current = detected
            continue
        sections[current].append(line)
    return sections


def _education(lines: list[str], body: list[str]) -> list[str]:
    found = [line for line in [*lines, *body] if _EDU.search(line)]
    return unique_keep(found)[:6]


def _responsibilities(lines: list[str]) -> list[str]:
    verbs = re.compile(
        r"^(build|develop|design|implement|own|create|deploy|maintain|collaborate|work|write|train|optimize|lead)\b",
        re.IGNORECASE,
    )
    chosen = lines or []
    if not chosen:
        return []
    detailed = [line for line in chosen if verbs.search(line) or len(line) > 40]
    return unique_keep(detailed or chosen)[:12]


def _keywords(skills: list[str], signals: list[str]) -> list[str]:
    return unique_keep([*skills, *signals])[:25]


def _supported_skills(candidates: list[str], jd_text: str) -> list[str]:
    """Drop skills a model mentioned that the JD text does not contain."""
    present = set(find_skills(jd_text))
    kept: list[str] = []
    lowered = jd_text.lower()
    for skill in candidates:
        if not str(skill).strip():
            continue
        canonical = canonicalize(str(skill))
        if canonical in present or str(skill).lower() in lowered:
            kept.append(str(skill).strip())
    return unique_keep(kept)


def analyze_jd_heuristic(posting: JobPosting) -> JDAnalysis:
    description = posting.description_or_card()
    sections = _split_sections(description)
    salary = parse_salary(posting.salary_text or description)
    experience = strictest_experience(posting.experience_text, description, posting.url)
    required = find_skills("\n".join(sections["required"] or sections["body"]))
    preferred = [skill for skill in find_skills("\n".join(sections["preferred"])) if skill not in required]
    # Skills that only appear in the body are requirements when no explicit list exists.
    if sections["required"]:
        body_only = [skill for skill in find_skills("\n".join(sections["body"])) if skill not in required and skill not in preferred]
        required = unique_keep([*required, *body_only])
    signals = ai_signals(f"{posting.title}\n{description}")
    responsibilities = _responsibilities(sections["responsibilities"] or sections["body"])
    education = _education(sections["education"], sections["body"])
    skills = unique_keep([*required, *preferred])
    return JDAnalysis(
        job_title=posting.title,
        company=posting.company,
        location=posting.location,
        salary=salary.label if salary.disclosed or salary.text else (posting.salary_text or "Not Disclosed"),
        salary_min_lpa=salary.min_lpa,
        salary_max_lpa=salary.max_lpa,
        salary_disclosed=salary.disclosed,
        experience_required=experience.text or posting.experience_text,
        experience_min=experience.minimum,
        experience_max=experience.maximum,
        required_skills=required,
        preferred_skills=preferred,
        responsibilities=responsibilities,
        education_requirements=education,
        keywords=_keywords(skills, signals),
        domain=domain_for(signals, description),
        ai_signals=signals,
    )


def _as_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def analyze_jd(posting: JobPosting, llm: LLMProvider | None = None) -> JDAnalysis:
    """Analyze a JD. The numeric salary and experience fields stay deterministic."""
    base = analyze_jd_heuristic(posting)
    if llm is None or not llm.available:
        return base
    try:
        raw = llm.complete_json(
            system=JD_SYSTEM,
            user=jd_user_prompt(
                title=posting.title,
                company=posting.company,
                location=posting.location,
                description=posting.description_or_card(),
            ),
        )
    except Exception as exc:  # provider/network/parse errors fall back safely
        logger.warning("LLM JD analysis failed (%s). Using the deterministic extractor.", exc)
        return base

    description = posting.description_or_card()
    required = _supported_skills(_as_list(raw.get("required_skills")), description)
    preferred = [
        skill
        for skill in _supported_skills(_as_list(raw.get("preferred_skills")), description)
        if canonicalize(skill) not in {canonicalize(item) for item in required}
    ]
    if required:
        base.required_skills = unique_keep([*required, *base.required_skills])
    if preferred:
        base.preferred_skills = [
            skill
            for skill in unique_keep([*preferred, *base.preferred_skills])
            if canonicalize(skill) not in {canonicalize(item) for item in base.required_skills}
        ]
    responsibilities = _as_list(raw.get("responsibilities"))
    grounded = [
        line
        for line in responsibilities
        if line.lower()[:48] in description.lower() or len(set(line.lower().split()) & set(description.lower().split())) >= 3
    ]
    if grounded:
        base.responsibilities = unique_keep([*grounded, *base.responsibilities])[:12]
    domain = str(raw.get("domain") or "").strip()
    if domain:
        base.domain = domain
    base.keywords = _keywords(unique_keep([*base.required_skills, *base.preferred_skills]), base.ai_signals)
    return base
