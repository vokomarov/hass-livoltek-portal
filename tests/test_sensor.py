"""Every row must declare a unit consistent with its family, and the platform
must publish real values from a recorded payload."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from custom_components.livoltek_portal.api.units import CANONICAL_UNIT, UnitFamily
from custom_components.livoltek_portal.sensor import SENSOR_DESCRIPTIONS

from .test_init import build_entry

# The recorded fixture's `updateTime` is a fixed moment; the coordinator
# compares it against real wall-clock time to decide staleness (see
# entity.available / coordinator.is_stale), so a static fixture eventually
# reads as stale purely from elapsed calendar days -- every entity would show
# `unavailable` instead of the value under test. Every payload used for a
# state-value assertion below is stamped with this fixed, far-future
# `updateTime` so the entities it backs are never stale, and so state values
# that get snapshotted (the `last_reported` sensor) stay deterministic across
# runs regardless of when the suite executes.
_FRESH_UPDATE_TIME = 4070908800000  # 2099-01-01T00:00:00Z, epoch ms


def _fresh(payload: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return {**payload, "updateTime": _FRESH_UPDATE_TIME, **overrides}


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """`pytest_homeassistant_custom_component`'s own `snapshot` fixture is
    supposed to apply this extension globally, but in this environment
    syrupy's plain fixture wins the override and `created_at`/`modified_at`
    leak into the snapshot as non-deterministic timestamps. Applying the
    extension explicitly here is what actually strips them and writes to
    `tests/snapshots/`, matching the brief."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


def test_the_table_has_the_expected_shape() -> None:
    keys = [d.key for d in SENSOR_DESCRIPTIONS]
    assert len(keys) == len(set(keys)), "duplicate entity key"
    api_keys = [d.api_key for d in SENSOR_DESCRIPTIONS]
    assert len(api_keys) == len(set(api_keys)), "duplicate api key"
    assert len(SENSOR_DESCRIPTIONS) == 56
    enabled = [d for d in SENSOR_DESCRIPTIONS if d.entity_registry_enabled_default]
    assert len(enabled) == 38


@pytest.mark.parametrize("description", SENSOR_DESCRIPTIONS, ids=lambda d: d.key)
def test_every_row_declares_its_family_canonical_unit(description) -> None:
    """A row whose declared unit disagrees with its family would publish
    converted numbers under the wrong label."""
    if description.unit_family in (UnitFamily.RAW, None):
        assert description.native_unit_of_measurement is None
        return
    assert (
        description.native_unit_of_measurement
        == CANONICAL_UNIT[description.unit_family]
    )


@pytest.mark.parametrize("description", SENSOR_DESCRIPTIONS, ids=lambda d: d.key)
def test_no_entity_key_carries_the_vendor_typo(description) -> None:
    assert "gird" not in description.key
    assert description.key.islower() or "_" in description.key


def test_the_five_dashboard_rows_exist_and_ship_enabled() -> None:
    """The Energy dashboard is unusable without these; the shape assertions
    live in the two invariants below, which cover every energy row."""
    required = {
        "grid_imported_total",
        "grid_exported_total",
        "pv_energy_total",
        "battery_charged_total",
        "battery_discharged_total",
    }
    rows = {d.key: d for d in SENSOR_DESCRIPTIONS if d.key in required}
    assert set(rows) == required
    for row in rows.values():
        assert row.entity_registry_enabled_default


@pytest.mark.parametrize(
    "description",
    [d for d in SENSOR_DESCRIPTIONS if d.device_class is SensorDeviceClass.ENERGY],
    ids=lambda d: d.key,
)
def test_every_energy_row_is_wired_for_long_term_statistics(description) -> None:
    """HA only records long-term statistics for ENERGY + TOTAL_INCREASING +
    kWh. Miss any one of the three and the Energy dashboard silently drops the
    row, or records it against the wrong scale."""
    assert description.state_class is SensorStateClass.TOTAL_INCREASING
    assert description.native_unit_of_measurement == "kWh"
    assert description.unit_family is UnitFamily.ENERGY


@pytest.mark.parametrize(
    "description",
    [d for d in SENSOR_DESCRIPTIONS if d.key.endswith(("_today", "_total"))],
    ids=lambda d: d.key,
)
def test_every_cumulative_energy_row_declares_the_energy_device_class(
    description,
) -> None:
    """The reverse of the invariant above: a cumulative kWh row that loses its
    device class stops being a statistics candidate, and the test above would
    never see it. Non-energy cumulative rows (runtime) are exempt."""
    if description.unit_family is not UnitFamily.ENERGY:
        return
    assert description.device_class is SensorDeviceClass.ENERGY


@pytest.fixture
def mock_telemetry(telemetry_payload: dict):
    with patch(
        "custom_components.livoltek_portal.api.client.LivoltekClient.async_get_telemetry",
        AsyncMock(return_value=_fresh(telemetry_payload)),
    ) as mocked:
        yield mocked


