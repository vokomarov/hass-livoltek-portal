"""Constants for the Livoltek Portal integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "livoltek_portal"
MANUFACTURER: Final = "Livoltek"

# Regional portal hosts. The account only exists on one of them.
REGIONS: Final[dict[str, str]] = {
    "emea": "https://evs.livoltek-portal.com",
    "international": "https://www.livoltek-portal.com",
    "asia": "https://aa.livoltek-portal.com",
}
DEFAULT_REGION: Final = "emea"

ACCOUNT_TYPES: Final[tuple[str, ...]] = ("email", "phone")
DEFAULT_ACCOUNT_TYPE: Final = "email"

CONF_REGION: Final = "region"
CONF_ACCOUNT_TYPE: Final = "account_type"
CONF_LOGIN_ACCOUNT: Final = "login_account"
CONF_PASSWORD_MD5: Final = "password_md5"
CONF_TOKEN: Final = "access_token"
CONF_TOKEN_EXPIRES_AT: Final = "token_expires_at"
CONF_OWNER_ID: Final = "owner_id"
CONF_DEVICES: Final = "devices"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_SCAN_INTERVAL: Final = 120
MIN_SCAN_INTERVAL: Final = 30

# A held value is released to `unavailable` once its last real reading is older
# than max(MIN_HOLD_RELEASE, HOLD_RELEASE_INTERVALS x poll interval).
HOLD_RELEASE_INTERVALS: Final = 10
MIN_HOLD_RELEASE: Final = timedelta(minutes=30)

# The device is stale when its own updateTime is older than
# max(MIN_STALE_WINDOW, STALE_INTERVALS x poll interval). The floor keeps a
# normally-slow inverter from flapping: at a 120 s interval 3x is only 6 min,
# which is inside the portal's own refresh jitter.
STALE_INTERVALS: Final = 3
MIN_STALE_WINDOW: Final = timedelta(minutes=15)

# Fail-open warnings are throttled per payload key.
WARN_THROTTLE: Final = timedelta(hours=1)

ISSUE_CAPTCHA_REQUIRED: Final = "captcha_required"
