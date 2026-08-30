"""One polling coordinator per selected device, with a fail-open merge.

The upstream payload carries roughly 700 keys and about 640 of them are null on
any given cycle. Rather than flapping entities to `unknown`, the coordinator
holds the last real reading per key and warns — throttled, and only for keys
that actually back an entity. A held value is released to `unavailable` once it
is too old to be believable.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import DeviceRef, LivoltekClient, UnitFamily, extract_numeric, extract_text
from .api.errors import (
    LivoltekApiError,
    LivoltekAuthError,
    LivoltekCaptchaRequiredError,
    LivoltekConnectionError,
)
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    HOLD_RELEASE_INTERVALS,
    ISSUE_CAPTCHA_REQUIRED,
    MIN_HOLD_RELEASE,
    MIN_STALE_WINDOW,
    STALE_INTERVALS,
    WARN_THROTTLE,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class HeldValue:
    """The last real reading for one payload key, and when it arrived."""

    value: float | str | None
    updated_at: datetime


class LivoltekDeviceCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls one inverter and maintains its held-value store."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: LivoltekClient,
        device: DeviceRef,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            # device_id, not inverter_sn: HA's own coordinator logs `name` on
            # every transient failure, and the serial must never reach a log.
            name=f"{DOMAIN} {device.device_id}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.device = device
        self.raw: dict[str, Any] = {}
        self._fields: dict[str, UnitFamily | None] = {}
        self._held: dict[str, HeldValue] = {}
        # Keys whose value came from the most recent merge. Everything in
        # _held that is not in here is currently being held open.
        self._fresh: set[str] = set()
        self._last_warned: dict[str, datetime] = {}

    # -- registration ----------------------------------------------------

    def register_fields(self, fields: Mapping[str, UnitFamily | None]) -> None:
        """Declare which payload keys back entities.

        Platforms call this during their own setup, which happens after the
        entry's first refresh, so the newly registered keys are merged against
        the payload already in hand.
        """
        new = {key: family for key, family in fields.items() if key not in self._fields}
        self._fields.update(new)
        if new and self.raw:
            self._merge(self.raw, new)

    # -- reading ---------------------------------------------------------

    def value_for(self, key: str) -> float | str | None:
        """The last real reading, or None once the release valve has fired."""
        held = self._held.get(key)
        if held is None or not self._within_hold_window(held):
            return None
        return held.value

    def is_value_available(self, key: str) -> bool:
        """False when this key has no reading, or one too old to believe."""
        held = self._held.get(key)
        return held is not None and self._within_hold_window(held)

    @property
    def hold_window(self) -> timedelta:
        """How long a held value stays believable."""
        return max(MIN_HOLD_RELEASE, self._interval * HOLD_RELEASE_INTERVALS)

    @property
    def held_keys(self) -> set[str]:
        """Registered keys serving a held value rather than a fresh one.

        The fastest way to see which fields the portal stopped sending.
        """
        return set(self._held) - self._fresh

    @property
    def payload_updated_at(self) -> datetime | None:
        """The device's own report time, from `updateTime` (epoch ms)."""
        raw = self.raw.get("updateTime")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        try:
            return dt_util.utc_from_timestamp(float(raw) / 1000.0)
        except (OverflowError, OSError, ValueError):
            return None

    @property
    def is_stale(self) -> bool:
        """True when the cloud has data but the inverter stopped reporting.

        `status`, `pcsStatus` and `workStatus` are deliberately not used: their
        value semantics are unverified, and guessing them would take entities
        unavailable for the wrong reasons.
        """
        updated = self.payload_updated_at
        if updated is None:
            return False
        window = max(MIN_STALE_WINDOW, self._interval * STALE_INTERVALS)
        return dt_util.utcnow() - updated > window

    # -- polling ---------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            payload = await self.client.async_get_telemetry(self.device)
        except LivoltekCaptchaRequiredError as err:
            self._raise_captcha_issue()
            raise ConfigEntryAuthFailed(
                "Livoltek requires a captcha to log in again"
            ) from err
        except LivoltekAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (LivoltekApiError, LivoltekConnectionError) as err:
            raise UpdateFailed(str(err)) from err

        self.raw = payload
        self._merge(payload, self._fields)
        return payload

    # -- internals -------------------------------------------------------

    @property
    def _interval(self) -> timedelta:
        return self.update_interval or timedelta(seconds=DEFAULT_SCAN_INTERVAL)

    def _within_hold_window(self, held: HeldValue) -> bool:
        return dt_util.utcnow() - held.updated_at <= self.hold_window

    def _merge(
        self, payload: Mapping[str, Any], fields: Mapping[str, UnitFamily | None]
    ) -> None:
        """Merge fresh readings over the held store, one key at a time."""
        now = dt_util.utcnow()
        for key, family in fields.items():
            extracted = (
                extract_text(payload, key)
                if family is None
                else extract_numeric(payload, key, family)
            )
            if extracted.ok:
                self._held[key] = HeldValue(extracted.value, now)
                self._fresh.add(key)
                continue
            self._fresh.discard(key)
            self._warn(key, extracted.problem, payload.get(key), now)

    def _warn(self, key: str, problem: str | None, raw: Any, now: datetime) -> None:
        last = self._last_warned.get(key)
        if last is not None and now - last < WARN_THROTTLE:
            return
        self._last_warned[key] = now
        # device_id, not inverter_sn: this fires on every null field, which is
        # most fields on most cycles, so the serial must never reach a log.
        _LOGGER.warning(
            "device %s: field '%s' is %s (received %r); keeping the previous value",
            self.device.device_id,
            key,
            problem,
            raw,
        )

    def _raise_captcha_issue(self) -> None:
        assert self.config_entry is not None
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{ISSUE_CAPTCHA_REQUIRED}_{self.config_entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_CAPTCHA_REQUIRED,
            translation_placeholders={"account": self.config_entry.title},
        )
