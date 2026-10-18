"""Prompts. Every prompt forbids inventing candidate facts."""

from __future__ import annotations

JD_SYSTEM = """You extract structured facts from a job description.
Return a single JSON object with these keys:
job_title, company, location, salary, experience_required,
required_skills, preferred_skills, responsibilities,
education_requirements, keywords, domain.
Skills must be copied from the job description, not inferred from prestige or habit.
Do not add a skill that the text does not state.
Use an empty list or empty string when the text does not say.
"""

TAILOR_SYSTEM = """You rewrite a resume so it emphasizes experience the candidate already has.
Return a single JSON object with keys:
summary (string),
bullets (list of {company, role, original, rewritten}),
skills_order (list of skill names).

Rules you must not break:
- Do not invent employers, titles, dates, education, certifications, projects, or skills.
- Do not add a technology just because the job description mentions it.
- Do not add metrics, percentages, or headcount that are not in the original bullet.
- skills_order may only contain skills from the allowed list.
- rewritten must preserve the factual meaning of original.
- If a required skill is missing, leave it out. Do not imply the candidate has it.
"""


def jd_user_prompt(*, title: str, company: str, location: str, description: str) -> str:
    return (
        f"Job title: {title}\nCompany: {company}\nLocation: {location}\n\n"
        f"Job description:\n{description}"
    )


def tailor_user_prompt(*, resume_facts: str, jd_summary: str, allowed_skills: list[str]) -> str:
    skills = ", ".join(allowed_skills)
    return (
        "Allowed skills (only these may appear as skills):\n"
        f"{skills}\n\n"
        "Candidate facts:\n"
        f"{resume_facts}\n\n"
        "Job description analysis:\n"
        f"{jd_summary}\n"
    )
