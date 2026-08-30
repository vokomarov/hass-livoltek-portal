"""Credentials, the cached token, and its decoded expiry.

There is no refresh endpoint. Both recorded JWTs decode to exactly 30 days, the
reconstructed path catalog contains no refresh or renew route, and the Session
schema carries no refresh_token. "Refresh" therefore means logging in again with
the stored credentials, which is safe: tokens issued 17 minutes apart carried
different tokenId values, so the server permits concurrent sessions.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import aiohttp

from .errors import LivoltekConnectionError
from .models import Session
from .transport import async_request

_LOGGER = logging.getLogger(__name__)

LOGIN_PATH: Final = "/nbp/login/customer"

# Re-login this far ahead of the 30-day expiry, so a poll never races it.
TOKEN_REFRESH_MARGIN: Final = timedelta(days=3)

# Used only when a freshly issued token's `exp` cannot be decoded. Assuming it
# is already expired would re-login on every poll; assuming 30 days would risk
# silent failure. Half a day re-logins twice daily at worst.
FALLBACK_TOKEN_TTL: Final = timedelta(hours=12)

_DEVICE_NAME: Final = "Home Assistant"
# Integer device kind, and it must be 0. A string such as "phone" makes the
# portal treat the login as phone-based and reject an email account with
# login.phone.account.number.oversize.
_DEVICE_TYPE: Final = 0


def hash_password(plaintext: str) -> str:
    """Lowercase MD5 hex, as the wire protocol expects.

    Unsalted and uniterated. The resulting digest is password-equivalent: it is
    the only credential the API needs. See the README's security note.
    """
    return hashlib.md5(plaintext.encode("utf-8"), usedforsecurity=False).hexdigest()


def decode_token_expiry(token: str) -> datetime | None:
    """Read a JWT's `exp` claim, or None if it cannot be read.

    The signature is deliberately **not** verified: the integration is not the
    token's audience and holds no key. The claim is used only to schedule
    re-login, so a forged expiry would cost at most one extra login.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    segment = parts[1]
    try:
        raw = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
        claims = json.loads(raw)
        exp = claims["exp"]
    except (ValueError, KeyError, TypeError):
        return None
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(exp, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _now() -> datetime:
    return datetime.now(UTC)


class LivoltekAuth:
    """Owns the credentials and the cached session token."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        login_account: str,
        password_md5: str,
        account_type: str = "email",
        token: str | None = None,
        expires_at: datetime | None = None,
        owner_id: str | None = None,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._login_account = login_account
        self._password_md5 = password_md5
        self._account_type = account_type
        self._token = token
        self._expires_at = expires_at
        self._owner_id = owner_id
        self._lock = asyncio.Lock()

    @property
    def token(self) -> str | None:
        return self._token

    @property
    def expires_at(self) -> datetime | None:
        return self._expires_at

    @property
    def owner_id(self) -> str | None:
        return self._owner_id

    def invalidate(self) -> None:
        """Drop the cached token so the next call logs in again."""
        self._token = None
        self._expires_at = None

    def _is_stale(self) -> bool:
        if self._token is None or self._expires_at is None:
            return True
        return _now() >= self._expires_at - TOKEN_REFRESH_MARGIN

    async def async_get_token(self) -> str:
        """Return a usable token, logging in first if the cached one is stale.

        The lock makes N concurrent device coordinators produce one login.
        """
        token = self._token
        if token is not None and not self._is_stale():
            return token
        async with self._lock:
            # Re-check: a concurrent caller may have logged in while we waited.
            token = self._token
            if token is not None and not self._is_stale():
                return token
            session = await self.async_login()
            return session.access_token

    async def async_login(
        self, *, image_id: str | None = None, image_code: str | None = None
    ) -> Session:
        """Log in and cache the resulting token."""
        body: dict[str, Any] = {
            "language": "en",
            "login_account": self._login_account,
            "password": self._password_md5,
            # The wire protocol misspells this; reproduce it verbatim.
            "acctount_type": self._account_type,
            "device_name": _DEVICE_NAME,
            "device_type": _DEVICE_TYPE,
        }
        if image_id and image_code:
            body["image_id"] = image_id
            body["image_code"] = image_code

        envelope = await async_request(
            self._session, "POST", f"{self._base_url}{LOGIN_PATH}", json_body=body
        )
        data = envelope.get("data")
        if not isinstance(data, dict) or not data.get("access_token"):
            raise LivoltekConnectionError("Login response carried no access_token")

        token = str(data["access_token"])
        expires_at = decode_token_expiry(token)
        if expires_at is None:
            _LOGGER.debug(
                "Could not decode the token expiry; assuming %s", FALLBACK_TOKEN_TTL
            )
            expires_at = _now() + FALLBACK_TOKEN_TTL

        owner = data.get("owner")
        owner_id = (
            str(owner["id"])
            if isinstance(owner, dict) and owner.get("id") is not None
            else None
        )

        self._token = token
        self._expires_at = expires_at
        self._owner_id = owner_id
        return Session(access_token=token, expires_at=expires_at, owner_id=owner_id)
