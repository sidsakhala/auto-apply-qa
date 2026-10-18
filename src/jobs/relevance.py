"""Role relevance for Automation / QA testing roles."""

from __future__ import annotations

import re

from src.utils.text import normalize_key, normalize_space

QA_SIGNAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Test automation", re.compile(r"\b(test automation|automation testing|automated testing)\b", re.I)),
    ("Selenium", re.compile(r"\bselenium\b", re.I)),
    ("Playwright", re.compile(r"\bplaywright\b", re.I)),
    ("Cypress", re.compile(r"\bcypress\b", re.I)),
    ("API testing", re.compile(r"\b(api testing|rest assured|postman)\b", re.I)),
    ("BDD", re.compile(r"\b(bdd|cucumber|gherkin)\b", re.I)),
    ("PyTest", re.compile(r"\b(pytest|py test)\b", re.I)),
    ("TestNG/JUnit", re.compile(r"\b(testng|junit)\b", re.I)),
    ("CI/CD testing", re.compile(r"\b(ci/?cd|jenkins|github actions)\b", re.I)),
    ("Performance testing", re.compile(r"\b(jmeter|performance testing|load testing)\b", re.I)),
    ("SDET", re.compile(r"\bsdet\b", re.I)),
    ("Quality assurance", re.compile(r"\b(qa engineer|quality assurance|software test)\b", re.I)),
]


def ai_signals(text: str) -> list[str]:
    """JD domain signals (field name kept for shared pipeline models)."""
    found = []
    for name, pattern in QA_SIGNAL_PATTERNS:
        if pattern.search(text or ""):
            found.append(name)
    return found


_QA_TITLE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\bsdet\b",
        r"\bqa[\s/\-]*automation\b",
        r"\bautomation[\s/\-]*test(?:er|ing)?\b",
        r"\btest[\s/\-]*automation\b",
        r"\bsoftware[\s/\-]*test(?:er|ing)?\b",
        r"\bquality[\s/\-]*assurance\b",
        r"\bqa[\s/\-]*engineer\b",
        r"\btest[\s/\-]*engineer\b",
        r"\bautomation[\s/\-]*engineer\b",
        r"\bmanual[\s/\-]*test(?:er|ing)?\b",
        r"\bperformance[\s/\-]*test(?:er|ing)?\b",
        r"\bapi[\s/\-]*test(?:er|ing)?\b",
    )
)


def is_ai_related_job_title(title: str, target_roles: list[str] | None = None) -> bool:
    """True when the title is an Automation / QA / SDET role (shared hook name)."""
    roles = target_roles or []
    if title_score(title, roles) >= 70:
        return True
    blob = normalize_space(title or "").lower()
    if not blob:
        return False
    return any(pattern.search(blob) for pattern in _QA_TITLE_PATTERNS)


def title_score(title: str, target_roles: list[str]) -> float:
    normalized_title = normalize_key(title)
    if not normalized_title:
        return 0.0
    best = 0.0
    title_words = set(normalized_title.split())
    for role in target_roles:
        normalized_role = normalize_key(role)
        if not normalized_role:
            continue
        if normalized_role in normalized_title or normalized_title in normalized_role:
            best = max(best, 100.0)
            continue
        role_words = set(normalized_role.split())
        if role_words and role_words <= title_words:
            best = max(best, 95.0)
            continue
        if role_words:
            overlap = len(role_words & title_words) / len(role_words)
            best = max(best, overlap * 80.0)
    return best


def role_relevance(title: str, description: str, target_roles: list[str]) -> tuple[float, list[str]]:
    """Score 0-100. Generic titles can score higher when the JD is clearly QA/automation."""
    signals = ai_signals(f"{title}\n{description}")
    titled = title_score(title, target_roles)
    signal_score = min(100.0, len(signals) * 22.0)
    if titled >= 90:
        score = 100.0 if signal_score >= 44 or titled == 100 else 92.0
    elif signal_score >= 66:
        score = 88.0
    elif signal_score >= 44:
        score = 74.0
    else:
        score = min(titled, 45.0)
    return score, signals


def domain_for(signals: list[str], text: str) -> str:
    blob = normalize_space(text).lower()
    if "SDET" in signals or "test automation" in blob:
        return "Test Automation"
    if "Performance testing" in signals:
        return "Performance Testing"
    if "API testing" in signals:
        return "API Testing"
    if "BDD" in signals:
        return "BDD / Functional Testing"
    if "Quality assurance" in signals:
        return "Quality Assurance"
    return "Software Testing"
