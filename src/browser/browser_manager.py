"""Playwright lifecycle. CAPTCHA frames stop automation; they are never solved."""

from __future__ import annotations

import os
from pathlib import Path

from src.exceptions import SecurityChallengeError
from src.utils.config import BrowserSettings

VISIBLE_CHALLENGES = (
    "verify you are human",
    "verify that you are a human",
    "are you a robot",
    "i'm not a robot",
    "im not a robot",
    "unusual traffic",
    "complete the security check",
    "security check",
    "you don't have permission to access",
    "you don’t have permission to access",
    "errors.edgesuite.net",
    "edgesuite.net",
)


def text_has_challenge(text: str, url: str = "") -> bool:
    lowered = (text or "").lower()
    if any(phrase in lowered for phrase in VISIBLE_CHALLENGES):
        return True
    url_lower = (url or "").lower()
    return "captcha" in url_lower or "/challenge" in url_lower


def needs_login(text: str, url: str) -> bool:
    url_lower = (url or "").lower()
    if "nlogin" in url_lower or "/login" in url_lower:
        return True
    lowered = (text or "").lower()
    return "login to apply" in lowered or "register to apply" in lowered


class BrowserManager:
    """Persistent Chromium profile so a manual login survives later runs."""

    def __init__(self, settings: BrowserSettings, root: Path) -> None:
        self.settings = settings
        self.profile_dir = root / settings.user_data_dir
        self._playwright = None
        self.context = None
        self.page = None

    def __enter__(self) -> "BrowserManager":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def start(self) -> None:
        from playwright.sync_api import sync_playwright

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        args = ["--ozone-platform=x11"] if os.environ.get("NAUKRI_FORCE_X11") == "1" else []
        self.context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=self.settings.headless,
            slow_mo=self.settings.slow_mo_ms,
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
            args=args,
            env=os.environ.copy(),
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.set_default_timeout(self.settings.navigation_timeout_ms)

    def stop(self) -> None:
        if self.context is not None:
            self.context.close()
            self.context = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        self.page = None

    def has_challenge(self) -> bool:
        if self.page is None:
            return False
        try:
            text = self.page.inner_text("body")
        except Exception:
            text = ""
        if text_has_challenge(text, self.page.url):
            return True
        for frame in self.page.frames:
            url = (frame.url or "").lower()
            if not any(token in url for token in ("recaptcha", "hcaptcha", "captcha")):
                continue
            try:
                box = frame.frame_element().bounding_box()
            except Exception:
                return True
            if box and box.get("height", 0) > 40 and box.get("width", 0) > 40:
                return True
        return False

    def goto(self, url: str) -> None:
        if self.page is None:
            raise RuntimeError("Browser is not started")
        self.page.goto(url, wait_until="domcontentloaded")
        if self.has_challenge():
            raise SecurityChallengeError(
                "Naukri showed a security check or an Access Denied block. "
                "Solve it yourself in the browser window, then run the search again. "
                "This agent will not bypass it."
            )

    def wait_for_results(self, timeout_ms: int = 12000) -> bool:
        """Wait until job cards render. Return False when the page has no cards."""
        if self.page is None:
            return False
        if self.has_challenge():
            raise SecurityChallengeError(
                "Naukri showed a security check or an Access Denied block. "
                "Solve it yourself in the browser window, then run the search again. "
                "This agent will not bypass it."
            )
        try:
            self.page.wait_for_selector(
                "div.srp-jobtuple-wrapper, div.cust-job-tuple, article.jobTuple, a.title",
                timeout=timeout_ms,
            )
        except Exception:
            return False
        return not self.has_challenge()

    def content(self) -> str:
        if self.page is None:
            return ""
        return self.page.content()

    def body_text(self) -> str:
        if self.page is None:
            return ""
        try:
            return self.page.inner_text("body")
        except Exception:
            return ""
