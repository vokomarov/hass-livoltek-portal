"""Shared entity base: device identity and availability."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import LivoltekDeviceCoordinator


class LivoltekEntity(CoordinatorEntity[LivoltekDeviceCoordinator]):
    """Base for every entity backed by one inverter."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: LivoltekDeviceCoordinator, key: str) -> None:
        super().__init__(coordinator)
        device = coordinator.device
        # Keyed on the serial, not the numeric id: portal ids are
        # database-scoped and the API exposes deviceReplace/replaceDevice, so an
        # id can change under a physically unchanged device.
        self._attr_unique_id = f"{device.inverter_sn}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.inverter_sn)},
            name=device.ha_name,
            manufacturer=MANUFACTURER,
            model=device.product_type_name,
            serial_number=device.inverter_sn,
            sw_version=_text(coordinator.raw, "masterDSPVersion"),
            hw_version=_text(coordinator.raw, "hardwareVersion"),
        )

    @property
    def available(self) -> bool:
        """Available when the cloud call worked and the inverter is reporting."""
        return super().available and not self.coordinator.is_stale


def _text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return str(value) if isinstance(value, str) and value else None
