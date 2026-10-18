"""Location scoring against the candidate's city priority."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.utils.text import normalize_space

_CITY_ALIASES = {
    "pune": "pune",
    "hyderabad": "hyderabad",
    "bangalore": "bangalore",
    "bengaluru": "bangalore",
    "remote": "remote",
    "work from home": "remote",
    "wfh": "remote",
    "hybrid": "hybrid",
}

_PRIORITY_SCORE = {
    "pune": 100.0,
    "hyderabad": 92.0,
    "bangalore": 86.0,
}


@dataclass(frozen=True)
class LocationDecision:
    score: float
    allowed: bool
    reason: str
    matched: str


def _tokens(location: str) -> set[str]:
    text = normalize_space(location).lower()
    found: set[str] = set()
    for alias, canonical in _CITY_ALIASES.items():
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", text):
            found.add(canonical)
    return found


def preferred_keys(locations: list[str]) -> list[str]:
    keys: list[str] = []
    for location in locations:
        for token in _tokens(location):
            if token not in {"remote", "hybrid"} and token not in keys:
                keys.append(token)
    return keys


def evaluate_location(
    location: str,
    preferred: list[str],
    *,
    role_relevance: float,
    consider_remote_or_hybrid: bool,
) -> LocationDecision:
    tokens = _tokens(location)
    preferred_set = set(preferred_keys(preferred))
    cities = tokens & {"pune", "hyderabad", "bangalore"}
    matched_preferred = [city for city in ("pune", "hyderabad", "bangalore") if city in cities and city in preferred_set]

    if matched_preferred:
        best = matched_preferred[0]
        return LocationDecision(_PRIORITY_SCORE[best], True, "preferred_city", best)

    # A preferred city written in a way the alias map already handled is above.
    # Any other recognized preferred city string still counts.
    if cities & preferred_set:
        best = sorted(cities & preferred_set, key=lambda city: -_PRIORITY_SCORE[city])[0]
        return LocationDecision(_PRIORITY_SCORE[best], True, "preferred_city", best)

    remoteish = bool(tokens & {"remote", "hybrid"})
    if remoteish and consider_remote_or_hybrid:
        if role_relevance >= 75:
            kind = "remote" if "remote" in tokens else "hybrid"
            return LocationDecision(78.0, True, "remote_or_hybrid_relevant", kind)
        return LocationDecision(45.0, False, "remote_or_hybrid_weak_role", "remote")

    if not normalize_space(location):
        return LocationDecision(60.0, True, "location_undisclosed", "")

    if not cities and not remoteish:
        # Could still mention a preferred city that failed tokenization; already checked.
        return LocationDecision(15.0, False, "location_not_preferred", "")

    return LocationDecision(15.0, False, "location_not_preferred", "")
