"""Sign in to Naukri with the account in the environment.

A CAPTCHA or one-time code stops automation. Those checks are never solved here.
"""

from __future__ import annotations

import os

from src.browser.browser_manager import text_has_challenge
from src.exceptions import SecurityChallengeError
from src.utils.logger import get_logger

logger = get_logger("login")

LOGIN_URL = "https://www.naukri.com/nlogin/login"
_EMAIL_FIELDS = (
    "#usernameField",
    "input[placeholder*='Email' i]",
    "input[placeholder*='Username' i]",
    "input[type='email']",
    "input[name='username']",
)
_PASSWORD_FIELDS = ("#passwordField", "input[type='password']")
_SUBMIT_BUTTONS = (
    "button:has-text('Login')",
    "button:has-text('Sign in')",
    "button[type='submit']",
)
_PASSWORD_STEP = (
    "button:has-text('Use password')",
    "button:has-text('Login with password')",
    "a:has-text('Use password')",
    "a:has-text('Login with password')",
)


def credentials() -> tuple[str, str]:
    email = (os.environ.get("NAUKRI_EMAIL") or "").strip()
    password = os.environ.get("NAUKRI_PASSWORD") or ""
    return email, password


def ensure_naukri_login(page, *, email: str, password: str) -> str:
    """Open the login page and submit the account when Naukri asks for it.

    Returns ``already`` when the saved browser session is still signed in,
    or ``submitted`` after the login form is sent. Raises when a security
    check appears or the account details are missing.
    """
    if not email or not password:
        raise SecurityChallengeError(
            "Naukri email and password are missing. Add NAUKRI_EMAIL and NAUKRI_PASSWORD to .env."
        )
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if text_has_challenge(_body(page), page.url):
        raise SecurityChallengeError(
            "Naukri showed a security check on the login page. Solve it in the browser. This agent will not bypass it."
        )
    if _wait_until_signed_in(page, 8000):
        logger.info("Naukri session is already signed in")
        return "already"

    email_box = _wait_for_visible(page, _EMAIL_FIELDS, 8000)
    password_box = _first_visible(page, _PASSWORD_FIELDS)
    if email_box is not None:
        email_box.fill(email)
        logger.info("Filled the Naukri email field")
    if password_box is None:
        reveal = _first_visible(page, _PASSWORD_STEP)
        if reveal is not None:
            reveal.click()
        elif email_box is not None:
            _click_submit(page)
        password_box = _wait_for_visible(page, _PASSWORD_FIELDS, 8000)
    if password_box is None:
        if _already_signed_in(page):
            logger.info("Naukri session is already signed in")
            return "already"
        if text_has_challenge(_body(page), page.url) or _asks_for_otp(page):
            raise SecurityChallengeError(
                "Naukri asked for a CAPTCHA or a one-time code. Complete it in the browser, then run again."
            )
        raise SecurityChallengeError("Naukri did not show a password field. Sign in once in the browser window.")
    password_box.fill(password)
    logger.info("Filled the Naukri password field")
    _click_submit(page)
    page.wait_for_timeout(2000)
    if text_has_challenge(_body(page), page.url) or _asks_for_otp(page):
        raise SecurityChallengeError(
            "Naukri asked for a CAPTCHA or a one-time code. Complete it in the browser, then run again."
        )
    if _already_signed_in(page):
        logger.info("Signed in to Naukri")
        return "submitted"
    raise SecurityChallengeError("Naukri login did not complete. Check the browser window and sign in there.")


def _body(page) -> str:
    try:
        return page.inner_text("body")
    except Exception:
        return ""


def _wait_until_signed_in(page, timeout_ms: int) -> bool:
    waited = 0
    while waited <= timeout_ms:
        if _already_signed_in(page):
            return True
        page.wait_for_timeout(400)
        waited += 400
    return False


def _already_signed_in(page) -> bool:
    url = (page.url or "").lower()
    if "nlogin" in url or url.rstrip("/").endswith("/login"):
        return False
    if "/mnjuser/" in url:
        return True
    text = _body(page).lower()
    if "enter password" in text or "enter email" in text:
        return False
    return any(token in text for token in ("logout", "my naukri", "update profile", "view profile"))


def _asks_for_otp(page) -> bool:
    text = _body(page).lower()
    return "otp" in text or "one time password" in text or "one-time password" in text


def _wait_for_visible(page, selectors: tuple[str, ...], timeout_ms: int):
    waited = 0
    while waited <= timeout_ms:
        found = _first_visible(page, selectors)
        if found is not None:
            return found
        page.wait_for_timeout(400)
        waited += 400
    return None


def _first_visible(page, selectors: tuple[str, ...]):
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(min(locator.count(), 5)):
            item = locator.nth(index)
            try:
                if item.is_visible():
                    return item
            except Exception:
                continue
    return None


def _click_submit(page) -> None:
    button = _first_visible(page, _SUBMIT_BUTTONS)
    if button is None:
        raise SecurityChallengeError("Naukri login button was not found.")
    button.click()
