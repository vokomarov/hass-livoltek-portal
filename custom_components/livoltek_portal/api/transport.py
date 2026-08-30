"""HTTP transport and envelope handling.

Every endpoint returns HTTP 200, including on error, so HTTP status checking is
nearly useless here. All error handling keys off `msg_code`, and a 200 carrying
a failure code must never be mistaken for success.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Final

import aiohttp

from .errors import (
    LivoltekApiError,
    LivoltekAuthError,
    LivoltekCaptchaRequiredError,
    LivoltekConnectionError,
    LivoltekTokenError,
    LivoltekUnknownAccountError,
)

_LOGGER = logging.getLogger(__name__)

SUCCESS_CODES: Final = frozenset({"operate.success", "success"})
_TOKEN_CODES: Final = frozenset({"token.not.set", "token.expired", "token.invalid"})
_CAPTCHA_CODES: Final = frozenset({"err.password.need.verify"})
_UNKNOWN_ACCOUNT_CODES: Final = frozenset(
    {"err.user.not.exist", "err.account.not.exist"}
)
_PASSWORD_CODES: Final = frozenset({"err.password"})

DEFAULT_TIMEOUT_SECONDS: Final = 30


def error_for(msg_code: str, message: str | None = None) -> LivoltekApiError:
    """Map a failure `msg_code` onto the exception that describes it."""
    if msg_code in _CAPTCHA_CODES:
        return LivoltekCaptchaRequiredError(msg_code, message)
    if msg_code in _UNKNOWN_ACCOUNT_CODES:
        return LivoltekUnknownAccountError(msg_code, message)
    if msg_code in _TOKEN_CODES:
        return LivoltekTokenError(msg_code, message)
    if msg_code in _PASSWORD_CODES:
        return LivoltekAuthError(msg_code, message)
    return LivoltekApiError(msg_code, message)


def check_envelope(payload: Any) -> dict[str, Any]:
    """Return the envelope unchanged on success, raise on anything else.

    The whole envelope is returned rather than just `data` because
    `findAllByCustomer` carries a sibling `total` the caller needs.
    """
    if not isinstance(payload, dict):
        raise LivoltekConnectionError(
            f"Expected a JSON object, got {type(payload).__name__}"
        )
    msg_code = payload.get("msg_code") or payload.get("msgCode")
    if not isinstance(msg_code, str):
        raise LivoltekConnectionError("Response carried no msg_code")
    if msg_code in SUCCESS_CODES:
        return payload
    message = payload.get("message")
    raise error_for(msg_code, message if isinstance(message, str) else None)


async def async_request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    json_body: Mapping[str, Any] | None = None,
    params: Mapping[str, Any] | None = None,
    token: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Issue one request and return its checked envelope."""
    headers: dict[str, str] = {"Accept": "application/json"}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with session.request(
            method,
            url,
            json=json_body,
            params=params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout_seconds),
        ) as response:
            # The portal sends text/html content types on some errors, so the
            # parser must not be told to require application/json.
            payload = await response.json(content_type=None)
    except TimeoutError as err:
        raise LivoltekConnectionError(f"Timed out calling {url}") from err
    except aiohttp.ClientError as err:
        raise LivoltekConnectionError(f"Transport error calling {url}: {err}") from err
    except ValueError as err:
        raise LivoltekConnectionError(f"Response from {url} was not JSON") from err

    return check_envelope(payload)
