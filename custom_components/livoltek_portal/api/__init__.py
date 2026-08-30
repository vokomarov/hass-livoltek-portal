"""Transport-level client for the Livoltek portal API.

Nothing in this package may import from `homeassistant`; it is unit-testable
standalone.
"""

from __future__ import annotations

from .auth import LivoltekAuth, decode_token_expiry, hash_password
from .client import LivoltekClient
from .errors import (
    LivoltekApiError,
    LivoltekAuthError,
    LivoltekCaptchaRequiredError,
    LivoltekConnectionError,
    LivoltekError,
    LivoltekTokenError,
    LivoltekUnknownAccountError,
)
from .models import DeviceRef, Session
from .units import (
    CANONICAL_UNIT,
    Extracted,
    UnitFamily,
    extract_numeric,
    extract_text,
)

__all__ = [
    "CANONICAL_UNIT",
    "DeviceRef",
    "Extracted",
    "LivoltekApiError",
    "LivoltekAuth",
    "LivoltekAuthError",
    "LivoltekCaptchaRequiredError",
    "LivoltekClient",
    "LivoltekConnectionError",
    "LivoltekError",
    "LivoltekTokenError",
    "LivoltekUnknownAccountError",
    "Session",
    "UnitFamily",
    "decode_token_expiry",
    "extract_numeric",
    "extract_text",
    "hash_password",
]
