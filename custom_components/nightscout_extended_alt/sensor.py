"""Nightscout Extended Alt sensors."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import UnitOfTime
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, UNIT_MGDL, UNIT_MMOLL
from .coordinator import NightscoutCoordinator


def _num(value: Any) -> float | int | None:
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return None


def _mgdl_to_mmoll(value: Any) -> float | None:
    number = _num(value)
    if number is None:
        return None
    return round(float(number) / 18.0, 2)


def _get(obj: dict | None, *keys: str) -> Any:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _latest_suggested(c):
    return _get(c.latest_devicestatus, "openaps", "suggested")


def _latest_enacted(c):
    return _get(c.latest_devicestatus, "openaps", "enacted")


def _glucose_value(c, value):
    return _mgdl_to_mmoll(value) if c.glucose_unit == UNIT_MMOLL else _num(value)


class NSBaseSensor(CoordinatorEntity[NightscoutCoordinator], SensorEntity):
    """Base Nightscout sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NightscoutCoordinator,
        key: str,
        name: str,
        unit: str | None = None,
        icon: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = SensorEntityDescription(key=key)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "Nightscout Extended Alt",
            "manufacturer": MANUFACTURER,
            "model": "Nightscout Socket.IO",
        }


class ValueSensor(NSBaseSensor):
    """A sensor backed by a getter."""

    def __init__(self, coordinator, key, name, getter, unit=None, icon=None):
        super().__init__(coordinator, key, name, unit, icon)
        self._getter = getter

    @property
    def native_value(self):
        return self._getter(self.coordinator)


def _glucose(c):
    return _glucose_value(c, _get(c.latest_sgv, "mgdl"))


def _delta(c):
    # The captured SGV payload does not always contain delta. Calculate it from
    # the two latest readings when Nightscout has not supplied one directly.
    sgv = c.latest_sgv
    if not sgv:
        return None
    direct = _num(sgv.get("delta"))
    if direct is not None:
        return _glucose_value(c, direct)

    values = sorted(
        [x for x in c.sgvs.values() if isinstance(x, dict)],
        key=lambda x: _num(x.get("mills")) or _num(x.get("date")) or 0,
    )
    if len(values) < 2:
        return None
    current = _num(values[-1].get("mgdl"))
    previous = _num(values[-2].get("mgdl"))
    if current is None or previous is None:
        return None
    return _glucose_value(c, current - previous)


def _aaps_bg(c):
    return _glucose_value(c, _get(_latest_suggested(c), "bg"))


def _eventual_bg(c):
    return _glucose_value(c, _get(_latest_suggested(c), "eventualBG"))


def _target_bg(c):
    return _glucose_value(c, _get(_latest_suggested(c), "targetBG"))


def _tick(c):
    return _get(_latest_suggested(c), "tick")


def _iob(c):
    return _num(_get(c.latest_devicestatus, "openaps", "iob", "iob"))


def _basal_iob(c):
    return _num(_get(c.latest_devicestatus, "openaps", "iob", "basaliob"))


def _activity(c):
    return _num(_get(c.latest_devicestatus, "openaps", "iob", "activity"))


def _cob(c):
    return _num(_get(_latest_suggested(c), "COB"))


def _insulin_req(c):
    return _num(_get(_latest_suggested(c), "insulinReq"))


def _sensitivity_ratio(c):
    return _num(_get(_latest_suggested(c), "sensitivityRatio"))


def _dynamic_isf(c):
    value = _num(_get(_latest_suggested(c), "variable_sens"))
    if value is None:
        return None
    return round(value / 18.0, 2) if c.glucose_unit == UNIT_MMOLL else value


def _isf_for_carbs(c):
    value = _num(_get(_latest_suggested(c), "isfMgdlForCarbs"))
    if value is None:
        return None
    return round(value / 18.0, 2) if c.glucose_unit == UNIT_MMOLL else value


def _algorithm(c):
    return _get(_latest_suggested(c), "algorithm")


def _dynamic_isf_active(c):
    value = _get(_latest_suggested(c), "runningDynamicIsf")
    return "On" if value is True else ("Off" if value is False else None)


