"""Read the Overleaf resume into the same sections the scorer uses.

The TeX file is only read. Tailored PDFs are written from a separate copy.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.resume.models import Education, Experience, Resume
from src.utils.text import normalize_space, unique_keep

_SECTION = re.compile(r"\\section\{([^{}]+)\}")
_SUBHEADING = re.compile(r"\\resumeSubheading")
_ITEM = re.compile(r"\\resumeItem\{")
_SKILL_ITEM = re.compile(r"\\item\s*\\textbf\{([^{}]+)\}\s*(.*)")


def parse_overleaf_tex(path: Path | str) -> Resume:
    path = Path(path)
    source = path.read_text(encoding="utf-8", errors="replace")
    body = source.split(r"\begin{document}", 1)[-1]
    body = body.split(r"\end{document}", 1)[0]
    name = _name(source)
    sections = _sections(body)
    summary = _plain(sections.get("professional summary", ""))
    skills = _skills(sections.get("technical skills", "") or sections.get("skills", ""))
    experience = _roles(sections.get("professional experience", "") or sections.get("experience", ""))
    education = _education(sections.get("education", ""))
    plain = _plain(body)
    return Resume(
        name=name,
        summary=summary,
        experience=experience,
        skills=skills,
        education=education,
        raw_text=plain,
    )


def _name(source: str) -> str:
    body = source.split(r"\begin{document}", 1)[-1]
    match = re.search(r"\\textbf\{([^{}]+)\}", body)
    return _plain(match.group(1)) if match else ""


def _sections(body: str) -> dict[str, str]:
    matches = list(_SECTION.finditer(body))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = _plain(match.group(1)).lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[title] = body[start:end]
    return sections


def _skills(section: str) -> list[str]:
    skills: list[str] = []
    for line in section.splitlines():
        match = _SKILL_ITEM.search(line)
        if not match:
            continue
        skills.extend(_split_skill_items(_plain(match.group(2))))
    return unique_keep(skills)


def _split_skill_items(text: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        if char == "," and depth == 0:
            item = normalize_space("".join(current))
            if item:
                items.append(item)
            current = []
            continue
        current.append(char)
    tail = normalize_space("".join(current))
    if tail:
        items.append(tail)
    return items


def _roles(section: str) -> list[Experience]:
    roles: list[Experience] = []
    for block in _SUBHEADING.split(section)[1:]:
        args, rest = _brace_groups(block, 4)
        if len(args) < 3:
            continue
        bullets = [_plain(item) for item in _item_bodies(rest)]
        roles.append(
            Experience(
                company=_plain(args[0]),
                role=_plain(args[2]),
                duration=_plain(args[1]),
                responsibilities=[bullet for bullet in bullets if bullet],
            )
        )
    return roles


def _education(section: str) -> list[Education]:
    records: list[Education] = []
    for block in _SUBHEADING.split(section)[1:]:
        args, rest = _brace_groups(block, 4)
        if len(args) < 3:
            continue
        details = " ".join(_plain(item) for item in _item_bodies(rest) if _plain(item))
        records.append(
            Education(
                degree=_plain(args[2]),
                institution=_plain(args[0]),
                year=_plain(args[1]),
                details=details,
            )
        )
    return records


def _brace_groups(text: str, count: int) -> tuple[list[str], str]:
    groups: list[str] = []
    index = 0
    while len(groups) < count and index < len(text):
        while index < len(text) and text[index] != "{":
            if text[index] == "\\" and not text.startswith(r"\resume", index):
                break
            index += 1
        if index >= len(text) or text[index] != "{":
            break
        depth = 0
        start = index + 1
        while index < len(text):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    groups.append(text[start:index])
                    index += 1
                    break
            index += 1
    return groups, text[index:]


def _item_bodies(text: str) -> list[str]:
    bodies: list[str] = []
    for match in _ITEM.finditer(text):
        groups, _rest = _brace_groups(text[match.end() - 1 :], 1)
        if groups:
            bodies.append(groups[0])
    return bodies


def _plain(text: str) -> str:
    text = re.sub(r"(?<!\\)%.*", "", text)
    replacements = {
        r"\%": "%",
        r"\&": "&",
        r"\rightarrow": "->",
        r"$\sim$": "~",
        r"$\times$": "x",
        "--": "–",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"\\textbf\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    return normalize_space(text)
