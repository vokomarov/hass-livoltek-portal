"""Unit normalisation is the highest-consequence correctness risk in the
integration: a total_increasing sensor whose unit flips at 1000 records a 1000x
jump in long-term statistics."""

from __future__ import annotations

import pytest

from custom_components.livoltek_portal.api.units import (
    _SCALES,
    CANONICAL_UNIT,
    PROBLEM_ABSENT,
    PROBLEM_UNKNOWN_UNIT,
    PROBLEM_UNPARSEABLE,
    UnitFamily,
    convert,
    extract_numeric,
    extract_text,
    is_absent,
    parse_number,
)


@pytest.mark.parametrize("raw", [None, "", "  ", "--", "-", "null", "N/A"])
def test_absent_markers_are_absent(raw: object) -> None:
    assert is_absent(raw) is True


@pytest.mark.parametrize("raw", ["0", 0, 0.0, "0.0", "5.3", -1])
def test_real_readings_are_not_absent(raw: object) -> None:
    assert is_absent(raw) is False


def test_zero_parses_to_zero_not_none() -> None:
    """pvPower is "0" every night. Treating it as absent would leave PV power
    elevated after sunset and corrupt the Energy dashboard."""
    assert parse_number("0") == 0.0
    assert parse_number(0) == 0.0
    assert parse_number(0.0) == 0.0


@pytest.mark.parametrize("raw", ["abc", "1,5", "", None, {}, [], True, False])
def test_unparseable_values_yield_none(raw: object) -> None:
    assert parse_number(raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        "nan",
        "NaN",
        "Infinity",
        "-inf",
        float("nan"),
        float("inf"),
    ],
)
def test_non_finite_values_yield_none(raw: object) -> None:
    """Python's float() and json module both accept non-finite spellings.
    `nan * factor` is `nan`, which would otherwise reach a total_increasing
    sensor as a seemingly valid reading."""
    assert parse_number(raw) is None


def test_extract_numeric_rejects_non_finite_string() -> None:
    result = extract_numeric(
        {"pvPower": "nan", "pvPowerUnit": "kW"}, "pvPower", UnitFamily.POWER
    )
    assert not result.ok
    assert result.problem == PROBLEM_UNPARSEABLE


def test_extract_numeric_rejects_non_finite_native_float() -> None:
    result = extract_numeric(
        {"pvPower": float("inf"), "pvPowerUnit": "kW"}, "pvPower", UnitFamily.POWER
    )
    assert not result.ok
    assert result.problem == PROBLEM_UNPARSEABLE


def test_energy_mwh_converts_to_kwh() -> None:
    """girdImportedTotal arrived as "2.08" MWh in a recorded payload."""
    assert convert(2.08, UnitFamily.ENERGY, "MWh") == 2080.0


@pytest.mark.parametrize(
    ("family", "unit", "value", "expected"),
    [
        (UnitFamily.ENERGY, "Wh", 1500.0, 1.5),
        (UnitFamily.ENERGY, "kWh", 5.3, 5.3),
        (UnitFamily.ENERGY, "GWh", 0.001, 1000.0),
        (UnitFamily.POWER, "W", 240.0, 0.24),
        (UnitFamily.POWER, "kW", 0.24, 0.24),
        (UnitFamily.POWER, "MW", 0.001, 1.0),
        (UnitFamily.APPARENT_POWER, "kVA", 1.0, 1.0),
        (UnitFamily.REACTIVE_POWER, "kVar", 0.19, 0.19),
        (UnitFamily.VOLTAGE, "V", 226.0, 226.0),
        (UnitFamily.CURRENT, "A", 1.06, 1.06),
        (UnitFamily.CHARGE, "Ah", 100.0, 100.0),
        (UnitFamily.FREQUENCY, "Hz", 49.97, 49.97),
        (UnitFamily.DURATION, "H", 6466.654, 6466.654),
        (UnitFamily.DURATION, "min", 90.0, 1.5),
        (UnitFamily.TEMPERATURE, "℃", 24.9, 24.9),
        (UnitFamily.PERCENTAGE, "%", 95.0, 95.0),
    ],
)
def test_conversion_table(
    family: UnitFamily, unit: str, value: float, expected: float
) -> None:
    assert convert(value, family, unit) == pytest.approx(expected)


