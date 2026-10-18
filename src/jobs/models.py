"""Job posting and JD analysis records."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class JobPosting:
    job_id: str
    title: str
    company: str
    location: str
    salary_text: str = ""
    experience_text: str = ""
    url: str = ""
    description: str = ""

    def description_or_card(self) -> str:
        return self.description or " ".join(
            part for part in (self.title, self.company, self.location, self.salary_text, self.experience_text) if part
        )


@dataclass
class JDAnalysis:
    job_title: str = ""
    company: str = ""
    location: str = ""
    salary: str = ""
    salary_min_lpa: float | None = None
    salary_max_lpa: float | None = None
    salary_disclosed: bool = False
    experience_required: str = ""
    experience_min: float | None = None
    experience_max: float | None = None
    required_skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    education_requirements: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    domain: str = ""
    ai_signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "job_title": self.job_title,
            "company": self.company,
            "location": self.location,
            "salary": self.salary,
            "salary_min_lpa": self.salary_min_lpa,
            "salary_max_lpa": self.salary_max_lpa,
            "salary_disclosed": self.salary_disclosed,
            "experience_required": self.experience_required,
            "experience_min": self.experience_min,
            "experience_max": self.experience_max,
            "required_skills": list(self.required_skills),
            "preferred_skills": list(self.preferred_skills),
            "responsibilities": list(self.responsibilities),
            "education_requirements": list(self.education_requirements),
            "keywords": list(self.keywords),
            "domain": self.domain,
            "ai_signals": list(self.ai_signals),
        }
