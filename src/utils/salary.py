"""Salary parsing and the candidate's CTC rules.

Amounts are treated as LPA. A disclosed range whose maximum is below the
current CTC is rejected. Undisclosed salary is never an automatic rejection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_RANGE = re.compile(
    r"(?:(?P<cur>₹|rs\.?|inr)\s*)?"
    r"(?P<low>\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*"
    r"(?:₹|rs\.?|inr)?\s*"
    r"(?P<high>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>lpa|lakhs?|lacs?)?",
    re.IGNORECASE,
)
_SINGLE = re.compile(
    r"(?:(?P<cur>₹|rs\.?|inr)\s*)?"
    r"(?P<value>\d+(?:\.\d+)?)\s*\+?\s*"
    r"(?P<unit>lpa|lakhs?|lacs?)",
    re.IGNORECASE,
)
_UNDISCLOSED = re.compile(
    r"not\s+disclosed|unspecified|best in (?:the )?industry|competitive|as per industry",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SalaryInfo:
    text: str
    min_lpa: float | None
    max_lpa: float | None
    disclosed: bool

    @property
    def label(self) -> str:
        if not self.disclosed:
            return "Not Disclosed"
        if self.min_lpa is not None and self.max_lpa is not None and self.min_lpa != self.max_lpa:
            return f"₹{self._fmt(self.min_lpa)}–{self._fmt(self.max_lpa)} LPA"
        value = self.max_lpa if self.max_lpa is not None else self.min_lpa
        return f"₹{self._fmt(value)} LPA" if value is not None else "Not Disclosed"

    @staticmethod
    def _fmt(value: float | None) -> str:
        if value is None:
            return ""
        if float(value).is_integer():
            return str(int(value))
        return str(value)


def parse_salary(text: str | None) -> SalaryInfo:
    raw = (text or "").strip()
    if not raw or _UNDISCLOSED.search(raw):
        return SalaryInfo(text=raw, min_lpa=None, max_lpa=None, disclosed=False)

    match = _RANGE.search(raw)
    if match and (match.group("cur") or match.group("unit")):
        low = float(match.group("low"))
        high = float(match.group("high"))
        if low > high:
            low, high = high, low
        return SalaryInfo(text=raw, min_lpa=low, max_lpa=high, disclosed=True)

    single = _SINGLE.search(raw)
    if single:
        value = float(single.group("value"))
        return SalaryInfo(text=raw, min_lpa=value, max_lpa=value, disclosed=True)

    return SalaryInfo(text=raw, min_lpa=None, max_lpa=None, disclosed=False)


def salary_component(
    info: SalaryInfo,
    *,
    current_ctc_lpa: float,
    minimum_expected_lpa: float,
) -> tuple[float, bool, str]:
    """Return ``(score 0-100, hard_reject, band)``."""
    if not info.disclosed or info.max_lpa is None:
        return 60.0, False, "not_disclosed"

    upper = info.max_lpa
    lower = info.min_lpa if info.min_lpa is not None else upper
    if upper < current_ctc_lpa:
        return 0.0, True, "below_current"
    if lower >= minimum_expected_lpa:
        return 100.0, False, "high"
    if upper >= minimum_expected_lpa:
        return 75.0, False, "consider"
    return 35.0, False, "low"
