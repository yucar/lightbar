# config.py — Lightbar settings (safe to commit)
# Version: 2.0.0
#
# Per-install secrets (WiFi, MQTT credentials, API token) live in
# secrets.py — copy secrets.example.py and fill it in.

# ─── Strip ───────────────────────────────────────────────────────────

NUM_LEDS = 192          # Total LEDs (two 96-LED strips in series)
FPS = 60                # Animation frame rate during transitions
MAX_BRIGHTNESS = 1.0    # Global cap, 0.0-1.0. Lower it to stay inside the
                        # 3 A USB-C budget if you run bright, desaturated colours.

# ─── Virtual lights ─────────────────────────────────────────────────
# One light per gradient anchor, spaced evenly from the start of the strip
# to the end. Each has its own on/off, brightness and colour; the strip
# blends smoothly (colour AND brightness) from one to the next.
# 1-4 lights are sensible. Names appear as "<DEVICE_NAME> <light name>".

DEVICE_NAME = "Lightbar"
LIGHT_NAMES = ("Start", "End")
DEFAULT_COLORS = ((0.6, 1.0), (0.85, 1.0))   # (hue, saturation) 0.0-1.0 per light

# Also expose one extra light that controls all of them at once.
# Its brightness scales every light proportionally, keeping their ratios.
EXPOSE_ALL_LIGHT = True

# ─── Transitions (seconds) ──────────────────────────────────────────

FADE_S = 1.0            # On / off
BRIGHTNESS_FADE_S = 0.5
COLOR_FADE_S = 0.5

# ─── Power-on behaviour ─────────────────────────────────────────────
#   "off"     → always start dark
#   "on"      → always start lit with the saved colours/brightness
#   "restore" → come back exactly as before the power cut
POWER_ON = "restore"

# ─── Button A ───────────────────────────────────────────────────────

DEBOUNCE_MS = 30
HOLD_THRESHOLD_MS = 600     # Press longer than this = hold (dimming)
HOLD_REPEAT_MS = 50         # Brightness step interval while held
BRIGHTNESS_STEP = 0.02
MIN_BRIGHTNESS = 0.02
RECLICK_WINDOW_MS = 2000    # A click this soon after turning on randomizes

# ─── Network ────────────────────────────────────────────────────────

HOSTNAME = "lightbar"       # → http://lightbar.local
WIFI_RETRY_S = 10

# MQTT broker — the Mosquitto container from hub/docker-compose.yml.
# Use the IP (or hostname) of the machine running Docker.
MQTT_HOST = "192.168.1.10"
MQTT_PORT = 1883
MQTT_TOPIC_PREFIX = "lightbar"
HA_DISCOVERY_PREFIX = "homeassistant"

# Local REST API (curl / scripts). Protect it with API_TOKEN in secrets.py.
HTTP_ENABLED = True
HTTP_PORT = 80