def _pred_min(c, key):
    values = _get(_latest_suggested(c), "predBGs", key)
    if not isinstance(values, list) or not values:
        return None
    nums = [_num(v) for v in values]
    nums = [v for v in nums if v is not None]
    if not nums:
        return None
    return _glucose_value(c, min(nums))


def _console_min(c, label):
    """Read an exact AAPS minimum from consoleLog when present."""
    logs = _get(_latest_suggested(c), "consoleLog")
    if not isinstance(logs, list):
        return None
    prefix = f"{label}:"
    for item in logs:
        if isinstance(item, str) and prefix in item:
            match = re.search(rf"{re.escape(label)}\\s*:\\s*(-?\\d+(?:\\.\\d+)?)", item)
            if match:
                return _glucose_value(c, float(match.group(1)))
    return None


def _base_basal(c):
    return _num(_get(c.latest_devicestatus, "pump", "extended", "BaseBasalRate"))


def _temp_rate(c):
    return _num(_get(c.latest_devicestatus, "pump", "extended", "TempBasalAbsoluteRate"))


def _temp_remaining(c):
    return _num(_get(c.latest_devicestatus, "pump", "extended", "TempBasalRemaining"))


def _temp_start(c):
    return _get(c.latest_devicestatus, "pump", "extended", "TempBasalStart")


def _reservoir(c):
    value = _get(c.latest_devicestatus, "pump", "extended", "Reservoir")
    if value is None:
        value = _get(c.latest_devicestatus, "pump", "reservoir")
    return _num(value)


def _pump_battery(c):
    value = _get(c.latest_devicestatus, "pump", "extended", "BatteryPercent")
    if value is None:
        value = _get(c.latest_devicestatus, "pump", "battery", "percent")
    return _num(value)


def _phone_battery(c):
    return _num(_get(c.latest_devicestatus, "uploader", "battery"))


def _charging(c):
    value = _get(c.latest_devicestatus, "isCharging")
    return "Charging" if value is True else ("Not charging" if value is False else None)


def _profile(c):
    return _get(c.latest_devicestatus, "pump", "extended", "ActiveProfile")


def _pump_status(c):
    value = _get(c.latest_devicestatus, "pump", "status", "status")
    if value is None:
        value = _get(c.latest_devicestatus, "pump", "extended", "Status")
    return value


def _pump_version(c):
    return _get(c.latest_devicestatus, "pump", "extended", "Version")


def _pump_clock(c):
    return _get(c.latest_devicestatus, "pump", "clock")


def _last_bolus(c):
    return _num(_get(c.latest_devicestatus, "pump", "extended", "LastBolusAmount"))


def _last_bolus_time(c):
    return _get(c.latest_devicestatus, "pump", "extended", "LastBolus")


def _aaps_device(c):
    return _get(c.latest_devicestatus, "device")


def _aaps_version(c):
    return _get(c.latest_devicestatus, "configuration", "version")


def _enacted_insulin_req(c):
    return _num(_get(_latest_enacted(c), "insulinReq"))


def _enacted_rate(c):
    return _num(_get(_latest_enacted(c), "rate"))


def _enacted_duration(c):
    return _num(_get(_latest_enacted(c), "duration"))


def _last_treatment(c):
    t = c.latest_treatment
    if not t:
        return None
    return t.get("eventType")


def _last_treatment_time(c):
    t = c.latest_treatment
    if not t:
        return None
    value = t.get("mills", t.get("date"))
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


AGE_CONFIG = {
    "sage": {
        "name": "SAGE",
        "events": ("Sensor Start", "Sensor Change"),
        "warning_key": "statuslights_sage_warning",
        "critical_key": "statuslights_sage_critical",
        "icon": "mdi:thermometer",
    },
    "bage": {
        "name": "BAGE",
        "events": ("Pump Battery Change",),
        "warning_key": "statuslights_bage_warning",
        "critical_key": "statuslights_bage_critical",
        "icon": "mdi:battery-clock",
    },
    "cage": {
        "name": "CAGE",
        "events": ("Site Change",),
        "warning_key": "statuslights_cage_warning",
        "critical_key": "statuslights_cage_critical",
        "icon": "mdi:needle",
    },
    "iage": {
        "name": "IAGE",
        "events": ("Insulin Change",),
        "warning_key": "statuslights_iage_warning",
        "critical_key": "statuslights_iage_critical",
        "icon": "mdi:insulin",
    },
}


