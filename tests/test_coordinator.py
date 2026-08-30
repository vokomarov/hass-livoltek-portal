"""The fail-open merge is what keeps a null-heavy payload from flapping every
entity to unknown. Roughly 640 of the ~700 fields in a recorded payload are
null, so the hold, the throttle, and the release valve all carry weight."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun import freeze_time
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.livoltek_portal.api import DeviceRef, UnitFamily
from custom_components.livoltek_portal.api.errors import (
    LivoltekApiError,
    LivoltekCaptchaRequiredError,
    LivoltekConnectionError,
    LivoltekTokenError,
)
from custom_components.livoltek_portal.const import DOMAIN
from custom_components.livoltek_portal.coordinator import LivoltekDeviceCoordinator

DEVICE = DeviceRef(
    device_id=12345,
    inverter_sn="HP1XXXXHSC1XXXXX",
    name="HP1XXXXHSC1XXXXX(Hyper-6000)",
    product_type_name="Hyper-6000",
    template=44,
    power_station_name="Home",
)

FIELDS: dict[str, UnitFamily | None] = {
    "pvPower": UnitFamily.POWER,
    "batteryRestSoc": UnitFamily.PERCENTAGE,
    "girdImportedTotal": UnitFamily.ENERGY,
    "armVersion": None,
}


def payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "pvPower": "1.5",
        "pvPowerUnit": "kW",
        "batteryRestSoc": "95",
        "batteryRestSocUnit": "%",
        "girdImportedTotal": "2.08",
        "girdImportedTotalUnit": "MWh",
        "armVersion": "V1.1.2",
        "updateTime": int(datetime.now(UTC).timestamp() * 1000),
    }
    base.update(overrides)
    return base


def build(hass: HomeAssistant, scan_interval: int = 120) -> LivoltekDeviceCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="e1")
    entry.add_to_hass(hass)
    client = MagicMock()
    client.async_get_telemetry = AsyncMock(return_value=payload())
    coordinator = LivoltekDeviceCoordinator(hass, entry, client, DEVICE, scan_interval)
    coordinator.register_fields(FIELDS)
    return coordinator


async def test_first_refresh_populates_every_registered_field(
    hass: HomeAssistant,
) -> None:
    coordinator = build(hass)
    await coordinator.async_refresh()

    assert coordinator.value_for("pvPower") == 1.5
    assert coordinator.value_for("batteryRestSoc") == 95.0
    assert coordinator.value_for("girdImportedTotal") == 2080.0  # MWh -> kWh
    assert coordinator.value_for("armVersion") == "V1.1.2"


async def test_zero_updates_rather_than_holding(hass: HomeAssistant) -> None:
    """pvPower is "0" every night. Holding would leave PV elevated after sunset
    and corrupt the Energy dashboard while appearing to work."""
    coordinator = build(hass)
    await coordinator.async_refresh()
    assert coordinator.value_for("pvPower") == 1.5

    coordinator.client.async_get_telemetry.return_value = payload(pvPower="0")
    await coordinator.async_refresh()
    assert coordinator.value_for("pvPower") == 0.0


async def test_null_holds_the_previous_value_and_warns(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    coordinator = build(hass)
    await coordinator.async_refresh()

    coordinator.client.async_get_telemetry.return_value = payload(pvPower=None)
    caplog.clear()
    await coordinator.async_refresh()

    assert coordinator.value_for("pvPower") == 1.5
    assert "pvPower" in caplog.text
    assert "absent" in caplog.text


async def test_the_inverter_serial_never_reaches_a_log_record(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """The hold-and-warn path fires on nearly every cycle (most payload fields
    are null), so it is a routine, high-frequency place for a secret to leak.
    `device_id` identifies the device in logs; `inverter_sn` must not appear
    there, even though it is the identity used in the entity/device registry."""
    with caplog.at_level("WARNING"):
        coordinator = build(hass)
        await coordinator.async_refresh()

        coordinator.client.async_get_telemetry.return_value = payload(pvPower=None)
        caplog.clear()
        await coordinator.async_refresh()

    assert DEVICE.inverter_sn not in caplog.text


async def test_an_unparseable_value_holds_and_warns(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    coordinator = build(hass)
    await coordinator.async_refresh()

    coordinator.client.async_get_telemetry.return_value = payload(pvPower="n/a!")
    caplog.clear()
    await coordinator.async_refresh()

    assert coordinator.value_for("pvPower") == 1.5
    assert "unparseable" in caplog.text


async def test_an_unknown_unit_holds_rather_than_publishing_a_wrong_magnitude(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    coordinator = build(hass)
    await coordinator.async_refresh()

    coordinator.client.async_get_telemetry.return_value = payload(pvPowerUnit="GW")
    caplog.clear()
    await coordinator.async_refresh()

    assert coordinator.value_for("pvPower") == 1.5
    assert "unknown_unit" in caplog.text


async def test_unregistered_keys_never_warn(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """~640 of ~700 payload fields are null; logging them all would emit
    hundreds of thousands of lines a day."""
    coordinator = build(hass)
    coordinator.client.async_get_telemetry.return_value = payload(
        **{f"unused{i}": None for i in range(50)}
    )
    caplog.clear()
    await coordinator.async_refresh()
    assert "unused0" not in caplog.text


async def test_warnings_are_throttled_to_once_per_key_per_hour(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    with freeze_time("2026-08-28 10:00:00") as frozen:
        coordinator = build(hass)
        await coordinator.async_refresh()
        coordinator.client.async_get_telemetry.return_value = payload(pvPower=None)

        caplog.clear()
        await coordinator.async_refresh()
        assert caplog.text.count("pvPower") == 1

        frozen.tick(timedelta(minutes=30))
        caplog.clear()
        await coordinator.async_refresh()
        assert "pvPower" not in caplog.text

        frozen.tick(timedelta(minutes=31))
        caplog.clear()
        await coordinator.async_refresh()
        assert caplog.text.count("pvPower") == 1


async def test_the_release_valve_frees_a_value_held_too_long(
    hass: HomeAssistant,
) -> None:
    """Without this, a dead inverter would display confident, plausible,
    hours-old numbers indefinitely."""
    with freeze_time("2026-08-28 10:00:00") as frozen:
        coordinator = build(hass, scan_interval=120)
        await coordinator.async_refresh()
        assert coordinator.hold_window == timedelta(minutes=30)

        coordinator.client.async_get_telemetry.return_value = payload(pvPower=None)
        frozen.tick(timedelta(minutes=29))
        await coordinator.async_refresh()
        assert coordinator.value_for("pvPower") == 1.5
        assert coordinator.is_value_available("pvPower") is True

        frozen.tick(timedelta(minutes=2))
        assert coordinator.value_for("pvPower") is None
        assert coordinator.is_value_available("pvPower") is False


async def test_the_hold_window_scales_with_a_long_poll_interval(
    hass: HomeAssistant,
) -> None:
    coordinator = build(hass, scan_interval=600)
    assert coordinator.hold_window == timedelta(minutes=100)


async def test_staleness_uses_the_device_report_time(hass: HomeAssistant) -> None:
    with freeze_time("2026-08-28 10:00:00") as frozen:
        coordinator = build(hass, scan_interval=120)
        await coordinator.async_refresh()
        assert coordinator.is_stale is False

        frozen.tick(timedelta(minutes=14))
        assert coordinator.is_stale is False

        frozen.tick(timedelta(minutes=2))
        assert coordinator.is_stale is True


async def test_a_payload_without_update_time_is_never_stale(
    hass: HomeAssistant,
) -> None:
    """Inventing staleness from a missing timestamp would take entities
    unavailable for the wrong reason."""
    coordinator = build(hass)
    coordinator.client.async_get_telemetry.return_value = payload(updateTime=None)
    await coordinator.async_refresh()
    assert coordinator.is_stale is False


async def test_a_token_error_raises_config_entry_auth_failed(
    hass: HomeAssistant,
) -> None:
    coordinator = build(hass)
    coordinator.client.async_get_telemetry.side_effect = LivoltekTokenError(
        "token.expired"
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_a_captcha_lockout_raises_a_repair_issue(hass: HomeAssistant) -> None:
    """A silently failing 30-day re-login is a failure the user would otherwise
    notice days late."""
    coordinator = build(hass)
    coordinator.client.async_get_telemetry.side_effect = LivoltekCaptchaRequiredError(
        "err.password.need.verify"
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, "captcha_required_e1") is not None


@pytest.mark.parametrize(
    "error",
    [LivoltekApiError("service_error"), LivoltekConnectionError("boom")],
)
async def test_transport_and_api_errors_raise_update_failed(
    hass: HomeAssistant, error: Exception
) -> None:
    coordinator = build(hass)
    coordinator.client.async_get_telemetry.side_effect = error
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_registering_fields_after_the_first_refresh_backfills_them(
    hass: HomeAssistant,
) -> None:
    """Platforms register their keys after the entry's first refresh, so the
    merge must run for newly registered fields against the payload in hand."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="e2")
    entry.add_to_hass(hass)
    client = MagicMock()
    client.async_get_telemetry = AsyncMock(return_value=payload())
    coordinator = LivoltekDeviceCoordinator(hass, entry, client, DEVICE, 120)

    await coordinator.async_refresh()
    assert coordinator.value_for("pvPower") is None

    coordinator.register_fields(FIELDS)
    assert coordinator.value_for("pvPower") == 1.5


async def test_held_keys_lists_only_the_fields_the_portal_stopped_sending(
    hass: HomeAssistant,
) -> None:
    coordinator = build(hass)
    await coordinator.async_refresh()
    assert coordinator.held_keys == set()

    coordinator.client.async_get_telemetry = AsyncMock(
        return_value=payload(pvPower=None)
    )
    await coordinator.async_refresh()

    assert coordinator.held_keys == {"pvPower"}
    # Still readable: holding is the point.
    assert coordinator.value_for("pvPower") == 1.5


async def test_a_recovered_field_leaves_held_keys(hass: HomeAssistant) -> None:
    coordinator = build(hass)
    await coordinator.async_refresh()
    coordinator.client.async_get_telemetry = AsyncMock(
        return_value=payload(pvPower=None)
    )
    await coordinator.async_refresh()
    coordinator.client.async_get_telemetry = AsyncMock(
        return_value=payload(pvPower="0")
    )
    await coordinator.async_refresh()

    assert coordinator.held_keys == set()
    assert coordinator.value_for("pvPower") == 0.0
