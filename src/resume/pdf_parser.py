"""Extract structured resume data from a PDF using pdftotext."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from src.exceptions import ConfigurationError
from src.resume.models import Education, Experience, Project, Resume
from src.resume.parser import SECTION_ALIASES, _ACHIEVEMENT, _clean_bullet, _split_list, _split_meta
from src.utils.text import normalize_space, unique_keep

_BULLET = re.compile(r"^\s*[•\-\*]\s+")
_SECTION = {alias.upper(): name for name, aliases in SECTION_ALIASES.items() for alias in aliases}
_DATE_TAIL = re.compile(
    r"\s{2,}((?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|Present|Current).*)$",
    re.IGNORECASE,
)


def _parse_experience_header(line: str) -> tuple[str, str, str] | None:
    tail = _DATE_TAIL.search(line)
    if tail is None:
        return None
    head = normalize_space(line[: tail.start()])
    duration = normalize_space(tail.group(1))
    if not head:
        return None
    parts = re.split(r"\s*[—–-]\s*", head, maxsplit=1)
    if len(parts) == 2:
        return normalize_space(parts[0]), normalize_space(parts[1]), duration
    return head, "", duration


def _pdf_text(path: Path) -> str:
    try:
        completed = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise ConfigurationError("pdftotext is required to read PDF resumes.") from exc
    except subprocess.CalledProcessError as exc:
        raise ConfigurationError(f"Could not read PDF resume at {path}: {exc.stderr.strip()}") from exc
    return completed.stdout or ""


def _section_for(line: str) -> str | None:
    key = normalize_space(line).upper().rstrip(":")
    if key in _SECTION:
        return _SECTION[key]
    for alias, name in _SECTION.items():
        if key == alias or key.startswith(alias + " "):
            return name
    return None


def _is_bullet(line: str) -> bool:
    return bool(_BULLET.match(line))


def parse_resume_pdf(path: Path | str) -> Resume:
    path = Path(path)
    if not path.exists():
        raise ConfigurationError(f"PDF resume not found at {path}.")
    raw_text = _pdf_text(path)
    name = ""
    section = ""
    summary: list[str] = []
    skills: list[str] = []
    certifications: list[str] = []
    experience: list[Experience] = []
    projects: list[Project] = []
    education: list[Education] = []
    current_exp: Experience | None = None
    current_project: Project | None = None
    current_edu: Education | None = None

    def flush_education() -> None:
        nonlocal current_edu
        if current_edu and current_edu.degree:
            education.append(current_edu)
        current_edu = None

    raw_lines = raw_text.splitlines()
    for index, raw_line in enumerate(raw_lines):
        line = normalize_space(raw_line)
        if not line:
            continue
        detected = _section_for(line)
        if detected:
            flush_education()
            section = detected
            current_exp = None
            current_project = None
            continue

        if index == 0 and not name:
            name = line
            continue

        if section == "summary":
            summary.append(line)
        elif section == "skills":
            if ":" in line:
                _, _, rest = line.partition(":")
                skills.extend(_split_list(rest))
            else:
                skills.extend(_split_list(line))
        elif section == "certifications":
            certifications.append(_clean_bullet(line))
        elif section == "experience":
            parsed = _parse_experience_header(raw_line) if not _is_bullet(line) else None
            if parsed:
                role, company, duration = parsed
                current_exp = Experience(
                    company=normalize_space(company),
                    role=normalize_space(role),
                    duration=normalize_space(duration),
                )
                experience.append(current_exp)
                continue
            if _is_bullet(line):
                if current_exp is None:
                    current_exp = Experience(company="", role="", duration="")
                    experience.append(current_exp)
                bullet = _clean_bullet(line)
                if _ACHIEVEMENT.search(bullet):
                    current_exp.achievements.append(bullet)
                else:
                    current_exp.responsibilities.append(bullet)
        elif section == "projects":
            if _is_bullet(line):
                if current_project is None:
                    current_project = Project(name="")
                    projects.append(current_project)
                current_project.bullets.append(_clean_bullet(line))
            else:
                current_project = Project(name=line)
                projects.append(current_project)
        elif section == "education":
            if current_edu is None or (current_edu.degree and current_edu.institution):
                flush_education()
                parts = _split_meta(line)
                year = parts[-1] if parts and re.search(r"(19|20)\d{2}", parts[-1]) else ""
                degree = parts[0] if parts else line
                current_edu = Education(degree=degree, year=year)
            elif current_edu and not current_edu.institution:
                current_edu.institution = line

    flush_education()
    experience = [item for item in experience if item.role or item.company or item.bullets()]
    projects = [item for item in projects if item.name or item.bullets]
    if not name:
        for raw_line in raw_text.splitlines():
            first = normalize_space(raw_line)
            if first:
                name = first
                break
    return Resume(
        name=name,
        summary=" ".join(summary).strip(),
        experience=experience,
        projects=projects,
        skills=unique_keep(skills),
        certifications=unique_keep([item for item in certifications if item]),
        education=education,
        raw_text=raw_text,
    )
