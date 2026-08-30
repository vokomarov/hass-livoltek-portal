"""Online reflects the inverter, not the cloud connection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant

from .test_init import build_entry

ENTITY_ID = "binary_sensor.hyper_6000_online"


def _payload_at(telemetry_payload: dict, when: datetime) -> dict:
    return {**telemetry_payload, "updateTime": int(when.timestamp() * 1000)}


async def test_a_fresh_payload_reports_online(
    hass: HomeAssistant, telemetry_payload: dict
) -> None:
    entry = build_entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.livoltek_portal.api.client.LivoltekClient.async_get_telemetry",
        AsyncMock(return_value=_payload_at(telemetry_payload, datetime.now(UTC))),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_ON


async def test_a_stale_payload_reports_offline_while_staying_available(
    hass: HomeAssistant, telemetry_payload: dict
) -> None:
    old = datetime.now(UTC) - timedelta(hours=6)
    entry = build_entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.livoltek_portal.api.client.LivoltekClient.async_get_telemetry",
        AsyncMock(return_value=_payload_at(telemetry_payload, old)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_OFF
    # The numeric sensors go unavailable; this one must not, or nothing is left
    # to say the inverter is offline.
    assert (
        hass.states.get("sensor.hyper_6000_battery_soc").state
        == STATE_UNAVAILABLE
    )


async def test_a_failing_cloud_call_makes_it_unavailable(
    hass: HomeAssistant, telemetry_payload: dict
) -> None:
    from custom_components.livoltek_portal.api import LivoltekConnectionError

    entry = build_entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.livoltek_portal.api.client.LivoltekClient.async_get_telemetry",
        AsyncMock(
            side_effect=[
                _payload_at(telemetry_payload, datetime.now(UTC)),
                LivoltekConnectionError("down"),
            ]
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get(ENTITY_ID).state == STATE_ON

        await entry.runtime_data.coordinators[12345].async_refresh()
        await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE


async def test_a_payload_without_a_timestamp_is_treated_as_online(
    hass: HomeAssistant, telemetry_payload: dict
) -> None:
    """No timestamp means staleness is unknowable; claiming offline would be a
    false alarm on any model that omits updateTime."""
    payload = {k: v for k, v in telemetry_payload.items() if k != "updateTime"}
    entry = build_entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.livoltek_portal.api.client.LivoltekClient.async_get_telemetry",
        AsyncMock(return_value=payload),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_ON