def _latest_config(c):
    # Configuration is periodically embedded in devicestatus. Walk newest-first
    # so the most recent populated configuration wins.
    statuses = sorted(
        c.devicestatus.values(),
        key=lambda x: _num(x.get("mills")) or _num(x.get("date")) or 0,
        reverse=True,
    )
    for status in statuses:
        cfg = _get(status, "configuration", "overviewConfiguration")
        if isinstance(cfg, dict) and cfg:
            return cfg
    return {}


def _age_info(c, kind):
    cfg = AGE_CONFIG[kind]
    latest = None
    latest_ms = -1

    for treatment in c.treatments.values():
        if not isinstance(treatment, dict):
            continue
        if treatment.get("eventType") not in cfg["events"]:
            continue
        value = treatment.get("mills", treatment.get("date"))
        try:
            mills = int(value)
        except (TypeError, ValueError):
            continue
        if mills <= int(datetime.now(timezone.utc).timestamp() * 1000) and mills > latest_ms:
            latest_ms = mills
            latest = treatment

    if latest is None:
        return {
            "display": "n/a",
            "age_hours": None,
            "age_days": None,
            "changed_at": None,
            "severity": "unknown",
            "warning_hours": None,
            "critical_hours": None,
        }

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    age_minutes = max(0, (now_ms - latest_ms) // 60000)
    age_hours = age_minutes // 60
    days = age_hours // 24
    hours = age_hours % 24

    warning = _num(_latest_config(c).get(cfg["warning_key"]))
    critical = _num(_latest_config(c).get(cfg["critical_key"]))

    # Nightscout's status-light preferences are expressed in hours. Its info
    # stage begins one day before warning when no separate info preference exists.
    warning_hours = int(warning) if warning is not None else None
    critical_hours = int(critical) if critical is not None else None
    info_hours = max(0, warning_hours - 24) if warning_hours is not None else None

    if critical_hours is not None and age_hours >= critical_hours:
        severity = "critical"
    elif warning_hours is not None and age_hours >= warning_hours:
        severity = "warning"
    elif info_hours is not None and age_hours >= info_hours:
        severity = "info"
    else:
        severity = "normal"

    return {
        "display": f"{days}d{hours}h" if age_hours >= 24 else f"{age_hours}h",
        "age_hours": age_hours,
        "age_days": round(age_minutes / 1440, 2),
        "changed_at": datetime.fromtimestamp(latest_ms / 1000, tz=timezone.utc).isoformat(),
        "severity": severity,
        "warning_hours": warning_hours,
        "critical_hours": critical_hours,
        "event_type": latest.get("eventType"),
        "notes": latest.get("notes"),
        "treatment_id": latest.get("_id"),
    }


class AgeSensor(NSBaseSensor):
    """Nightscout-style age pill data."""

    def __init__(self, coordinator, key):
        cfg = AGE_CONFIG[key]
        super().__init__(coordinator, key, cfg["name"], icon=cfg["icon"])
        self._age_key = key

    @property
    def native_value(self):
        return _age_info(self.coordinator, self._age_key)["display"]

    @property
    def extra_state_attributes(self):
        info = _age_info(self.coordinator, self._age_key)
        return {
            "age_hours": info["age_hours"],
            "age_days": info["age_days"],
            "changed_at": info["changed_at"],
            "event_type": info["event_type"],
            "notes": info["notes"],
            "severity": info["severity"],
            "warning_hours": info["warning_hours"],
            "critical_hours": info["critical_hours"],
            "treatment_id": info["treatment_id"],
        }


def _make_sensors(c):
    glucose_unit = UNIT_MMOLL if c.glucose_unit == UNIT_MMOLL else UNIT_MGDL
    isf_unit = f"{glucose_unit}/U"

    return [
        ValueSensor(c, "glucose", "Glucose", _glucose, glucose_unit),
        ValueSensor(c, "glucose_delta", "BG Delta", _delta, glucose_unit),
        ValueSensor(c, "aaps_bg", "AAPS BG", _aaps_bg, glucose_unit),
        ValueSensor(c, "eventual_bg", "Eventual BG", _eventual_bg, glucose_unit),
        ValueSensor(c, "target_bg", "Target BG", _target_bg, glucose_unit),
        ValueSensor(c, "tick", "BG Tick", _tick),
        ValueSensor(c, "iob", "IOB", _iob, "U"),
        ValueSensor(c, "basal_iob", "Basal IOB", _basal_iob, "U"),
        ValueSensor(c, "activity", "Insulin Activity", _activity, "U/min"),
        ValueSensor(c, "cob", "COB", _cob, "g"),
        ValueSensor(c, "insulin_req", "Insulin Required", _insulin_req, "U"),
        ValueSensor(c, "sensitivity_ratio", "Sensitivity Ratio", _sensitivity_ratio),
        ValueSensor(c, "dynamic_isf", "Dynamic ISF", _dynamic_isf, isf_unit),
        ValueSensor(c, "isf_for_carbs", "ISF for Carbs", _isf_for_carbs, isf_unit),
        ValueSensor(c, "algorithm", "AAPS Algorithm", _algorithm),
        ValueSensor(c, "dynamic_isf_active", "Dynamic ISF Active", _dynamic_isf_active),
        ValueSensor(c, "min_pred_bg", "Minimum Predicted BG", lambda x: _console_min(x, "minPredBG"), glucose_unit),
        ValueSensor(c, "min_iob_pred_bg", "Minimum IOB Predicted BG", lambda x: _console_min(x, "minIOBPredBG"), glucose_unit),
        ValueSensor(c, "min_zt_pred_bg", "Minimum ZT Predicted BG", lambda x: _console_min(x, "minZTGuardBG"), glucose_unit),
        ValueSensor(c, "min_uam_pred_bg", "Minimum UAM Predicted BG", lambda x: _console_min(x, "minUAMPredBG"), glucose_unit),
        ValueSensor(c, "base_basal_rate", "Base Basal Rate", _base_basal, "U/h"),
        ValueSensor(c, "temp_basal_rate", "Temp Basal Absolute Rate", _temp_rate, "U/h"),
        ValueSensor(c, "temp_basal_remaining", "Temp Basal Remaining", _temp_remaining, UnitOfTime.MINUTES),
        ValueSensor(c, "temp_basal_start", "Temp Basal Start", _temp_start),
        ValueSensor(c, "reservoir", "Reservoir", _reservoir, "U"),
        ValueSensor(c, "pump_battery", "Pump Battery", _pump_battery, "%"),
        ValueSensor(c, "pump_status", "Pump Status", _pump_status),
        ValueSensor(c, "pump_version", "Pump Version", _pump_version),
        ValueSensor(c, "pump_clock", "Pump Clock", _pump_clock),
        ValueSensor(c, "active_profile", "Active Profile", _profile),
        ValueSensor(c, "last_bolus_amount", "Last Bolus Amount", _last_bolus, "U"),
        ValueSensor(c, "last_bolus_time", "Last Bolus Time", _last_bolus_time),
        ValueSensor(c, "aaps_phone_battery", "AAPS Phone Battery", _phone_battery, "%"),
        ValueSensor(c, "aaps_phone_charging", "AAPS Phone Charging", _charging),
        ValueSensor(c, "aaps_device", "AAPS Device", _aaps_device),
        ValueSensor(c, "aaps_version", "AAPS Version", _aaps_version),
        ValueSensor(c, "enacted_insulin_req", "Enacted Insulin Required", _enacted_insulin_req, "U"),
        ValueSensor(c, "enacted_rate", "Enacted Rate", _enacted_rate, "U/h"),
        ValueSensor(c, "enacted_duration", "Enacted Duration", _enacted_duration, UnitOfTime.MINUTES),
        ValueSensor(c, "last_treatment", "Last Treatment", _last_treatment),
        ValueSensor(c, "last_treatment_time", "Last Treatment Time", _last_treatment_time),
        AgeSensor(c, "sage"),
        AgeSensor(c, "bage"),
        AgeSensor(c, "cage"),
        AgeSensor(c, "iage"),
    ]


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(_make_sensors(coordinator))
