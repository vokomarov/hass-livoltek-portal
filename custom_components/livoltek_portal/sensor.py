"""Sensor platform.

Every sensor is one row in SENSOR_DESCRIPTIONS plus one generic entity class.
`key` is the stable snake_case identifier that lands in the entity id; `api_key`
is the portal's own spelling, including its `gird` typo for "grid".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfReactivePower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api.units import UnitFamily
from .coordinator import LivoltekDeviceCoordinator
from .entity import LivoltekEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LivoltekSensorEntityDescription(SensorEntityDescription):
    """One telemetry field mapped onto one Home Assistant sensor."""

    api_key: str
    # None means the field is text (version strings, serials) and is read with
    # extract_text. UnitFamily.RAW means numeric but never rescaled. Anything
    # else is numeric and converted to that family's canonical unit. This
    # mirrors the coordinator's `family is None` branch exactly -- getting it
    # backwards turns "V1.10" into a permanent `unparseable` warning.
    unit_family: UnitFamily | None = None
    value_fn: Callable[[Any], Any] | None = None


BATTERY_DIRECTIONS = ("charging", "idle", "discharging")

# batteryStatus is a tri-state direction flag, not an opaque vendor code: its
# value equalled the sign of batteryActivePower in all six probe-03 captures.
# That is why this one field is an enum while pcsStatus and workStatus are not
# -- those never varied across any live state, so there is nothing to name.
_BATTERY_DIRECTION_BY_FLAG = {-1: "discharging", 0: "idle", 1: "charging"}


def _battery_direction(value: Any) -> str | None:
    """Map the tri-state flag to an option name, or None if it is not one.

    Returning None (Home Assistant shows `unknown`) rather than passing an
    unmodelled value straight through is what keeps a firmware that invents a
    fourth state from raising, because HA rejects a state outside `options`.
    """
    try:
        return _BATTERY_DIRECTION_BY_FLAG.get(int(value))
    except (TypeError, ValueError):
        return None


def _epoch_ms_to_datetime(value: Any) -> datetime | None:
    """`updateTime` is epoch milliseconds in the portal's own clock."""
    try:
        millis = int(float(value))
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    return datetime.fromtimestamp(millis / 1000, tz=UTC)


def _battery_flow_power(value: Any) -> float | None:
    """Re-sign batteryActivePower for the Energy dashboard's power flow.

    The portal reports battery power positive while charging; Home Assistant's
    power-flow view is house-centric and wants positive while discharging. So
    negate it -- folding -0.0 back to 0.0 so idle never renders as "-0.0".
    """
    try:
        flipped = -float(value)
    except (TypeError, ValueError):
        return None
    return flipped or 0.0


_MEASURE = SensorStateClass.MEASUREMENT
_TOTAL = SensorStateClass.TOTAL_INCREASING
_DIAG = EntityCategory.DIAGNOSTIC


