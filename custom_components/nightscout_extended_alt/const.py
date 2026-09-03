"""Constants for Nightscout Extended Alt."""
from homeassistant.const import Platform

DOMAIN = "nightscout_extended_alt"
NAME = "Nightscout Extended Alt"
MANUFACTURER = "Nightscout"

CONF_URL = "url"
CONF_TOKEN = "token"
CONF_GLUCOSE_UNIT = "glucose_unit"

UNIT_MGDL = "mg/dL"
UNIT_MMOLL = "mmol/L"

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

SOCKET_PATH = "/socket.io"
RECONNECT_MIN = 2
RECONNECT_MAX = 60