# Every spelling in `_SCALES`, mapped to the multiplier a correct
# implementation must use. Written independently of `_SCALES` itself: a typo
# that corrupts a factor in the table under test must make this fail, not
# pass by comparing the table to itself.
_EXPECTED_SCALE_FACTORS: dict[tuple[UnitFamily, str], float] = {
    (UnitFamily.ENERGY, "Wh"): 0.001,
    (UnitFamily.ENERGY, "kWh"): 1.0,
    (UnitFamily.ENERGY, "MWh"): 1000.0,
    (UnitFamily.ENERGY, "GWh"): 1_000_000.0,
    (UnitFamily.POWER, "W"): 0.001,
    (UnitFamily.POWER, "kW"): 1.0,
    (UnitFamily.POWER, "MW"): 1000.0,
    (UnitFamily.APPARENT_POWER, "VA"): 0.001,
    (UnitFamily.APPARENT_POWER, "kVA"): 1.0,
    (UnitFamily.APPARENT_POWER, "MVA"): 1000.0,
    (UnitFamily.REACTIVE_POWER, "var"): 0.001,
    (UnitFamily.REACTIVE_POWER, "Var"): 0.001,
    (UnitFamily.REACTIVE_POWER, "VAr"): 0.001,
    (UnitFamily.REACTIVE_POWER, "kvar"): 1.0,
    (UnitFamily.REACTIVE_POWER, "kVar"): 1.0,
    (UnitFamily.REACTIVE_POWER, "kVAr"): 1.0,
    (UnitFamily.REACTIVE_POWER, "Mvar"): 1000.0,
    (UnitFamily.REACTIVE_POWER, "MVar"): 1000.0,
    (UnitFamily.VOLTAGE, "mV"): 0.001,
    (UnitFamily.VOLTAGE, "V"): 1.0,
    (UnitFamily.VOLTAGE, "kV"): 1000.0,
    (UnitFamily.CURRENT, "mA"): 0.001,
    (UnitFamily.CURRENT, "A"): 1.0,
    (UnitFamily.CURRENT, "kA"): 1000.0,
    (UnitFamily.CHARGE, "mAh"): 0.001,
    (UnitFamily.CHARGE, "Ah"): 1.0,
    (UnitFamily.CHARGE, "kAh"): 1000.0,
    (UnitFamily.FREQUENCY, "Hz"): 1.0,
    (UnitFamily.FREQUENCY, "kHz"): 1000.0,
    (UnitFamily.DURATION, "s"): 1.0 / 3600.0,
    (UnitFamily.DURATION, "S"): 1.0 / 3600.0,
    (UnitFamily.DURATION, "min"): 1.0 / 60.0,
    (UnitFamily.DURATION, "h"): 1.0,
    (UnitFamily.DURATION, "H"): 1.0,
    (UnitFamily.TEMPERATURE, "℃"): 1.0,
    (UnitFamily.TEMPERATURE, "°C"): 1.0,
    (UnitFamily.TEMPERATURE, "C"): 1.0,
    (UnitFamily.PERCENTAGE, "%"): 1.0,
    (UnitFamily.PERCENTAGE, "%RH"): 1.0,
}


def test_expected_factors_cover_every_scales_entry() -> None:
    """Guards the guard: if `_SCALES` gains or loses a spelling, this table
    must be updated to match, or the completeness claim below is false."""
    all_scale_keys = {
        (family, unit) for family, table in _SCALES.items() for unit in table
    }
    assert all_scale_keys == set(_EXPECTED_SCALE_FACTORS)


@pytest.mark.parametrize(
    ("family", "unit", "factor"),
    [(f, u, m) for (f, u), m in _EXPECTED_SCALE_FACTORS.items()],
)
def test_every_scaled_unit_converts_correctly(
    family: UnitFamily, unit: str, factor: float
) -> None:
    """Walks every spelling in `_SCALES`, not a one-per-family sample. A typo
    in this hand-authored table produces exactly the 1000x jump this module
    exists to prevent, and a sampled test would not catch it.

    Rounded to 6 places to match `convert`'s documented rounding of float
    noise (see test_extract_numeric_rounds_off_float_noise) — this does not
    hide a wrong factor, since a 1000x-scale bug is still far outside the
    rounding error at any of these magnitudes.
    """
    assert convert(10.0, family, unit) == pytest.approx(round(10.0 * factor, 6))


