"""Tolerant parsing and unit normalisation for telemetry payloads.

With `isUseChangeUnit=true` the server rescales each field independently: one
recorded payload carried `girdImportedToday` as "5.3" kWh alongside
`girdImportedTotal` as "2.08" MWh. A `total_increasing` sensor whose unit flips
at the 1000 boundary makes Home Assistant record a 1000x jump in long-term
statistics, which permanently corrupts the Energy dashboard.

Every numeric field therefore declares a family, and extraction converts the
value against the field's `<key>Unit` companion into that family's canonical
unit. An unrecognised unit yields no reading rather than a value of unknown
magnitude.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final


class UnitFamily(StrEnum):
    """The dimension a field is measured in."""

    ENERGY = "energy"
    POWER = "power"
    APPARENT_POWER = "apparent_power"
    REACTIVE_POWER = "reactive_power"
    VOLTAGE = "voltage"
    CURRENT = "current"
    CHARGE = "charge"
    FREQUENCY = "frequency"
    DURATION = "duration"
    TEMPERATURE = "temperature"
    PERCENTAGE = "percentage"
    RAW = "raw"


CANONICAL_UNIT: Final[dict[UnitFamily, str | None]] = {
    UnitFamily.ENERGY: "kWh",
    UnitFamily.POWER: "kW",
    UnitFamily.APPARENT_POWER: "kVA",
    UnitFamily.REACTIVE_POWER: "kvar",
    UnitFamily.VOLTAGE: "V",
    UnitFamily.CURRENT: "A",
    UnitFamily.CHARGE: "Ah",
    UnitFamily.FREQUENCY: "Hz",
    UnitFamily.DURATION: "h",
    UnitFamily.TEMPERATURE: "°C",
    UnitFamily.PERCENTAGE: "%",
    UnitFamily.RAW: None,
}

# Spellings are reproduced exactly as the API emits them: "kVar" with a capital
# V and a capital a, "H" for hours, U+2103 for degrees Celsius.
_SCALES: Final[dict[UnitFamily, dict[str, float]]] = {
    UnitFamily.ENERGY: {"Wh": 0.001, "kWh": 1.0, "MWh": 1000.0, "GWh": 1_000_000.0},
    UnitFamily.POWER: {"W": 0.001, "kW": 1.0, "MW": 1000.0},
    UnitFamily.APPARENT_POWER: {"VA": 0.001, "kVA": 1.0, "MVA": 1000.0},
    UnitFamily.REACTIVE_POWER: {
        "var": 0.001,
        "Var": 0.001,
        "VAr": 0.001,
        "kvar": 1.0,
        "kVar": 1.0,
        "kVAr": 1.0,
        "Mvar": 1000.0,
        "MVar": 1000.0,
    },
    UnitFamily.VOLTAGE: {"mV": 0.001, "V": 1.0, "kV": 1000.0},
    UnitFamily.CURRENT: {"mA": 0.001, "A": 1.0, "kA": 1000.0},
    UnitFamily.CHARGE: {"mAh": 0.001, "Ah": 1.0, "kAh": 1000.0},
    UnitFamily.FREQUENCY: {"Hz": 1.0, "kHz": 1000.0},
    UnitFamily.DURATION: {
        "s": 1.0 / 3600.0,
        "S": 1.0 / 3600.0,
        "min": 1.0 / 60.0,
        "h": 1.0,
        "H": 1.0,
    },
    UnitFamily.TEMPERATURE: {"℃": 1.0, "°C": 1.0, "C": 1.0},
    UnitFamily.PERCENTAGE: {"%": 1.0, "%RH": 1.0},
    UnitFamily.RAW: {},
}

# Families where a missing companion unit is unambiguous, because no SI prefix
# is in play. The payload carries no `temperatureUnit` key at all, and none for
# `capacityLevel` or `batteryNum`. Every other family refuses.
_UNIT_OPTIONAL: Final = frozenset(
    {UnitFamily.TEMPERATURE, UnitFamily.PERCENTAGE, UnitFamily.RAW}
)

# Strings the API uses for "no reading". "0" is deliberately absent: zero is a
# legitimate value, not a marker.
_ABSENT_MARKERS: Final = frozenset({"", "--", "-", "null", "N/A", "NA"})

PROBLEM_ABSENT: Final = "absent"
PROBLEM_UNPARSEABLE: Final = "unparseable"
PROBLEM_UNKNOWN_UNIT: Final = "unknown_unit"

_ROUND_TO: Final = 6


@dataclass(frozen=True, slots=True)
class Extracted:
    """The outcome of pulling one field out of a telemetry payload."""

    value: float | str | None = None
    problem: str | None = None

    @property
    def ok(self) -> bool:
        """True when `value` is usable."""
        return self.problem is None


def is_absent(raw: object) -> bool:
    """True when the API is saying "no reading" rather than reporting a value."""
    if raw is None:
        return True
    return isinstance(raw, str) and raw.strip() in _ABSENT_MARKERS


def parse_number(raw: object) -> float | None:
    """Parse a value that arrives as a JSON string, int, or float.

    Rejects non-finite results (`nan`/`inf`/`-inf`) after coercion, so both a
    literal `"nan"` string and a bare `NaN`/`Infinity` that Python's `json`
    module already decoded to a `float` are caught by the same check.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        try:
            value = float(raw.strip())
        except ValueError:
            return None
    else:
        return None
    return value if math.isfinite(value) else None


def convert(value: float, family: UnitFamily, unit: str | None) -> float | None:
    """Convert `value` into `family`'s canonical unit, or None if we cannot."""
    # RAW is dimensionless (batteryNum, capacityLevel counts): any unit string
    # is ignored rather than checked, because there is nothing to convert.
    if family is UnitFamily.RAW:
        return value
    if unit is None or not unit.strip():
        return value if family in _UNIT_OPTIONAL else None
    factor = _SCALES[family].get(unit.strip())
    if factor is None:
        return None
    return round(value * factor, _ROUND_TO)


def extract_numeric(
    payload: Mapping[str, Any], key: str, family: UnitFamily
) -> Extracted:
    """Read one numeric field and normalise it to its canonical unit."""
    if key not in payload or is_absent(payload[key]):
        return Extracted(problem=PROBLEM_ABSENT)
    number = parse_number(payload[key])
    if number is None:
        return Extracted(problem=PROBLEM_UNPARSEABLE)
    raw_unit = payload.get(f"{key}Unit")
    converted = convert(number, family, raw_unit if isinstance(raw_unit, str) else None)
    if converted is None:
        return Extracted(problem=PROBLEM_UNKNOWN_UNIT)
    return Extracted(value=converted)


def extract_text(payload: Mapping[str, Any], key: str) -> Extracted:
    """Read one string field, such as a firmware version."""
    if key not in payload or is_absent(payload[key]):
        return Extracted(problem=PROBLEM_ABSENT)
    return Extracted(value=str(payload[key]))
