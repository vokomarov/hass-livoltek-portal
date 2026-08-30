"""Exception hierarchy for the Livoltek portal API.

Every upstream response is HTTP 200, including errors, so the failure signal is
the envelope's `msg_code`. These types carry it so callers can branch without
re-parsing strings.
"""

from __future__ import annotations


class LivoltekError(Exception):
    """Base class for every error this package raises."""


class LivoltekConnectionError(LivoltekError):
    """Transport failure, timeout, or a response that is not a valid envelope."""


class LivoltekApiError(LivoltekError):
    """The envelope reported a failure `msg_code`."""

    def __init__(self, msg_code: str, message: str | None = None) -> None:
        super().__init__(message or msg_code)
        self.msg_code = msg_code
        self.message = message


class LivoltekAuthError(LivoltekApiError):
    """The credentials were rejected. Retrying without new input loops."""


class LivoltekTokenError(LivoltekAuthError):
    """The token is missing, expired, or invalid. Re-login and retry once."""


class LivoltekCaptchaRequiredError(LivoltekAuthError):
    """Login is locked to a captcha after repeated failures."""


class LivoltekUnknownAccountError(LivoltekAuthError):
    """The account does not exist *on this regional host*."""
