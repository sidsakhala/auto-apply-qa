"""Search combinations. Primary QA roles and three cities come first."""

from __future__ import annotations

from dataclasses import dataclass

PRIMARY_ROLES = (
    "Automation Test Engineer",
    "QA Automation Engineer",
    "SDET",
    "Software Test Engineer",
)
PRIMARY_LOCATIONS = ("Pune", "Hyderabad", "Bangalore")


@dataclass(frozen=True)
class SearchQuery:
    role: str
    location: str

    @property
    def label(self) -> str:
        return f"{self.role} {self.location}"


def build_search_queries(profile: dict, *, limit: int) -> list[SearchQuery]:
    roles = [str(role).strip() for role in profile.get("target_roles") or [] if str(role).strip()]
    for role in PRIMARY_ROLES:
        if role not in roles:
            roles.insert(0, role)
    ordered_roles = [role for role in PRIMARY_ROLES if role in roles]
    ordered_roles.extend(role for role in roles if role not in ordered_roles)

    queries: list[SearchQuery] = []
    seen: set[tuple[str, str]] = set()

    def add(role: str, location: str) -> None:
        key = (role.lower(), location.lower())
        if key in seen:
            return
        seen.add(key)
        queries.append(SearchQuery(role=role, location=location))

    for role in PRIMARY_ROLES:
        for location in PRIMARY_LOCATIONS:
            add(role, location)
    for role in ordered_roles:
        for location in PRIMARY_LOCATIONS:
            add(role, location)
            if len(queries) >= limit:
                return queries
    return queries[:limit]
