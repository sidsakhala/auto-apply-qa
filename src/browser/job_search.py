"""Search Naukri and open job pages. A security challenge stops the search."""

from __future__ import annotations

import random
import time

from src.browser.browser_manager import BrowserManager
from src.browser.naukri import (
    PROFILE_JOB_PAGES,
    parse_job_detail_html,
    parse_profile_job_html,
    parse_search_html,
    search_url,
)
from src.exceptions import SecurityChallengeError
from src.jobs.experience import experience_component, strictest_experience
from src.jobs.models import JobPosting
from src.jobs.search import SearchQuery
from src.utils.config import SearchSettings
from src.utils.logger import get_logger

logger = get_logger("search")


class NaukriSearch:
    def __init__(
        self,
        browser: BrowserManager,
        settings: SearchSettings,
        *,
        profile: dict | None = None,
        sleeper=time.sleep,
    ) -> None:
        self.browser = browser
        self.settings = settings
        self.profile = profile or {}
        self.sleeper = sleeper

    def collect(self, queries: list[SearchQuery]) -> list[JobPosting]:
        found: list[JobPosting] = []
        seen: set[str] = set()
        try:
            if self.settings.profile_jobs_enabled:
                self._collect_profile_jobs(found, seen)
            for query in queries:
                if self._reached_cap(found):
                    break
                for page in range(1, self.settings.max_pages + 1):
                    url = search_url(
                        query.role,
                        query.location,
                        page,
                        self.settings.freshness_days,
                    )
                    logger.info("Searching %s", url)
                    self.browser.goto(url)
                    self.browser.wait_for_results()
                    cards = parse_search_html(self.browser.content())
                    title = self.browser.page.title() if self.browser.page is not None else ""
                    logger.info(
                        "Query '%s' page %s returned %s cards (page title: %s)",
                        query.label,
                        page,
                        len(cards),
                        title,
                    )
                    self._pause()
                    self._ingest_cards(cards, found, seen)
        except SecurityChallengeError as exc:
            exc.found = found  # type: ignore[attr-defined]
            raise
        return found

    def _collect_profile_jobs(self, found: list[JobPosting], seen: set[str]) -> None:
        limit = self.settings.max_profile_jobs
        for page_url in PROFILE_JOB_PAGES:
            if self._reached_cap(found) or limit <= 0:
                return
            logger.info("Loading profile-based jobs from %s", page_url)
            self.browser.goto(page_url)
            self._wait_for_profile_jobs()
            self._scroll_profile_feed()
            cards = parse_profile_job_html(self.browser.content())
            logger.info("Profile page returned %s job cards", len(cards))
            self._pause()
            before = len(found)
            self._ingest_cards(cards, found, seen, max_add=limit)
            limit -= len(found) - before
            if limit <= 0:
                return

    def _wait_for_profile_jobs(self) -> None:
        page = self.browser.page
        if page is None:
            return
        if self.browser.has_challenge():
            raise SecurityChallengeError("Security challenge on Naukri profile jobs page.")
        for selector in (
            "div.srp-jobtuple-wrapper",
            "div.cust-job-tuple",
            "article.jobTuple",
            "a[href*='job-listings']",
        ):
            try:
                page.wait_for_selector(selector, timeout=12000)
                return
            except Exception:
                continue

    def _scroll_profile_feed(self) -> None:
        page = self.browser.page
        if page is None:
            return
        try:
            for _ in range(3):
                page.evaluate("window.scrollBy(0, Math.min(window.innerHeight * 2, 1800))")
                page.wait_for_timeout(800)
        except Exception:
            return

    def _ingest_cards(
        self,
        cards: list[JobPosting],
        found: list[JobPosting],
        seen: set[str],
        *,
        max_add: int | None = None,
    ) -> None:
        added = 0
        per_query_cap = self.settings.max_jobs_per_query
        for card in cards:
            if max_add is not None and added >= max_add:
                return
            if card.job_id in seen or not card.url:
                continue
            if not self._experience_allowed(card):
                logger.info(
                    "Skipped (experience): %s at %s [%s]",
                    card.title,
                    card.company,
                    card.experience_text or card.url,
                )
                continue
            seen.add(card.job_id)
            if self._reached_cap(found):
                return
            found.append(self._with_description(card))
            added += 1
            self._pause()
            if max_add is None and added >= per_query_cap:
                break

    def _experience_allowed(self, card: JobPosting) -> bool:
        """Drop profile/search cards whose experience band is above the candidate cap."""
        candidate = self.profile.get("candidate") or {}
        required = strictest_experience(card.experience_text, card.url)
        if not required.disclosed:
            return True
        _score, hard_reject, _reason = experience_component(
            required,
            candidate_min=float(candidate.get("experience_min_years", 2)),
            candidate_max=float(candidate.get("experience_max_years", 8)),
            maximum_years=float(candidate.get("maximum_job_experience_years", 8)),
            minimum_years=float(candidate.get("minimum_job_experience_years", 2)),
        )
        return not hard_reject

    def _reached_cap(self, found: list[JobPosting]) -> bool:
        cap = self.settings.max_new_jobs_per_run
        return cap > 0 and len(found) >= cap

    def _with_description(self, card: JobPosting) -> JobPosting:
        self.browser.goto(card.url)
        detail = parse_job_detail_html(self.browser.content())
        if detail:
            card.description = detail
        return card

    def _pause(self) -> None:
        delay = random.uniform(self.settings.min_delay_seconds, self.settings.max_delay_seconds)
        self.sleeper(delay)
