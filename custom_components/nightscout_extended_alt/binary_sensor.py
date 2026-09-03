"""Nightscout binary sensors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NightscoutCoordinator


class NightscoutConnectionSensor(CoordinatorEntity[NightscoutCoordinator], BinarySensorEntity):
    """Socket connection state."""

    _attr_has_entity_name = True
    _attr_name = "Socket Connected"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_socket_connected"
        self._attr_device_class = "connectivity"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "Nightscout Extended Alt",
            "manufacturer": "Nightscout",
            "model": "Nightscout Socket.IO",
        }

    @property
    def is_on(self):
        return self.coordinator.connected


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NightscoutConnectionSensor(coordinator)])
