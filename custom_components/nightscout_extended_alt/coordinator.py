"""Nightscout Socket.IO coordinator."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

import socketio
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_GLUCOSE_UNIT,
    CONF_TOKEN,
    CONF_URL,
    DOMAIN,
    RECONNECT_MAX,
    RECONNECT_MIN,
    SOCKET_PATH,
)

_LOGGER = logging.getLogger(__name__)


def _epoch_ms(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _iso_from_ms(value: Any) -> str | None:
    millis = _epoch_ms(value)
    if millis is None:
        return None
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat()


class NightscoutCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Maintain a live Nightscout data cache."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Nightscout Extended Alt",
            update_interval=None,
        )
        self.entry = entry
        self.url = entry.data[CONF_URL].rstrip("/")
        self.token = entry.data.get(CONF_TOKEN, "")
        self.glucose_unit = entry.data.get(CONF_GLUCOSE_UNIT, "mmol/L")

        self.sio = socketio.AsyncClient(
            reconnection=False,
            logger=False,
            engineio_logger=False,
        )
        self._runner: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._connected = False

        self.sgvs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.treatments: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.devicestatus: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.alarms: OrderedDict[str, dict[str, Any]] = OrderedDict()

        self.last_update_ms: int | None = None
        self.last_event: str | None = None
        self.last_alarm: dict[str, Any] | None = None

        self._register_handlers()

    @property
    def connected(self) -> bool:
        return self._connected

    def _register_handlers(self) -> None:
        @self.sio.event
        async def connect():
            self._connected = True
            self.last_event = "connected"
            _LOGGER.info("Connected to Nightscout Socket.IO")
            self.async_set_updated_data(self.snapshot())

        @self.sio.event
        async def disconnect():
            self._connected = False
            self.last_event = "disconnected"
            _LOGGER.warning("Disconnected from Nightscout Socket.IO")
            self.async_set_updated_data(self.snapshot())

        @self.sio.on("connected")
        async def connected_event(*args):
            self.last_event = "connected"
            self.async_set_updated_data(self.snapshot())

        @self.sio.on("dataUpdate", namespace="/")
        async def data_update(*args):
            payload = next((arg for arg in args if isinstance(arg, dict)), None)
            _LOGGER.debug("Nightscout dataUpdate received: %s", self._payload_summary(payload))
            if payload is None:
                return
            self._apply_data_update(payload)
            self.last_event = "dataUpdate"
            self.async_set_updated_data(self.snapshot())

        @self.sio.on("retroUpdate", namespace="/")
        async def retro_update(*args):
            payload = next((arg for arg in args if isinstance(arg, dict)), None)
            _LOGGER.debug("Nightscout retroUpdate received: %s", self._payload_summary(payload))
            if payload is None:
                return
            self._apply_data_update(payload)
            self.last_event = "retroUpdate"
            self.async_set_updated_data(self.snapshot())

        @self.sio.on("notification", namespace="/alarm")
        async def alarm_notification(payload=None):
            if not isinstance(payload, dict):
                return
            key = str(payload.get("notifyhash") or payload.get("key") or time.time_ns())
            self.alarms[key] = payload
            self.alarms.move_to_end(key)
            while len(self.alarms) > 100:
                self.alarms.popitem(last=False)
            self.last_alarm = payload
            self.last_event = "alarm.notification"
            self.async_set_updated_data(self.snapshot())

    @staticmethod
    def _payload_summary(payload: dict[str, Any] | None) -> str:
        if not isinstance(payload, dict):
            return repr(payload)
        return (
            f"keys={list(payload.keys())}, "
            f"sgvs={len(payload.get('sgvs') or [])}, "
            f"treatments={len(payload.get('treatments') or [])}, "
            f"devicestatus={len(payload.get('devicestatus') or [])}"
        )

    async def _authorize_socket(self) -> bool:
        """Authorize the main Nightscout Socket.IO namespace."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def callback(result=None):
            if not future.done():
                future.set_result(result if isinstance(result, dict) else {})

        payload = {
            "client": "web",
            "secret": None,
            "token": self.token or None,
            "history": 48,
        }

        _LOGGER.debug("Authorizing Nightscout Socket.IO main namespace")
        try:
            await self.sio.emit("authorize", payload, namespace="/", callback=callback)
            result = await asyncio.wait_for(future, timeout=15)
        except Exception as err:
            _LOGGER.warning("Nightscout Socket.IO authorization error: %s", err)
            return False

        _LOGGER.debug("Nightscout Socket.IO authorization response: %s", result)
        return bool(result.get("read")) if isinstance(result, dict) else False

    async def _subscribe_for_alarms(self) -> bool:
        """Subscribe to Nightscout alarm notifications."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def callback(result=None):
            if not future.done():
                future.set_result(result if isinstance(result, dict) else {})

        payload = {
            "secret": None,
            "jwtToken": self.token or None,
        }

        _LOGGER.debug("Subscribing to Nightscout alarm notifications")
        try:
            await self.sio.emit(
                "subscribe",
                payload,
                namespace="/alarm",
                callback=callback,
            )
            result = await asyncio.wait_for(future, timeout=15)
        except Exception as err:
            _LOGGER.warning("Nightscout alarm subscription error: %s", err)
            return False

        _LOGGER.debug("Nightscout alarm subscription response: %s", result)
        return bool(result.get("success")) if isinstance(result, dict) else False

    async def _bootstrap_rest(self) -> None:
        """Load a small current cache so entities do not wait for the next socket event."""
        session = async_get_clientsession(self.hass)
        params = {"count": "20"}
        if self.token:
            params["token"] = self.token

        endpoints = (
            ("sgvs", "/api/v1/entries.json"),
            ("treatments", "/api/v1/treatments.json"),
            ("devicestatus", "/api/v1/devicestatus.json"),
        )

        for cache_name, endpoint in endpoints:
            try:
                async with session.get(
                    f"{self.url}{endpoint}",
                    params=params,
                    timeout=15,
                ) as response:
                    if response.status >= 400:
                        _LOGGER.warning(
                            "Nightscout bootstrap %s returned HTTP %s",
                            endpoint,
                            response.status,
                        )
                        continue
                    data = await response.json()
                    if not isinstance(data, list):
                        _LOGGER.warning("Nightscout bootstrap %s returned non-list data", endpoint)
                        continue

                    if cache_name == "sgvs":
                        for item in data:
                            if isinstance(item, dict):
                                key = str(item.get("_id") or item.get("mills") or time.time_ns())
                                self.sgvs[key] = item
                    elif cache_name == "treatments":
                        for item in data:
                            if isinstance(item, dict) and item.get("_id"):
                                self.treatments[str(item["_id"])] = item
                    else:
                        for item in data:
                            if isinstance(item, dict):
                                key = str(item.get("_id") or item.get("mills") or item.get("date") or time.time_ns())
                                self.devicestatus[key] = item

                    _LOGGER.debug(
                        "Nightscout bootstrap %s loaded %d records",
                        endpoint,
                        len(data),
                    )
            except Exception as err:
                _LOGGER.warning("Nightscout bootstrap %s failed: %s", endpoint, err)

        self.async_set_updated_data(self.snapshot())

    def _apply_data_update(self, payload: dict[str, Any]) -> None:
        self.last_update_ms = _epoch_ms(payload.get("lastUpdated")) or self.last_update_ms

        for sgv in payload.get("sgvs") or []:
            if not isinstance(sgv, dict):
                continue
            key = str(sgv.get("_id") or sgv.get("mills") or time.time_ns())
            self.sgvs[key] = sgv
            self.sgvs.move_to_end(key)

        for treatment in payload.get("treatments") or []:
            if not isinstance(treatment, dict):
                continue
            key = treatment.get("_id")
            if not key:
                continue
            action = treatment.get("action")
            if action == "remove":
                self.treatments.pop(str(key), None)
            else:
                # Create and update events are retained by _id.
                self.treatments[str(key)] = treatment
                self.treatments.move_to_end(str(key))

        for status in payload.get("devicestatus") or []:
            if not isinstance(status, dict):
                continue
            key = str(status.get("_id") or status.get("mills") or time.time_ns())
            self.devicestatus[key] = status
            self.devicestatus.move_to_end(key)

        # Keep memory bounded while retaining a useful local history.
        for cache in (self.sgvs, self.treatments, self.devicestatus):
            while len(cache) > 5000:
                cache.popitem(last=False)

    def _latest(self, cache: OrderedDict[str, dict[str, Any]], *time_keys: str):
        if not cache:
            return None
        values = list(cache.values())
        if not time_keys:
            return values[-1]

        def sort_key(item):
            for key in time_keys:
                value = _epoch_ms(item.get(key))
                if value is not None:
                    return value
            return 0

        return max(values, key=sort_key)

    @property
    def latest_sgv(self) -> dict[str, Any] | None:
        return self._latest(self.sgvs, "mills", "date")

    @property
    def latest_devicestatus(self) -> dict[str, Any] | None:
        return self._latest(self.devicestatus, "mills", "date", "created_at")

    @property
    def latest_treatment(self) -> dict[str, Any] | None:
        return self._latest(self.treatments, "mills", "date", "created_at")

    def snapshot(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "last_event": self.last_event,
            "last_update": _iso_from_ms(self.last_update_ms),
            "glucose_unit": self.glucose_unit,
            "latest_sgv": self.latest_sgv,
            "latest_devicestatus": self.latest_devicestatus,
            "latest_treatment": self.latest_treatment,
            "last_alarm": self.last_alarm,
            "sgv_count": len(self.sgvs),
            "treatment_count": len(self.treatments),
            "devicestatus_count": len(self.devicestatus),
            "alarm_count": len(self.alarms),
        }

    async def async_start(self) -> None:
        """Start the Socket.IO worker."""
        self._stop_event.clear()
        self._runner = asyncio.create_task(self._socket_loop())

    async def async_stop(self) -> None:
        """Stop the Socket.IO worker."""
        self._stop_event.set()
        if self._runner:
            self._runner.cancel()
            try:
                await self._runner
            except asyncio.CancelledError:
                pass
        if self.sio.connected:
            await self.sio.disconnect()

    async def _socket_loop(self) -> None:
        """Connect and reconnect to Nightscout."""
        delay = RECONNECT_MIN
        while not self._stop_event.is_set():
            try:
                query_url = self.url
                if self.token:
                    separator = "&" if "?" in query_url else "?"
                    query_url = f"{query_url}{separator}token={self.token}"

                await self.sio.connect(
                    query_url,
                    socketio_path=SOCKET_PATH,
                    namespaces=["/", "/alarm"],
                    transports=["polling", "websocket"],
                    wait_timeout=15,
                )

                # Nightscout does not simply start sending the application data
                # after the Socket.IO namespace connects. The web client explicitly
                # authorizes the main socket and subscribes to the alarm namespace.
                authorized = await self._authorize_socket()
                if not authorized:
                    raise RuntimeError("Nightscout Socket.IO authorization failed")

                await self._subscribe_for_alarms()
                await self._bootstrap_rest()
                delay = RECONNECT_MIN

                while self.sio.connected and not self._stop_event.is_set():
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                raise
            except Exception as err:
                self._connected = False
                self.last_event = "connection_error"
                _LOGGER.warning("Nightscout Socket.IO connection failed: %s", err)
                self.async_set_updated_data(self.snapshot())

            if self._stop_event.is_set():
                break

            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX)
