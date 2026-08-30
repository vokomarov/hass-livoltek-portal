"""The Livoltek Portal integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DeviceRef, LivoltekAuth, LivoltekClient
from .const import (
    CONF_ACCOUNT_TYPE,
    CONF_DEVICES,
    CONF_LOGIN_ACCOUNT,
    CONF_OWNER_ID,
    CONF_PASSWORD_MD5,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DEFAULT_ACCOUNT_TYPE,
    DEFAULT_REGION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    REGIONS,
)
from .coordinator import LivoltekDeviceCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

# Seconds between each additional device's first poll, so N inverters do not
# fire simultaneously on setup or after a restart.
STAGGER_SECONDS = 5


@dataclass
class LivoltekRuntimeData:
    """Everything a loaded entry owns."""

    client: LivoltekClient
    coordinators: dict[int, LivoltekDeviceCoordinator] = field(default_factory=dict)
    options_snapshot: dict[str, Any] = field(default_factory=dict)


type LivoltekConfigEntry = ConfigEntry[LivoltekRuntimeData]


def build_client(hass: HomeAssistant, entry: LivoltekConfigEntry) -> LivoltekClient:
    """Build a client from the entry's stored credentials and token."""
    base_url = REGIONS.get(entry.data.get(CONF_REGION, DEFAULT_REGION))
    if base_url is None:
        raise ConfigEntryError(f"Unknown region {entry.data.get(CONF_REGION)!r}")

    expires_at: datetime | None = None
    stored_expiry = entry.data.get(CONF_TOKEN_EXPIRES_AT)
    if isinstance(stored_expiry, str):
        try:
            expires_at = datetime.fromisoformat(stored_expiry)
        except ValueError:
            expires_at = None

    auth = LivoltekAuth(
        async_get_clientsession(hass),
        base_url,
        entry.data[CONF_LOGIN_ACCOUNT],
        entry.data[CONF_PASSWORD_MD5],
        account_type=entry.data.get(CONF_ACCOUNT_TYPE, DEFAULT_ACCOUNT_TYPE),
        token=entry.data.get(CONF_TOKEN),
        expires_at=expires_at,
        owner_id=entry.data.get(CONF_OWNER_ID),
    )
    return LivoltekClient(async_get_clientsession(hass), base_url, auth)


async def async_setup_entry(hass: HomeAssistant, entry: LivoltekConfigEntry) -> bool:
    """Set up one Livoltek account."""
    devices = [
        DeviceRef.from_dict(raw) for raw in entry.options.get(CONF_DEVICES, []) or []
    ]
    if not devices:
        raise ConfigEntryError(
            "No devices are selected. Reconfigure the integration and pick at "
            "least one device."
        )

    client = build_client(hass, entry)
    scan_interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))

    runtime = LivoltekRuntimeData(client=client, options_snapshot=dict(entry.options))
    entry.runtime_data = runtime

    for device in devices:
        runtime.coordinators[device.device_id] = LivoltekDeviceCoordinator(
            hass, entry, client, device, scan_interval
        )

    ordered = list(runtime.coordinators.values())

    # Registered BEFORE the first refresh, not after: the refresh itself can
    # rotate the token (the stored one is stale, or the server rejects it and
    # the client re-logs in mid-request), and a listener added afterwards is
    # not in `_listeners` when the refresh's async_update_listeners() fires,
    # so that new token is never written back.
    # Every coordinator, not just the first: they share one client and so one
    # token, and any of them can be the poll that rotates it. Listening on only
    # the first leaves a rotation by device 2 unwritten until device 1 next
    # refreshes. `_persist_token` is idempotent and skips the write when the
    # stored token already matches, so the extra listeners cost nothing.
    for coordinator in ordered:
        entry.async_on_unload(
            coordinator.async_add_listener(
                lambda: _persist_token(hass, entry, client.auth)
            )
        )
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

    # The first device's refresh runs inline so setup fails fast on a bad token
    # or an unreachable host. The rest are staggered in the background.
    await ordered[0].async_config_entry_first_refresh()
    for index, coordinator in enumerate(ordered[1:], start=1):
        entry.async_create_background_task(
            hass,
            _async_staggered_first_refresh(coordinator, index * STAGGER_SECONDS),
            # device_id, never inverter_sn: task names surface in HA's debug
            # log and in traces, and the serial is a secret.
            name=f"{DOMAIN}-first-refresh-{coordinator.device.device_id}",
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LivoltekConfigEntry) -> bool:
    """Unload an account.

    `POST /nbp/logout` is deliberately not called: unloading is not a sign-out,
    Home Assistant reloads entries routinely, and discarding a valid 30-day
    token on every reload would force a fresh login each time.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_staggered_first_refresh(
    coordinator: LivoltekDeviceCoordinator, delay: int
) -> None:
    await asyncio.sleep(delay)
    await coordinator.async_refresh()


@callback
def _persist_token(
    hass: HomeAssistant, entry: LivoltekConfigEntry, auth: LivoltekAuth
) -> None:
    """Write a re-issued token back so a restart reuses the 30-day session."""
    token = auth.token
    if not token or token == entry.data.get(CONF_TOKEN):
        return
    expires_at = auth.expires_at.isoformat() if auth.expires_at else None
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_TOKEN: token,
            CONF_TOKEN_EXPIRES_AT: expires_at,
            CONF_OWNER_ID: auth.owner_id or entry.data.get(CONF_OWNER_ID),
        },
    )


async def _async_entry_updated(hass: HomeAssistant, entry: LivoltekConfigEntry) -> None:
    """Reload only when the *options* changed.

    `async_update_entry` fires this listener for data writes too, and the token
    is written back roughly once a month. Reloading on that would recurse.
    """
    runtime = getattr(entry, "runtime_data", None)
    if runtime is not None and runtime.options_snapshot == dict(entry.options):
        return
    await hass.config_entries.async_reload(entry.entry_id)
