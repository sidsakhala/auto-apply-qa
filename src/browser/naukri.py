"""Naukri selectors and HTML parsers.

When Naukri changes its markup, update the selector lists in this file.
The rest of the agent depends on ``JobPosting`` objects, not on page structure.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.browser.browser_manager import needs_login, text_has_challenge
from src.jobs.models import JobPosting
from src.jobs.parser import job_id_from_url

CARD_SELECTORS = (
    "div.cust-job-tuple",
    "div.srp-jobtuple-wrapper",
    "article.jobTuple",
    "div.jobTuple",
    "div[class*='jobTuple']",
    "div[class*='jobtuple']",
)
TITLE_SELECTORS = ("a.title", "a.jobTupleHeader", "a[class*='title']", "a[href*='job-listings']")
COMPANY_SELECTORS = ("a.comp-name", "span.comp-name", "a[class*='comp-name']", ".companyInfo", ".company-name")
LOCATION_SELECTORS = ("span.loc-wrap", "span.locWdth", "span.loc", "span[class*='location']", ".location")
SALARY_SELECTORS = ("span.sal-wrap", "span.sal", "span[class*='salary']", ".salary")
EXPERIENCE_SELECTORS = ("span.exp-wrap", "span.expwdth", "span.exp", "span[class*='experience']")
DESCRIPTION_SELECTORS = (
    "div.styles_JDC__dang-inner-html",
    "div[class*='JDC__dang-inner-html']",
    "section.job-desc",
    "div.job-desc",
    "div#jobDescriptionText",
    "div[class*='job-desc']",
)


def _slug(value: str) -> str:
    text = value.lower().replace("/", " ").replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "jobs"


def search_url(role: str, location: str, page: int = 1, freshness_days: int = 1) -> str:
    """Naukri results URL with the Freshness filter. 1 is Last 1 day (jobAge=1)."""
    slug = f"{_slug(role)}-jobs-in-{_slug(location)}"
    if page > 1:
        slug = f"{slug}-{page}"
    url = f"https://www.naukri.com/{slug}"
    if freshness_days:
        url = f"{url}?jobAge={int(freshness_days)}"
    return url


def _first_text(node, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        found = node.select_one(selector)
        if found:
            return found.get_text(" ", strip=True)
    return ""


def _absolute(href: str) -> str:
    if not href:
        return ""
    return urljoin("https://www.naukri.com", href)


PROFILE_JOB_PAGES = (
    "https://www.naukri.com/mnjuser/recommendedjobs",
    "https://www.naukri.com/mnjuser/homepage",
)


def parse_profile_job_html(html: str) -> list[JobPosting]:
    """Job cards from the logged-in dashboard (profile-based recommendations)."""
    postings = parse_search_html(html)
    if postings:
        return postings
    soup = BeautifulSoup(html or "", "html.parser")
    seen: set[str] = set()
    results: list[JobPosting] = []
    for link in soup.select("a[href*='job-listings']"):
        href = _absolute(link.get("href", ""))
        job_id = job_id_from_url(href)
        if not job_id or job_id in seen:
            continue
        title = link.get_text(" ", strip=True)
        if not title or len(title) < 3:
            continue
        seen.add(job_id)
        card = link
        for _ in range(4):
            if card.parent is None:
                break
            card = card.parent
        results.append(
            JobPosting(
                job_id=job_id,
                title=title,
                company=_first_text(card, COMPANY_SELECTORS),
                location=_first_text(card, LOCATION_SELECTORS),
                salary_text=_first_text(card, SALARY_SELECTORS),
                experience_text=_first_text(card, EXPERIENCE_SELECTORS),
                url=href,
                description=card.get_text("\n", strip=True),
            )
        )
    return results


def parse_search_html(html: str) -> list[JobPosting]:
    soup = BeautifulSoup(html or "", "html.parser")
    cards = []
    seen: set[int] = set()
    kept = []
    for selector in CARD_SELECTORS:
        for card in soup.select(selector):
            if id(card) in seen:
                continue
            if any(id(parent) in seen for parent in card.parents):
                continue
            seen.add(id(card))
            kept.append(card)
    cards = kept
    postings: list[JobPosting] = []
    for card in cards:
        title_node = None
        for selector in TITLE_SELECTORS:
            title_node = card.select_one(selector)
            if title_node:
                break
        title = title_node.get_text(" ", strip=True) if title_node else ""
        href = _absolute(title_node.get("href", "")) if title_node else ""
        description = card.get_text("\n", strip=True)
        postings.append(
            JobPosting(
                job_id=job_id_from_url(href) or job_id_from_url(title),
                title=title,
                company=_first_text(card, COMPANY_SELECTORS),
                location=_first_text(card, LOCATION_SELECTORS),
                salary_text=_first_text(card, SALARY_SELECTORS),
                experience_text=_first_text(card, EXPERIENCE_SELECTORS),
                url=href,
                description=description,
            )
        )
    return [posting for posting in postings if posting.title and posting.job_id]


def _json_ld_description(soup: BeautifulSoup) -> str:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                raw = item.get("description") or ""
                return BeautifulSoup(str(raw), "html.parser").get_text("\n", strip=True)
    return ""


def parse_job_detail_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    embedded = _json_ld_description(soup)
    if embedded:
        return embedded
    for selector in DESCRIPTION_SELECTORS:
        node = soup.select_one(selector)
        if node:
            return node.get_text("\n", strip=True)
    return ""


def page_has_challenge(html: str, url: str) -> bool:
    text = BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)
    return text_has_challenge(text, url)


def page_needs_login(html: str, url: str) -> bool:
    text = BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)
    return needs_login(text, url)
