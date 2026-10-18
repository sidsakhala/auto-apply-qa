"""Experience-range parsing and fit against the candidate's years."""

from __future__ import annotations

import re
from dataclasses import dataclass

_RANGE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs|yr)\b",
    re.IGNORECASE,
)
_RANGE_TO = re.compile(
    r"(\d+(?:\.\d+)?)\s*[-–—]?\s*to\s*[-–—]?\s*(\d+(?:\.\d+)?)\s*[-–—]?\s*(?:years|yrs|yr)\b",
    re.IGNORECASE,
)
_BELOW = re.compile(
    r"(?:below|under|less than|up to)\s*(\d+(?:\.\d+)?)\s*(?:years|yrs|yr)\b",
    re.IGNORECASE,
)
_PLUS = re.compile(r"(\d+(?:\.\d+)?)\s*\+\s*(?:years|yrs|yr)\b", re.IGNORECASE)
_MINIMUM = re.compile(
    r"(?:minimum|min\.?|at least)\s*(\d+(?:\.\d+)?)\s*(?:years|yrs|yr)\b",
    re.IGNORECASE,
)
_YEARS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:years|yrs|yr)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ExperienceRange:
    text: str
    minimum: float | None
    maximum: float | None

    @property
    def disclosed(self) -> bool:
        return self.minimum is not None or self.maximum is not None


def parse_experience(text: str | None) -> ExperienceRange:
    raw = (text or "").strip()
    if not raw:
        return ExperienceRange(text="", minimum=None, maximum=None)
    match = _RANGE.search(raw) or _RANGE_TO.search(raw)
    if match:
        low = float(match.group(1))
        high = float(match.group(2))
        if low > high:
            low, high = high, low
        return ExperienceRange(text=raw, minimum=low, maximum=high)
    below = _BELOW.search(raw)
    if below:
        return ExperienceRange(text=raw, minimum=0.0, maximum=float(below.group(1)))
    plus = _PLUS.search(raw)
    if plus:
        low = float(plus.group(1))
        return ExperienceRange(text=raw, minimum=low, maximum=None)
    minimum = _MINIMUM.search(raw)
    if minimum:
        low = float(minimum.group(1))
        return ExperienceRange(text=raw, minimum=low, maximum=None)
    years = _YEARS.search(raw)
    if years:
        value = float(years.group(1))
        return ExperienceRange(text=raw, minimum=value, maximum=value)
    return ExperienceRange(text=raw, minimum=None, maximum=None)


def strictest_experience(*texts: str) -> ExperienceRange:
    """Use the highest disclosed range. A Naukri URL such as 4-to-8-years wins over a vague JD."""
    chosen = ExperienceRange(text="", minimum=None, maximum=None)
    for text in texts:
        parsed = parse_experience(text)
        if not parsed.disclosed:
            continue
        if not chosen.disclosed or _upper(parsed) > _upper(chosen):
            chosen = parsed
    return chosen


def _upper(required: ExperienceRange) -> float:
    if required.maximum is not None:
        return required.maximum
    if required.minimum is not None:
        return required.minimum
    return -1.0


def experience_component(
    required: ExperienceRange,
    *,
    candidate_min: float,
    candidate_max: float,
    maximum_years: float = 8,
    minimum_years: float = 2,
) -> tuple[float, bool, str]:
    """Return ``(score 0-100, hard_reject, reason)``.

    Job experience must overlap the candidate band from ``candidate_profile.yaml``.
    Rejects postings below ``minimum_years`` or whose minimum is above ``maximum_years``.
    A range such as 3–8 years stays when its minimum is within the cap.
    """
    if not required.disclosed:
        return 70.0, False, "experience_undisclosed"

    req_min = required.minimum if required.minimum is not None else 0.0
    req_max = required.maximum if required.maximum is not None else req_min
    if required.maximum is None and required.minimum is not None:
        req_max = req_min

    if req_min > maximum_years:
        return 0.0, True, "experience_too_high"
    if req_max + 1e-9 < minimum_years and req_min + 1e-9 < minimum_years:
        return 0.0, True, "experience_too_low"

    band_max = min(req_max, maximum_years)
    overlap = min(candidate_max, band_max) - max(candidate_min, req_min)
    if overlap >= 0:
        if candidate_min >= req_min and candidate_max <= max(req_max, req_min):
            return 100.0, False, "within_range"
        return 85.0, False, "overlaps"

    gap = req_min - candidate_max
    if gap <= 1:
        return 55.0, False, "one_year_stretch"
    if req_max + 1e-9 < candidate_min - 1:
        return 0.0, True, "experience_too_low"
    if req_min > candidate_max + 2:
        return 0.0, True, "experience_too_high"
    return 35.0, False, "stretch"