def test_unknown_unit_refuses_rather_than_guessing() -> None:
    assert convert(1.0, UnitFamily.ENERGY, "TWh") is None
    assert convert(1.0, UnitFamily.POWER, "horsepower") is None


@pytest.mark.parametrize(
    "family",
    [
        UnitFamily.ENERGY,
        UnitFamily.POWER,
        UnitFamily.APPARENT_POWER,
        UnitFamily.REACTIVE_POWER,
        UnitFamily.VOLTAGE,
        UnitFamily.CURRENT,
        UnitFamily.CHARGE,
        UnitFamily.FREQUENCY,
        UnitFamily.DURATION,
    ],
)
def test_every_scaled_family_refuses_an_unrecognised_unit(family: UnitFamily) -> None:
    assert convert(1.0, family, "bogus-unit") is None


def test_missing_unit_refuses_for_scaled_families() -> None:
    assert convert(1.0, UnitFamily.ENERGY, None) is None
    assert convert(1.0, UnitFamily.POWER, "") is None


def test_missing_unit_is_tolerated_where_no_prefix_is_possible() -> None:
    """The payload carries no `temperatureUnit` key for the inverter
    temperature, and no unit at all for capacityLevel or batteryNum."""
    assert convert(44.0, UnitFamily.TEMPERATURE, None) == 44.0
    assert convert(95.0, UnitFamily.PERCENTAGE, None) == 95.0
    assert convert(6.0, UnitFamily.RAW, None) == 6.0


def test_raw_ignores_any_unit_string() -> None:
    """RAW is dimensionless (batteryNum, capacityLevel): unlike every other
    family, an unrecognised or nonsensical unit does not cause a refusal,
    because there is nothing to convert against."""
    assert convert(5.0, UnitFamily.RAW, "TWh") == 5.0


def test_extract_numeric_converts_against_the_unit_companion() -> None:
    payload = {"girdImportedTotal": "2.08", "girdImportedTotalUnit": "MWh"}
    result = extract_numeric(payload, "girdImportedTotal", UnitFamily.ENERGY)
    assert result.ok
    assert result.value == 2080.0


def test_extract_numeric_reports_absent_for_null() -> None:
    result = extract_numeric(
        {"pvPower": None, "pvPowerUnit": "kW"}, "pvPower", UnitFamily.POWER
    )
    assert result.value is None
    assert result.problem == PROBLEM_ABSENT


def test_extract_numeric_reports_absent_for_a_missing_key() -> None:
    result = extract_numeric({}, "pvPower", UnitFamily.POWER)
    assert result.problem == PROBLEM_ABSENT


def test_extract_numeric_accepts_zero() -> None:
    result = extract_numeric(
        {"pvPower": "0", "pvPowerUnit": "kW"}, "pvPower", UnitFamily.POWER
    )
    assert result.ok
    assert result.value == 0.0


def test_extract_numeric_reports_unparseable() -> None:
    result = extract_numeric(
        {"pvPower": "n/a!", "pvPowerUnit": "kW"}, "pvPower", UnitFamily.POWER
    )
    assert result.problem == PROBLEM_UNPARSEABLE


def test_extract_numeric_reports_unknown_unit() -> None:
    result = extract_numeric(
        {"pvPower": "1.0", "pvPowerUnit": "GW"}, "pvPower", UnitFamily.POWER
    )
    assert result.problem == PROBLEM_UNKNOWN_UNIT


def test_extract_numeric_rounds_off_float_noise() -> None:
    """2.08 * 1000 is 2080.0000000000002 in IEEE 754."""
    payload = {"epsEnergy": "1.6", "epsEnergyUnit": "MWh"}
    assert extract_numeric(payload, "epsEnergy", UnitFamily.ENERGY).value == 1600.0


def test_extract_text_passes_strings_through() -> None:
    result = extract_text({"armVersion": "V1.1.2"}, "armVersion")
    assert result.ok
    assert result.value == "V1.1.2"


def test_extract_text_reports_absent_for_null() -> None:
    assert extract_text({"armVersion": None}, "armVersion").problem == PROBLEM_ABSENT


def test_every_family_declares_a_canonical_unit() -> None:
    assert set(CANONICAL_UNIT) == set(UnitFamily)
