"""Entry setup wires one coordinator per selected device and persists the token
so a Home Assistant restart reuses the existing 30-day session."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.livoltek_portal.const import (
    CONF_ACCOUNT_TYPE,
    CONF_DEVICES,
    CONF_LOGIN_ACCOUNT,
    CONF_OWNER_ID,
    CONF_PASSWORD_MD5,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DOMAIN,
)

from .test_api_auth import make_token

DEVICE_OPTION = {
    "device_id": 12345,
    "inverter_sn": "HP1XXXXHSC1XXXXX",
    "name": "HP1XXXXHSC1XXXXX(Hyper-6000)",
    "product_type_name": "Hyper-6000",
    "template": 44,
    "power_station_name": "Home",
    "display_name": None,
}


def build_entry(**data_overrides) -> MockConfigEntry:
    expires = datetime.now(UTC) + timedelta(days=30)
    data = {
        CONF_REGION: "emea",
        CONF_LOGIN_ACCOUNT: "user@example.com",
        CONF_PASSWORD_MD5: "5f4dcc3b5aa765d61d8327deb882cf99",
        CONF_ACCOUNT_TYPE: "email",
        CONF_TOKEN: make_token(expires),
        CONF_TOKEN_EXPIRES_AT: expires.isoformat(),
        CONF_OWNER_ID: "9001",
    }
    data.update(data_overrides)
    return MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        unique_id="9001",
        data=data,
        options={CONF_DEVICES: [DEVICE_OPTION], CONF_SCAN_INTERVAL: 120},
    )


@pytest.fixture
def mock_telemetry(telemetry_payload: dict):
    """Patched at the transport, not at `async_get_telemetry`.

    `auth.async_get_token()` — the only thing that can rotate a token during
    setup — is called from `_async_authed_request`. Patching either
    `async_get_telemetry` or `_async_authed_request` skips it, and the
    token-write-back test then passes without exercising the path it is named
    for. Patching the transport leaves the whole client and auth chain real.
    """
    with patch(
        "custom_components.livoltek_portal.api.client.async_request",
        AsyncMock(
            return_value={"data": telemetry_payload, "msg_code": "operate.success"}
        ),
    ) as mocked:
        yield mocked


async def test_setup_creates_one_coordinator_per_selected_device(
    hass: HomeAssistant, mock_telemetry
) -> None:
    entry = build_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert set(entry.runtime_data.coordinators) == {12345}


async def test_setup_reuses_a_stored_token_without_logging_in(
    hass: HomeAssistant, mock_telemetry
) -> None:
    """The token lives 30 days. A restart must not consume a fresh session."""
    entry = build_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.livoltek_portal.api.auth.LivoltekAuth.async_login",
        AsyncMock(),
    ) as login:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    login.assert_not_called()


async def test_a_refreshed_token_is_written_back_to_the_entry(
    hass: HomeAssistant, mock_telemetry
) -> None:
    expired = datetime.now(UTC) - timedelta(days=1)
    entry = build_entry(
        **{CONF_TOKEN: make_token(expired), CONF_TOKEN_EXPIRES_AT: expired.isoformat()}
    )
    entry.add_to_hass(hass)
    fresh_expiry = datetime.now(UTC) + timedelta(days=30)
    fresh = make_token(fresh_expiry)

    async def fake_login(self, **kwargs):
        from custom_components.livoltek_portal.api.models import Session

        self._token = fresh
        self._expires_at = fresh_expiry
        return Session(fresh, fresh_expiry, "9001")

    with patch(
        "custom_components.livoltek_portal.api.auth.LivoltekAuth.async_login",
        fake_login,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.data[CONF_TOKEN] == fresh
    assert entry.data[CONF_TOKEN_EXPIRES_AT] == fresh_expiry.isoformat()


async def test_a_token_rotated_on_a_second_device_is_written_back(
    hass: HomeAssistant, mock_telemetry
) -> None:
    """All coordinators share one client, so any of them can be the poll that
    rotates the token. Listening on only the first would leave a rotation seen
    by device 2 unwritten until device 1 next refreshed -- up to a full scan
    interval later, and lost entirely if HA restarted in that window."""
    # A distinct serial as well as a distinct id: entity unique_ids are built
    # from the serial, so reusing it collides every entity on the second device.
    second = {
        **DEVICE_OPTION,
        "device_id": 12346,
        "inverter_sn": "HP2XXXXHSC2XXXXX",
        "name": "HP2XXXXHSC2XXXXX(Hyper-6000)",
    }
    entry = build_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry,
        options={CONF_DEVICES: [DEVICE_OPTION, second], CONF_SCAN_INTERVAL: 120},
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert set(entry.runtime_data.coordinators) == {12345, 12346}

    # A different expiry than build_entry's, so the token bytes actually
    # differ -- make_token is deterministic in its expiry.
    rotated_expiry = datetime.now(UTC) + timedelta(days=29)
    rotated = make_token(rotated_expiry)
    assert entry.data[CONF_TOKEN] != rotated

    auth = entry.runtime_data.client.auth
    auth._token = rotated
    auth._expires_at = rotated_expiry

    # Only the second device polls. The first is left untouched on purpose:
    # if its listener is the one doing the write, this assertion still passes
    # for the wrong reason.
    await entry.runtime_data.coordinators[12346].async_refresh()
    await hass.async_block_till_done()

    assert entry.data[CONF_TOKEN] == rotated


async def test_setup_fails_when_no_devices_are_selected(hass: HomeAssistant) -> None:
    entry = build_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={CONF_DEVICES: [], CONF_SCAN_INTERVAL: 120}
    )

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_unload_tears_everything_down(
    hass: HomeAssistant, mock_telemetry
) -> None:
    entry = build_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_changing_options_reloads_the_entry(
    hass: HomeAssistant, mock_telemetry
) -> None:
    entry = build_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(
        entry, options={CONF_DEVICES: [DEVICE_OPTION], CONF_SCAN_INTERVAL: 300}
    )
    await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinators[12345]
    assert coordinator.update_interval == timedelta(seconds=300)


async def test_writing_the_token_back_does_not_trigger_a_reload_loop(
    hass: HomeAssistant, mock_telemetry
) -> None:
    """async_update_entry fires the update listener; only an options change may
    reload, or a monthly token write would recurse."""
    entry = build_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    runtime_before = entry.runtime_data

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_TOKEN: "a-different-token"}
    )
    await hass.async_block_till_done()

    assert entry.runtime_data is runtime_before
