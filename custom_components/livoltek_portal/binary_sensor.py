"""Binary sensor platform: one Online sensor per inverter."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import LivoltekDeviceCoordinator
from .entity import LivoltekEntity

PARALLEL_UPDATES = 0

ONLINE = BinarySensorEntityDescription(
    key="online",
    name="Online",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,  # LivoltekConfigEntry
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Online sensors."""
    async_add_entities(
        LivoltekOnlineBinarySensor(coordinator)
        for coordinator in entry.runtime_data.coordinators.values()
    )


class LivoltekOnlineBinarySensor(LivoltekEntity, BinarySensorEntity):
    """Whether the inverter is still reporting to the portal."""

    def __init__(self, coordinator: LivoltekDeviceCoordinator) -> None:
        super().__init__(coordinator, ONLINE.key)
        self.entity_description = ONLINE

    @property
    def is_on(self) -> bool:
        return not self.coordinator.is_stale

    @property
    def available(self) -> bool:
        """Deliberately NOT LivoltekEntity.available.

        Every other entity goes unavailable when the payload is stale. This one
        must survive that, because reporting the inverter offline is its whole
        job. It follows the cloud call alone.
        """
        return self.coordinator.last_update_success