_PRIMARY: tuple[LivoltekSensorEntityDescription, ...] = (
    # --- Battery -----------------------------------------------------------
    LivoltekSensorEntityDescription(
        key="battery_soc",
        api_key="batteryRestSoc",
        name="Battery SoC",
        unit_family=UnitFamily.PERCENTAGE,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=_MEASURE,
        suggested_display_precision=0,
    ),
    # Signed, and published as the portal reports it: POSITIVE CHARGING,
    # NEGATIVE DISCHARGING (probe 03, six captures; batteryCurrent agrees).
    # Deliberately not flipped: this row matches the vendor's own app. Home
    # Assistant enforces no sign convention on a standalone battery-power
    # entity and shipped integrations split both ways. The Energy dashboard's
    # cumulative bars read battery_charged_total / battery_discharged_total, but
    # its live power-flow view (HA 2025.12+) reads an instantaneous sensor and
    # expects the house-centric sign (positive = discharging) --
    # battery_power_energy_dashboard below carries that flipped sign for the
    # flow, while this row stays vendor-faithful.
    LivoltekSensorEntityDescription(
        key="battery_power",
        api_key="batteryActivePower",
        name="Battery power",
        unit_family=UnitFamily.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=_MEASURE,
        suggested_display_precision=3,
    ),
    # The same batteryActivePower field, re-signed for the Energy dashboard's
    # power-flow view: it is house-centric (positive = discharging), the exact
    # opposite of the vendor sign on battery_power above. Shipping both means
    # the flow points the right way without the user hand-building a negating
    # template sensor. Shares battery_power's api_key by design.
    LivoltekSensorEntityDescription(
        key="battery_power_energy_dashboard",
        api_key="batteryActivePower",
        name="Battery power (Energy dashboard)",
        unit_family=UnitFamily.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=_MEASURE,
        value_fn=_battery_flow_power,
        suggested_display_precision=3,
    ),
    LivoltekSensorEntityDescription(
        key="battery_status",
        api_key="batteryStatus",
        name="Battery status",
        # RAW so the coordinator parses it as a number and never rescales it;
        # value_fn then turns that number into one of `options`.
        unit_family=UnitFamily.RAW,
        value_fn=_battery_direction,
        device_class=SensorDeviceClass.ENUM,
        options=list(BATTERY_DIRECTIONS),
        translation_key="battery_status",
    ),
    LivoltekSensorEntityDescription(
        key="battery_voltage",
        api_key="batteryVoltage",
        name="Battery voltage",
        unit_family=UnitFamily.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=_MEASURE,
        suggested_display_precision=1,
    ),
    LivoltekSensorEntityDescription(
        key="battery_current",
        api_key="batteryCurrent",
        name="Battery current",
        unit_family=UnitFamily.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=_MEASURE,
        suggested_display_precision=1,
    ),
    LivoltekSensorEntityDescription(
        key="battery_max_temperature",
        api_key="batteryMaxTemperature",
        name="Battery max temperature",
        unit_family=UnitFamily.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=_MEASURE,
        suggested_display_precision=1,
    ),
    LivoltekSensorEntityDescription(
        key="battery_min_temperature",
        api_key="batteryMinTemperature",
        name="Battery min temperature",
        unit_family=UnitFamily.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=_MEASURE,
        suggested_display_precision=1,
    ),
    # CD = charge, FD = discharge. Confirmed by batteryCDVoltage 57.6 V vs
    # batteryFDVoltage 48 V on a 48 V LiFePO4 pack.
    LivoltekSensorEntityDescription(
        key="battery_charged_today",
        api_key="batteryCDToday",
        name="Battery charged today",
        unit_family=UnitFamily.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=_TOTAL,
        suggested_display_precision=2,
    ),
    LivoltekSensorEntityDescription(
        key="battery_charged_total",
        api_key="batteryCDTotal",
        name="Battery charged total",
        unit_family=UnitFamily.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=_TOTAL,
        suggested_display_precision=2,
    ),
    LivoltekSensorEntityDescription(
        key="battery_discharged_today",
        api_key="batteryFDToday",
        name="Battery discharged today",
        unit_family=UnitFamily.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=_TOTAL,
        suggested_display_precision=2,
    ),
    LivoltekSensorEntityDescription(
        key="battery_discharged_total",
        api_key="batteryFDTotal",
        name="Battery discharged total",
        unit_family=UnitFamily.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=_TOTAL,
        suggested_display_precision=2,
    ),
    # --- Grid (the API spells it "gird"; entity keys do not) ---------------
    # Import is positive (probe 03). Export was unreachable on the probe site,
    # so the negative direction is unverified; published as reported. The
    # Energy dashboard reads grid_imported_total / grid_exported_total, not
    # this sensor, so a wrong export sign would mislabel one instantaneous
    # reading and nothing else.
    LivoltekSensorEntityDescription(
        key="grid_power",
        api_key="girdPower",
        name="Grid power",
        unit_family=UnitFamily.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=_MEASURE,
        suggested_display_precision=3,
    ),
    LivoltekSensorEntityDescription(
        key="grid_imported_today",
        api_key="girdImportedToday",
        name="Grid imported today",
        unit_family=UnitFamily.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=_TOTAL,
        suggested_display_precision=2,
    ),
    LivoltekSensorEntityDescription(
        key="grid_imported_total",
        api_key="girdImportedTotal",
        name="Grid imported total",
        unit_family=UnitFamily.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=_TOTAL,
        suggested_display_precision=2,
    ),
    LivoltekSensorEntityDescription(
        key="grid_exported_today",
        api_key="girdExportedToday",
        name="Grid exported today",
        unit_family=UnitFamily.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=_TOTAL,
        suggested_display_precision=2,
    ),
    LivoltekSensorEntityDescription(
        key="grid_exported_total",
        api_key="girdExportedTotal",
        name="Grid exported total",
        unit_family=UnitFamily.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=_TOTAL,
        suggested_display_precision=2,
    ),
    LivoltekSensorEntityDescription(
        key="grid_voltage",
        api_key="girdVoltage",
        name="Grid voltage",
        unit_family=UnitFamily.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=_MEASURE,
        suggested_display_precision=1,
    ),
    LivoltekSensorEntityDescription(
        key="grid_current",
        api_key="girdCurrent",
        name="Grid current",
        unit_family=UnitFamily.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=_MEASURE,
        suggested_display_precision=1,
    ),
    LivoltekSensorEntityDescription(
        key="grid_frequency",
        api_key="girdFrequency",
        name="Grid frequency",
        unit_family=UnitFamily.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=_MEASURE,
        suggested_display_precision=2,
    ),
    # --- Load --------------------------------------------------------------
    LivoltekSensorEntityDescription(
        key="load_power",
        api_key="loadActivePower",
        name="Load power",
        unit_family=UnitFamily.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=_MEASURE,
        suggested_display_precision=3,
    ),
    LivoltekSensorEntityDescription(
        key="load_consumption_today",
        api_key="loadConsumptionToday",
        name="Load consumption today",
        unit_family=UnitFamily.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=_TOTAL,
        suggested_display_precision=2,
    ),
    LivoltekSensorEntityDescription(
        key="load_consumption_total",
        api_key="loadConsumptionTotal",
        name="Load consumption total",
        unit_family=UnitFamily.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=_TOTAL,
        suggested_display_precision=2,
    ),
    # loadEUsedToday (4.9) and loadConsumptionToday (3.4) disagree in the
    # recorded payload: two different measurement points. Both ship.
    LivoltekSensorEntityDescription(
        key="load_energy_used_today",
        api_key="loadEUsedToday",
        name="Load energy used today",
        unit_family=UnitFamily.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=_TOTAL,
        suggested_display_precision=2,
    ),
    LivoltekSensorEntityDescription(
        key="load_energy_used_total",
        api_key="loadEUsedTotal",
        name="Load energy used total",
        unit_family=UnitFamily.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=_TOTAL,
        suggested_display_precision=2,
    ),
    LivoltekSensorEntityDescription(
        key="load_voltage",
        api_key="loadVoltage",
        name="Load voltage",
        unit_family=UnitFamily.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=_MEASURE,
        suggested_display_precision=1,
    ),
    LivoltekSensorEntityDescription(
        key="load_current",
        api_key="loadCurrent",
        name="Load current",
        unit_family=UnitFamily.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=_MEASURE,
        suggested_display_precision=1,
    ),
    # --- PV ----------------------------------------------------------------
    LivoltekSensorEntityDescription(
        key="pv_power",
        api_key="pvPower",
        name="PV power",
        unit_family=UnitFamily.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=_MEASURE,
        suggested_display_precision=3,
    ),
    LivoltekSensorEntityDescription(
        key="pv_energy_today",
        api_key="pvFieldToday",
        name="PV energy today",
        unit_family=UnitFamily.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=_TOTAL,
        suggested_display_precision=2,
    ),
    LivoltekSensorEntityDescription(
        key="pv_energy_total",
        api_key="pvFieldTotal",
        name="PV energy total",
        unit_family=UnitFamily.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=_TOTAL,
        suggested_display_precision=2,
    ),
    # --- EPS (backup output) ----------------------------------------------
    LivoltekSensorEntityDescription(
        key="backup_power",
        api_key="epsActivePower",
        name="Backup power",
        unit_family=UnitFamily.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=_MEASURE,
        suggested_display_precision=3,
    ),
    LivoltekSensorEntityDescription(
        key="backup_voltage",
        api_key="epsVoltage",
        name="Backup voltage",
        unit_family=UnitFamily.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=_MEASURE,
        suggested_display_precision=1,
    ),
    LivoltekSensorEntityDescription(
        key="backup_current",
        api_key="epsCurrent",
        name="Backup current",
        unit_family=UnitFamily.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=_MEASURE,
        suggested_display_precision=1,
    ),
    LivoltekSensorEntityDescription(
        key="backup_energy_total",
        api_key="epsEnergy",
        name="Backup energy total",
        unit_family=UnitFamily.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=_TOTAL,
        suggested_display_precision=2,
    ),
    # --- Inverter ----------------------------------------------------------
    LivoltekSensorEntityDescription(
        key="inverter_temperature",
        api_key="temperature",
        name="Inverter temperature",
        unit_family=UnitFamily.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=_MEASURE,
        suggested_display_precision=1,
    ),
    LivoltekSensorEntityDescription(
        key="ac_power",
        api_key="acPower",
        name="AC power",
        unit_family=UnitFamily.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=_MEASURE,
        suggested_display_precision=3,
    ),
    LivoltekSensorEntityDescription(
        key="reactive_power",
        api_key="reactivePower",
        name="Reactive power",
        unit_family=UnitFamily.REACTIVE_POWER,
        native_unit_of_measurement=UnitOfReactivePower.KILO_VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=_MEASURE,
        suggested_display_precision=3,
    ),
    LivoltekSensorEntityDescription(
        key="total_runtime",
        api_key="totalTime",
        name="Total runtime",
        unit_family=UnitFamily.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=_TOTAL,
        suggested_display_precision=0,
    ),
    LivoltekSensorEntityDescription(
        key="last_reported",
        api_key="updateTime",
        name="Last reported",
        # RAW, not None: updateTime arrives as an integer, so it must go through
        # the numeric path before value_fn turns it into a datetime.
        unit_family=UnitFamily.RAW,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_epoch_ms_to_datetime,
    ),
)


