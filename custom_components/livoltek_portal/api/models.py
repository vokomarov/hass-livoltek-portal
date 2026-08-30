"""Response models.

Field naming is inconsistent between endpoints: `findAllByCustomer` returns
`inverter_sn` and `template`, while `energyStorageInfo` returns `inverterSn` and
`templateId` for the same two concepts. Each model is written against its own
endpoint's actual keys — there is no shared normalisation layer, because the
next endpoint will break it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Session:
    """The result of a successful login."""

    # repr=False: the token is a bearer credential and must never appear in a
    # traceback, a debug log that formats this object, or a diagnostics dump.
    access_token: str = field(repr=False)
    expires_at: datetime
    owner_id: str | None = None


@dataclass(frozen=True, slots=True)
class DeviceRef:
    """One entry from `findAllByCustomer`.

    `device_id` is only ever a request parameter. Identity is keyed on
    `inverter_sn`, because portal ids are database-scoped and the API exposes
    `deviceReplace/replaceDevice`.
    """

    device_id: int
    inverter_sn: str
    name: str
    product_type_name: str | None = None
    template: int | None = None
    power_station_name: str | None = None
    # Set in the config flow's naming step. Never read from the portal.
    display_name: str | None = None

    @property
    def ha_name(self) -> str:
        """The Home Assistant device name, and so every entity_id's prefix.

        Never the portal's `name`, which embeds the inverter serial and turns
        every entity into `sensor.hp1abcdhsc1efghi_battery_soc` -- unwritable
        from memory in an automation, and a serial leaked into every dashboard.
        """
        return self.display_name or self.product_type_name or self.name

    @property
    def label(self) -> str:
        """Picker label: disambiguates devices on multi-site accounts."""
        if self.power_station_name:
            return f"{self.name} — {self.power_station_name}"
        return self.name

    @classmethod
    def from_payload(cls, entry: Mapping[str, Any]) -> DeviceRef | None:
        """Build from a `findAllByCustomer` list entry, or None if unusable."""
        raw_id = entry.get("id")
        serial = entry.get("inverter_sn")
        if not isinstance(raw_id, int) or not isinstance(serial, str) or not serial:
            return None
        template = entry.get("template")
        return cls(
            device_id=raw_id,
            inverter_sn=serial,
            name=str(entry.get("name") or serial),
            product_type_name=_opt_str(entry.get("productTypeName")),
            template=template if isinstance(template, int) else None,
            power_station_name=_opt_str(entry.get("powerStationName")),
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialise for storage in config entry options."""
        return {
            "device_id": self.device_id,
            "inverter_sn": self.inverter_sn,
            "name": self.name,
            "product_type_name": self.product_type_name,
            "template": self.template,
            "power_station_name": self.power_station_name,
            "display_name": self.display_name,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> DeviceRef:
        """Rebuild from config entry options."""
        return cls(
            device_id=int(raw["device_id"]),
            inverter_sn=str(raw["inverter_sn"]),
            name=str(raw["name"]),
            product_type_name=_opt_str(raw.get("product_type_name")),
            template=raw.get("template"),
            power_station_name=_opt_str(raw.get("power_station_name")),
            display_name=_opt_str(raw.get("display_name")),
        )


def _opt_str(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and value else None
