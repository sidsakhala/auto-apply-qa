"""Reject tailored resumes that invent facts."""

from __future__ import annotations

import re

from src.resume.matcher import profile_skills, skill_corpus
from src.resume.models import Experience, Resume
from src.utils.skills import AI_EVIDENCE_TERMS, canonicalize, find_skills
from src.utils.text import content_words, jaccard, normalize_space, numbers_in

TEMPLATE_MARKER = "TEMPLATE_NOT_A_REAL_RESUME"
_SUFFIX = re.compile(r"\s+supporting AI/ML workflows\.?$", re.IGNORECASE)


class ValidationResult:
    def __init__(self, errors: list[str] | None = None) -> None:
        self.errors = errors or []

    @property
    def ok(self) -> bool:
        return not self.errors


def is_template_resume(resume: Resume) -> bool:
    return TEMPLATE_MARKER in (resume.raw_text or "")


def _same_texts(left: list[str], right: list[str]) -> bool:
    return [normalize_space(item) for item in left] == [normalize_space(item) for item in right]


def _peel_suffix(bullet: str, evidence: set[str]) -> tuple[str, str | None]:
    match = _SUFFIX.search(bullet.strip())
    if not match:
        return bullet.strip(), None
    if not (evidence & AI_EVIDENCE_TERMS):
        return bullet.strip(), "AI/ML wording was added without AI evidence in that role"
    return bullet.strip()[: match.start()].rstrip(), None


def _grounded(bullet: str, originals: list[str], evidence: set[str]) -> str | None:
    peeled, error = _peel_suffix(bullet, evidence)
    if error:
        return error
    source_text = " ".join(originals)
    if not numbers_in(peeled) <= numbers_in(source_text):
        return "A bullet adds a number that is not in the original role"
    allowed = set(find_skills(source_text)) | set(evidence)
    extra = [skill for skill in find_skills(peeled) if skill not in allowed]
    if extra:
        return f"A bullet adds skills that are not in that role: {', '.join(extra)}"

    peeled_key = normalize_space(peeled).lower().rstrip(".")
    for original in originals:
        original_key = normalize_space(original).lower().rstrip(".")
        if peeled_key == original_key:
            return None
        rewritten = peeled_key
        source = original_key
        if source.startswith("worked on ") and rewritten.startswith("developed "):
            rewritten = "worked on " + rewritten[len("developed ") :]
        if rewritten.rstrip(".") == source.rstrip("."):
            return None
        if jaccard(content_words(peeled), content_words(original)) >= 0.55:
            return None
    return "A bullet does not match any original responsibility or achievement"


def validate_tailored(
    master: Resume,
    summary: str,
    experience: list[Experience],
    skills: list[str],
    projects: list,
    *,
    profile: dict | None = None,
) -> ValidationResult:
    errors: list[str] = []
    corpus = skill_corpus(master, profile)
    allowed_section = {canonicalize(skill) for skill in master.skills}
    allowed_section.update(canonicalize(skill) for skill in profile_skills(profile))

    if numbers_in(summary) - numbers_in(master.raw_text):
        errors.append("The summary adds numbers that are not in the master resume")
    invented = [skill for skill in find_skills(summary) if skill not in corpus]
    if invented:
        errors.append("The summary adds skills that are not in the master resume: " + ", ".join(invented))

    for skill in skills:
        if canonicalize(skill) not in allowed_section:
            errors.append(f"Skill '{skill}' is not in the master skills section or candidate profile")

    if len(experience) != len(master.experience):
        errors.append("Tailoring changed the number of jobs")
    for original, updated in zip(master.experience, experience):
        if normalize_space(original.company) != normalize_space(updated.company):
            errors.append(f"Company changed from '{original.company}' to '{updated.company}'")
        if normalize_space(original.role) != normalize_space(updated.role):
            errors.append(f"Job title changed from '{original.role}' to '{updated.role}'")
        if normalize_space(original.duration) != normalize_space(updated.duration):
            errors.append("Employment dates changed")
        if _same_texts(original.technologies, updated.technologies) is False:
            errors.append(f"Technologies changed for {original.company}")
        evidence = set(find_skills(" ".join([*original.bullets(), *original.technologies, original.role])))
        source = original.bullets()
        output = updated.bullets()
        if len(output) != len(source):
            errors.append(f"Bullet count changed for {original.role or original.company}")
            continue
        for bullet in output:
            problem = _grounded(bullet, source, evidence)
            if problem:
                errors.append(problem)

    if [normalize_space(item) for item in master.certifications] != []:
        pass
    if len(projects) != len(master.projects):
        errors.append("Tailoring changed the number of projects")

    return ValidationResult(errors)


def validate_identity(master: Resume, certifications: list[str], education: list) -> list[str]:
    errors = []
    if [normalize_space(item) for item in certifications] != [normalize_space(item) for item in master.certifications]:
        errors.append("Certifications changed")
    if len(education) != len(master.education):
        errors.append("Education changed")
    for original, updated in zip(master.education, education):
        if (
            normalize_space(original.degree) != normalize_space(updated.degree)
            or normalize_space(original.institution) != normalize_space(updated.institution)
            or normalize_space(original.year) != normalize_space(updated.year)
        ):
            errors.append("Education facts changed")
    return errors