async def test_all_entities_match_the_snapshot(
    hass: HomeAssistant,
    mock_telemetry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    entry = build_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    for entity in sorted(entities, key=lambda e: e.entity_id):
        assert entity == snapshot(name=f"{entity.entity_id}-entry")
        assert hass.states.get(entity.entity_id) == snapshot(
            name=f"{entity.entity_id}-state"
        )


async def test_battery_soc_reads_from_battery_rest_soc(
    hass: HomeAssistant, mock_telemetry, telemetry_payload: dict
) -> None:
    """`batterySOC` is null in recorded payloads; `batteryRestSoc` carries it."""
    assert telemetry_payload.get("batterySOC") is None
    entry = build_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.hyper_6000_battery_soc")
    assert state is not None
    assert float(state.state) == float(telemetry_payload["batteryRestSoc"])


async def test_an_mwh_total_is_normalised_to_kwh(
    hass: HomeAssistant, telemetry_payload: dict
) -> None:
    """The server rescales per field. Without normalisation a unit flip at the
    1000 boundary writes a 1000x jump into long-term statistics."""
    payload = _fresh(
        telemetry_payload,
        girdImportedTotal="2.08",
        girdImportedTotalUnit="MWh",
    )
    entry = build_entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.livoltek_portal.api.client.LivoltekClient.async_get_telemetry",
        AsyncMock(return_value=payload),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.hyper_6000_grid_imported_total")
    assert float(state.state) == pytest.approx(2080.0)


async def test_a_held_value_keeps_the_last_good_reading(
    hass: HomeAssistant, telemetry_payload: dict
) -> None:
    good = _fresh(telemetry_payload, batteryRestSoc="61", batteryRestSocUnit="%")
    bad = _fresh(telemetry_payload, batteryRestSoc=None)
    entry = build_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.livoltek_portal.api.client.LivoltekClient.async_get_telemetry",
        AsyncMock(side_effect=[good, bad]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entity_id = "sensor.hyper_6000_battery_soc"
        assert hass.states.get(entity_id).state == "61.0"

        await entry.runtime_data.coordinators[12345].async_refresh()
        await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "61.0"


async def test_a_zero_reading_updates_and_is_never_held(
    hass: HomeAssistant, telemetry_payload: dict
) -> None:
    first = _fresh(telemetry_payload, pvPower="1.5", pvPowerUnit="kW")
    second = _fresh(telemetry_payload, pvPower="0", pvPowerUnit="kW")
    entry = build_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.livoltek_portal.api.client.LivoltekClient.async_get_telemetry",
        AsyncMock(side_effect=[first, second]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entity_id = "sensor.hyper_6000_pv_power"
        assert float(hass.states.get(entity_id).state) == 1.5

        await entry.runtime_data.coordinators[12345].async_refresh()
        await hass.async_block_till_done()

    assert float(hass.states.get(entity_id).state) == 0.0


async def test_a_key_absent_from_every_payload_reports_unknown_not_unavailable(
    hass: HomeAssistant, telemetry_payload: dict
) -> None:
    payload = _fresh({k: v for k, v in telemetry_payload.items() if k != "epsEnergy"})
    entry = build_entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.livoltek_portal.api.client.LivoltekClient.async_get_telemetry",
        AsyncMock(return_value=payload),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.hyper_6000_backup_energy_total")
    assert state.state == STATE_UNKNOWN
    assert state.state != STATE_UNAVAILABLE


async def test_update_time_becomes_an_aware_datetime(
    hass: HomeAssistant, mock_telemetry
) -> None:
    entry = build_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.hyper_6000_last_reported")
    assert state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
    assert state.state.endswith("+00:00")


@pytest.mark.parametrize(
    "description",
    [d for d in SENSOR_DESCRIPTIONS if d.unit_family is UnitFamily.RAW],
    ids=lambda d: d.key,
)
def test_raw_rows_never_reach_home_assistant_as_floats(description) -> None:
    """RAW rows are integer counts and status flags, but every numeric field is
    parsed through float(). Without a value_fn the tri-state battery_status
    publishes as "-1.0", and the obvious automation -- comparing the state to
    "-1" -- is then silently always False. Failing quietly is the whole reason
    this is a test and not a comment."""
    assert description.value_fn is not None, (
        f"{description.key} is RAW with no value_fn, so it will publish 1 as '1.0'"
    )
    assert not isinstance(description.value_fn(-1.0), float)


@pytest.mark.parametrize(
    "description",
    [d for d in SENSOR_DESCRIPTIONS if d.device_class is SensorDeviceClass.ENUM],
    ids=lambda d: d.key,
)
def test_every_enum_row_only_ever_produces_a_declared_option(description) -> None:
    """Home Assistant raises on a state outside `options`, so a value the
    mapping does not model has to become None -- `unknown` -- rather than pass
    through. A firmware that invents a fourth status code must not take the
    entity down."""
    assert description.options
    assert description.value_fn is not None
    for raw in (-2, 2, 99, None, "", "weird"):
        assert description.value_fn(raw) is None, f"{raw!r} leaked through"
    for raw in (-1, 0, 1, "1", -1.0):
        assert description.value_fn(raw) in description.options


def test_battery_status_names_the_direction_probe_03_observed() -> None:
    """The mapping itself, not just its shape: -1/0/+1 tracked the sign of
    batteryActivePower in all six captures."""
    row = next(d for d in SENSOR_DESCRIPTIONS if d.key == "battery_status")
    assert [row.value_fn(flag) for flag in (1, 0, -1)] == [
        "charging",
        "idle",
        "discharging",
    ]
