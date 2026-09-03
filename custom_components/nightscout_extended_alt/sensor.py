"""Nightscout sensors."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTime
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, UNIT_MGDL, UNIT_MMOLL
from .coordinator import NightscoutCoordinator


def _mgdl_to_mmoll(value: Any) -> float | None:
    try:
        return round(float(value) / 18.0, 3)
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> float | int | None:
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return None


def _get_nested(obj: dict | None, *keys: str):
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


class NSBaseSensor(CoordinatorEntity[NightscoutCoordinator], SensorEntity):
    """Base sensor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, description, key):
        super().__init__(coordinator)
        self.entity_description = description
        self._key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "Nightscout Extended Alt",
            "manufacturer": MANUFACTURER,
            "model": "Nightscout Socket.IO",
        }

    @property
    def native_value(self):
        return self._value()

    def _value(self):
        return None


class ValueSensor(NSBaseSensor):
    """Generic value sensor."""

    def __init__(self, coordinator, key, name, getter, unit=None, device_class=None):
        super().__init__(coordinator, None, key)
        self._attr_name = name
        self._getter = getter
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class

    def _value(self):
        return self._getter(self.coordinator)


def _glucose(c):
    sgv = c.latest_sgv
    if not sgv:
        return None
    value = sgv.get("mgdl")
    if c.glucose_unit == UNIT_MMOLL:
        return _mgdl_to_mmoll(value)
    return _num(value)


def _glucose_delta(c):
    sgv = c.latest_sgv
    if not sgv:
        return None
    value = sgv.get("mgdl")
    if value is None:
        return None
    # The capture exposes BG Delta as mg/dL. We expose it in the selected unit.
    # If delta is unavailable in the SGV payload, return None rather than guessing.
    delta = sgv.get("delta")
    if delta is None:
        return None
    if c.glucose_unit == UNIT_MMOLL:
        return _mgdl_to_mmoll(delta)
    return _num(delta)


def _iob(c):
    return _num(_get_nested(c.latest_devicestatus, "openaps", "iob", "iob"))


def _basal_iob(c):
    return _num(_get_nested(c.latest_devicestatus, "openaps", "iob", "basaliob"))


def _activity(c):
    return _num(_get_nested(c.latest_devicestatus, "openaps", "iob", "activity"))


def _cob(c):
    return _num(_get_nested(c.latest_devicestatus, "openaps", "suggested", "COB"))


def _eventual_bg(c):
    return _num(_get_nested(c.latest_devicestatus, "openaps", "suggested", "eventualBG"))


def _target_bg(c):
    return _num(_get_nested(c.latest_devicestatus, "openaps", "suggested", "targetBG"))


def _insulin_req(c):
    return _num(_get_nested(c.latest_devicestatus, "openaps", "suggested", "insulinReq"))


def _base_basal(c):
    return _num(_get_nested(c.latest_devicestatus, "pump", "extended", "BaseBasalRate"))


def _temp_basal_rate(c):
    return _num(_get_nested(c.latest_devicestatus, "pump", "extended", "TempBasalAbsoluteRate"))


def _temp_remaining(c):
    return _num(_get_nested(c.latest_devicestatus, "pump", "extended", "TempBasalRemaining"))


def _reservoir(c):
    return _num(_get_nested(c.latest_devicestatus, "pump", "extended", "Reservoir"))


def _pump_battery(c):
    return _num(_get_nested(c.latest_devicestatus, "pump", "extended", "BatteryPercent"))


def _aaps_battery(c):
    return _num(_get_nested(c.latest_devicestatus, "uploader", "battery"))


def _profile(c):
    return _get_nested(c.latest_devicestatus, "pump", "extended", "ActiveProfile")


def _pump_status(c):
    return _get_nested(c.latest_devicestatus, "pump", "extended", "Status")


def _last_bolus(c):
    return _num(_get_nested(c.latest_devicestatus, "pump", "extended", "LastBolusAmount"))


def _mgdl_sensor(c, key, name, getter):
    unit = UNIT_MMOLL if c.glucose_unit == UNIT_MMOLL else UNIT_MGDL
    return ValueSensor(c, key, name, getter, unit, SensorDeviceClass.BLOOD_GLUCOSE)


def _make_sensors(c):
    sensors = [
        _mgdl_sensor(c, "glucose", "Glucose", _glucose),
        _mgdl_sensor(c, "glucose_delta", "BG Delta", _glucose_delta),
        ValueSensor(c, "iob", "IOB", _iob, "U"),
        ValueSensor(c, "basal_iob", "Basal IOB", _basal_iob, "U"),
        ValueSensor(c, "activity", "Insulin Activity", _activity, "U/min"),
        ValueSensor(c, "cob", "COB", _cob, "g"),
        _mgdl_sensor(c, "eventual_bg", "Eventual BG", _eventual_bg),
        _mgdl_sensor(c, "target_bg", "Target BG", _target_bg),
        ValueSensor(c, "insulin_req", "Insulin Required", _insulin_req, "U"),
        ValueSensor(c, "base_basal_rate", "Base Basal Rate", _base_basal, "U/h"),
        ValueSensor(c, "temp_basal_rate", "Temp Basal Absolute Rate", _temp_basal_rate, "U/h"),
        ValueSensor(c, "temp_basal_remaining", "Temp Basal Remaining", _temp_remaining, UnitOfTime.MINUTES),
        ValueSensor(c, "reservoir", "Reservoir", _reservoir, "U"),
        ValueSensor(c, "pump_battery", "Pump Battery", _pump_battery, "%"),
        ValueSensor(c, "aaps_battery", "AAPS Phone Battery", _aaps_battery, "%"),
        ValueSensor(c, "active_profile", "Active Profile", _profile),
        ValueSensor(c, "pump_status", "Pump Status", _pump_status),
        ValueSensor(c, "last_bolus", "Last Bolus Amount", _last_bolus, "U"),
    ]
    return sensors


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(_make_sensors(coordinator))
