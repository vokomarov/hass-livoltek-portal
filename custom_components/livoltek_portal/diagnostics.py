"""Config entry diagnostics.

Users paste these into public issue trackers, so anything that identifies the
account, the hardware, or the session is redacted before it leaves the instance.
The telemetry payload itself is kept: it is the only reason the dump is useful.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import (
    CONF_LOGIN_ACCOUNT,
    CONF_OWNER_ID,
    CONF_PASSWORD_MD5,
    CONF_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
)

# The MD5 digest is password-equivalent: the portal accepts it verbatim.
TO_REDACT_DATA = {
    CONF_LOGIN_ACCOUNT,
    CONF_PASSWORD_MD5,
    CONF_TOKEN,
    CONF_OWNER_ID,
    "password",
}

# Serials identify the installation and appear in warranty and support records.
TO_REDACT_DEVICE = {"inverter_sn", "name", "power_station_name"}

TO_REDACT_TELEMETRY = {
    "inverterSn",
    "wifiSn",
    "battery1Sn",
    "battery2Sn",
    "battery3Sn",
    "battery4Sn",
    "battery5Sn",
    "sn",
    "deviceSn",
    "cabinetSn",
    "collectorSn",
    "hemsSn",
    "meterSn",
    # The payload's own "name" field carries the inverter serial, not a
    # friendly label -- see DeviceRef.from_payload's `name or serial` default.
    "name",
    "powerStationName",
    # The telemetry payload names the site and pins it to a country and a city.
    # `powerStationName` above is the device-list endpoint's spelling; the
    # realtime payload uses `stationName`, and only that one is ever present
    # here. The three timezone fields are not offsets -- they carry a city name
    # ("Springfield"), and `registrationTimezone` / `updateTimeZone` prefix it with
    # a timestamp. Together these locate the owner's home.
    "stationName",
    "stationId",
    "countryName",
    "timezone",
    "registrationTimezone",
    "updateTimeZone",
    "userName",
    "email",
    "phone",
    "address",
    "latitude",
    "longitude",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry
) -> dict[str, Any]:
    """Return redacted diagnostics for one account."""
    runtime = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT_DATA),
            # Kept unredacted: an ISO timestamp reveals nothing and is the first
            # thing to check when polling silently stops.
            "token_expires_at": entry.data.get(CONF_TOKEN_EXPIRES_AT),
            "options": {
                "scan_interval": entry.options.get("scan_interval"),
                "device_count": len(entry.options.get("devices", [])),
            },
        },
        "devices": [
            {
                "device": async_redact_data(
                    coordinator.device.as_dict(), TO_REDACT_DEVICE
                ),
                "last_update_success": coordinator.last_update_success,
                "is_stale": coordinator.is_stale,
                "payload_updated_at": (
                    coordinator.payload_updated_at.isoformat()
                    if coordinator.payload_updated_at
                    else None
                ),
                "held_keys": sorted(coordinator.held_keys),
                "telemetry": async_redact_data(coordinator.raw, TO_REDACT_TELEMETRY),
            }
            for coordinator in runtime.coordinators.values()
        ],
    }
