"""Errors that callers should handle explicitly."""


class ConfigurationError(RuntimeError):
    """The configuration or local environment is not usable."""


class ResumeIntegrityError(RuntimeError):
    """A tailored resume broke a factual-integrity rule."""


class SecurityChallengeError(RuntimeError):
    """A CAPTCHA or other anti-bot challenge is on screen. Do not bypass it."""


class LoginRequiredError(RuntimeError):
    """Naukri needs an interactive login before applications can continue."""
