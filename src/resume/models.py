"""Structured resume and match records."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Experience:
    company: str
    role: str
    duration: str
    responsibilities: list[str] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)
    technologies: list[str] = field(default_factory=list)

    def bullets(self) -> list[str]:
        return [*self.responsibilities, *self.achievements]


@dataclass
class Project:
    name: str
    bullets: list[str] = field(default_factory=list)
    technologies: list[str] = field(default_factory=list)


@dataclass
class Education:
    degree: str
    institution: str = ""
    year: str = ""
    details: str = ""


@dataclass
class Resume:
    name: str
    summary: str
    experience: list[Experience] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    education: list[Education] = field(default_factory=list)
    raw_text: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "summary": self.summary,
            "experience": [
                {
                    "company": item.company,
                    "role": item.role,
                    "duration": item.duration,
                    "responsibilities": list(item.responsibilities),
                    "achievements": list(item.achievements),
                    "technologies": list(item.technologies),
                }
                for item in self.experience
            ],
            "projects": [
                {"name": item.name, "bullets": list(item.bullets), "technologies": list(item.technologies)}
                for item in self.projects
            ],
            "skills": list(self.skills),
            "certifications": list(self.certifications),
            "education": [
                {
                    "degree": item.degree,
                    "institution": item.institution,
                    "year": item.year,
                    "details": item.details,
                }
                for item in self.education
            ],
        }


@dataclass
class SkillMatch:
    matching_skills: list[str] = field(default_factory=list)
    partial_match: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    pairs: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "matching_skills": list(self.matching_skills),
            "partial_match": list(self.partial_match),
            "missing_skills": list(self.missing_skills),
            "pairs": list(self.pairs),
        }


@dataclass
class ResumeScores:
    overall: float
    skills: float
    experience: float
    role: float
    cloud_ai: float

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "skills": self.skills,
            "experience": self.experience,
            "role": self.role,
            "cloud_ai": self.cloud_ai,
        }