_DIAGNOSTIC: tuple[LivoltekSensorEntityDescription, ...] = (
    LivoltekSensorEntityDescription(
        key="bms_capacity",
        api_key="bMSCapacity",
        name="BMS capacity",
        unit_family=UnitFamily.CHARGE,
        native_unit_of_measurement="Ah",
        state_class=_MEASURE,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    LivoltekSensorEntityDescription(
        key="battery_capacity",
        api_key="batteryCapacityKwh",
        name="Battery capacity",
        unit_family=UnitFamily.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=_MEASURE,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    LivoltekSensorEntityDescription(
        key="cell_voltage_max",
        api_key="vCellMax",
        name="Cell voltage max",
        unit_family=UnitFamily.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=_MEASURE,
        suggested_display_precision=3,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    LivoltekSensorEntityDescription(
        key="cell_voltage_min",
        api_key="vCellMin",
        name="Cell voltage min",
        unit_family=UnitFamily.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=_MEASURE,
        suggested_display_precision=3,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    LivoltekSensorEntityDescription(
        key="bus_voltage",
        api_key="busVoltage",
        name="Bus voltage",
        unit_family=UnitFamily.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=_MEASURE,
        suggested_display_precision=1,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    LivoltekSensorEntityDescription(
        key="inverter_frequency",
        api_key="dwFrequency",
        name="Inverter frequency",
        unit_family=UnitFamily.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=_MEASURE,
        suggested_display_precision=2,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    # No device class: SIGNAL_STRENGTH is dBm, and this field is a percentage.
    LivoltekSensorEntityDescription(
        key="signal_strength",
        api_key="intensity",
        name="Signal strength",
        unit_family=UnitFamily.PERCENTAGE,
        native_unit_of_measurement=PERCENTAGE,
        state_class=_MEASURE,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    LivoltekSensorEntityDescription(
        key="capacity_level",
        value_fn=int,
        api_key="capacityLevel",
        name="Capacity level",
        unit_family=UnitFamily.RAW,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    LivoltekSensorEntityDescription(
        key="battery_module_count",
        value_fn=int,
        api_key="batteryNum",
        name="Battery module count",
        unit_family=UnitFamily.RAW,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    # Raw status integers, and they stay raw. Probe 03 killed the planned enum
    # promotion twice over: the vendor app shows a power-flow diagram rather
    # than status text, so no capture can say what a given integer is called;
    # and all three of these were identical across charging, idle and
    # discharging captures, changing only when the cloud served a stale record.
    # They track data freshness, which the Online binary sensor already reports
    # from updateTime. An ENUM sensor must declare every option up front, so one
    # built from this evidence would drop standby, fault and firmware-update
    # states into `unknown` and break automations keyed on it.
    LivoltekSensorEntityDescription(
        key="pcs_status",
        value_fn=int,
        api_key="pcsStatus",
        name="PCS status",
        unit_family=UnitFamily.RAW,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    LivoltekSensorEntityDescription(
        key="work_status",
        value_fn=int,
        api_key="workStatus",
        name="Work status",
        unit_family=UnitFamily.RAW,
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    LivoltekSensorEntityDescription(
        key="arm_version",
        api_key="armVersion",
        name="ARM version",
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    LivoltekSensorEntityDescription(
        key="bms_version",
        api_key="bMSVersion",
        name="BMS version",
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    LivoltekSensorEntityDescription(
        key="master_dsp_version",
        api_key="masterDSPVersion",
        name="Master DSP version",
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    LivoltekSensorEntityDescription(
        key="slave_dsp_version",
        api_key="slaverDSPVersion",
        name="Slave DSP version",
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    LivoltekSensorEntityDescription(
        key="wifi_version",
        api_key="wifiVersion",
        name="Wi-Fi version",
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    LivoltekSensorEntityDescription(
        key="wifi_serial_number",
        api_key="wifiSn",
        name="Wi-Fi serial number",
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
    LivoltekSensorEntityDescription(
        key="battery_serial_number",
        api_key="battery1Sn",
        name="Battery serial number",
        entity_category=_DIAG,
        entity_registry_enabled_default=False,
    ),
)

SENSOR_DESCRIPTIONS: tuple[LivoltekSensorEntityDescription, ...] = (
    _PRIMARY + _DIAGNOSTIC
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,  # LivoltekConfigEntry; annotating it would import __init__ circularly
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create every sensor for every selected device."""
    # register_fields takes a Mapping[str, UnitFamily | None]: the coordinator
    # needs each key's family to decide between the numeric and the text path.
    fields = {d.api_key: d.unit_family for d in SENSOR_DESCRIPTIONS}
    entities: list[LivoltekSensor] = []
    for coordinator in entry.runtime_data.coordinators.values():
        coordinator.register_fields(fields)
        entities.extend(
            LivoltekSensor(coordinator, description)
            for description in SENSOR_DESCRIPTIONS
        )
    async_add_entities(entities)


class LivoltekSensor(LivoltekEntity, SensorEntity):
    """One telemetry field."""

    entity_description: LivoltekSensorEntityDescription

    def __init__(
        self,
        coordinator: LivoltekDeviceCoordinator,
        description: LivoltekSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """The held value, converted if the row asks for it.

        A key the portal has never sent reads as unknown, not unavailable: the
        device is fine, the field simply does not exist on this model.
        """
        value = self.coordinator.value_for(self.entity_description.api_key)
        if value is None:
            return None
        if self.entity_description.value_fn is not None:
            return self.entity_description.value_fn(value)
        return value
