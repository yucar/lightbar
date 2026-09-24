# app.py — Lightbar firmware for the Pimoroni Plasma 2350 W
# Version: 2.0.0
#
# Started by main.py (kept tiny so this module can be imported by tests).
#
# Drives 192 WS2812 LEDs as a polychromatic gradient between N "virtual
# lights", each with its own on/off, brightness and colour.
#
# Control:
#   • Home Assistant — MQTT auto-discovery (see ha.py); from there to
#     Apple Home via HA's built-in HomeKit Bridge.
#   • Local REST API — see http_api.py.
#   • Button A:
#       click (off)                 → all lights on
#       click (on, ≤2 s after on)   → randomize colours
#       click (on)                  → all lights off
#       hold                        → dim; direction alternates each hold
#                                     (from off: starts at minimum, goes up)
#
# Status LED:
#   blue pulse → connecting to WiFi     orange  → WiFi down
#   magenta    → WiFi OK, MQTT broker unreachable
#   green      → all OK
#
# Files on the board: main.py, app.py, config.py, secrets.py, gradient.py,
# lightbar.py, mqtt.py, ha.py, http_api.py  (state.json is created at runtime)
#
# Firmware: Pimoroni MicroPython for Plasma 2350 W
#   https://github.com/pimoroni/plasma/releases/latest

import asyncio
import binascii
import gc

import machine
import network
import plasma
from pimoroni import RGBLED
from time import ticks_ms, ticks_diff

import config as cfg
from lightbar import Lightbar, clamp
from mqtt import MQTTClient
from ha import HomeAssistant, VERSION
from http_api import RestApi

SAVE_DELAY_MS = 5000            # Save state this long after the last change
SYNC_COALESCE_S = 0.15          # Batch rapid changes into one MQTT update


# ─── Button ──────────────────────────────────────────────────────────

class Button:
    """Button A: debounced click / hold state machine."""

    def __init__(self, pin, bar):
        self.pin = pin
        self.bar = bar
        self._raw = False
        self._raw_since = 0
        self._pressed = False
        self._pressed_at = 0
        self._holding = False
        self._last_step = 0
        self._dir = -1              # direction of the next hold is -_dir
        self._last_on = 0

    def poll(self):
        now = ticks_ms()
        raw = self.pin.value() == 0             # active low
        if raw != self._raw:
            self._raw, self._raw_since = raw, now
        elif raw != self._pressed and ticks_diff(now, self._raw_since) >= cfg.DEBOUNCE_MS:
            self._pressed = raw
            if raw:
                self._pressed_at = now
            else:
                self._release(now)
        if self._pressed:
            self._hold_tick(now)

    def _release(self, now):
        if self._holding:
            self._holding = False
            return
        bar = self.bar
        if not bar.any_on():
            bar.set_all(on=True)
            self._last_on = now
        elif ticks_diff(now, self._last_on) <= cfg.RECLICK_WINDOW_MS:
            bar.randomize()
            self._last_on = now
        else:
            bar.set_all(on=False)

    def _hold_tick(self, now):
        bar = self.bar
        if not self._holding:
            if ticks_diff(now, self._pressed_at) < cfg.HOLD_THRESHOLD_MS:
                return
            self._holding = True
            self._last_step = now
            level = bar.master_brightness()
            if not bar.any_on():
                bar.set_all(brightness=cfg.MIN_BRIGHTNESS, transition=0)
                bar.set_all(on=True, transition=0.2)
                self._dir = 1
            elif level >= 1.0:
                self._dir = -1
            elif level <= cfg.MIN_BRIGHTNESS:
                self._dir = 1
            else:
                self._dir = -self._dir
            return
        if ticks_diff(now, self._last_step) < cfg.HOLD_REPEAT_MS:
            return
        self._last_step = now
        level = bar.master_brightness()
        target = clamp(level + self._dir * cfg.BRIGHTNESS_STEP, cfg.MIN_BRIGHTNESS, 1.0)
        if target != level:
            bar.set_all(brightness=target, transition=cfg.HOLD_REPEAT_MS * 2 / 1000)


# ─── Main application ────────────────────────────────────────────────

class App:
    def __init__(self, secrets):
        self.secrets = secrets
        strip = plasma.WS2812(cfg.NUM_LEDS)
        strip.start(cfg.FPS)
        self.status_led = RGBLED("LED_R", "LED_G", "LED_B")
        self.bar = Lightbar(strip, cfg)
        self.button = Button(machine.Pin(23, machine.Pin.IN, machine.Pin.PULL_UP), self.bar)

        self.device_id = "{}_{}".format(
            cfg.HOSTNAME, binascii.hexlify(machine.unique_id()[-3:]).decode())
        try:
            network.hostname(cfg.HOSTNAME)
        except (AttributeError, ValueError):
            pass
        self.wlan = network.WLAN(network.STA_IF)
        self.wifi_connecting = False

        self.mqtt = MQTTClient(
            self.device_id, cfg.MQTT_HOST, cfg.MQTT_PORT,
            user=getattr(secrets, "MQTT_USER", None),
            password=getattr(secrets, "MQTT_PASSWORD", None),
            keepalive=30)
        self.ha = HomeAssistant(self.bar, self.mqtt, cfg, self.device_id)

        self.changed = asyncio.Event()
        self.bar.on_change = self.changed.set
        self.save_pending = False

    # ── Tasks ─────────────────────────────────────────────────────

    async def render_loop(self):
        frame_s = 1 / cfg.FPS
        while True:
            self.bar.tick()
            await asyncio.sleep(frame_s)

    async def button_loop(self):
        while True:
            self.button.poll()
            await asyncio.sleep(0.01)

    async def sync_loop(self):
        """Publish state to HA after changes, and schedule a save."""
        while True:
            await self.changed.wait()
            await asyncio.sleep(SYNC_COALESCE_S)
            self.changed.clear()
            self.save_pending = True
            await self.ha.publish_state()

    async def save_loop(self):
        while True:
            await asyncio.sleep(1)
            if self.save_pending and ticks_diff(ticks_ms(), self.bar.last_change_ms) > SAVE_DELAY_MS:
                self.save_pending = False
                try:
                    self.bar.save()
                except OSError as e:
                    print("[State] Save failed: {!r}".format(e))

    async def wifi_loop(self):
        wlan, secrets = self.wlan, self.secrets
        wlan.active(True)
        try:
            wlan.config(pm=0xA11140)        # disable WiFi power-save: snappier replies
        except (AttributeError, ValueError, TypeError):
            pass
        static_ip = getattr(secrets, "STATIC_IP", None)
        if static_ip:
            wlan.ifconfig((static_ip, secrets.SUBNET, secrets.GATEWAY, secrets.DNS))
        while True:
            if not wlan.isconnected():
                self.wifi_connecting = True
                print("[WiFi] Connecting to '{}'...".format(secrets.WIFI_SSID))
                wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)
                for _ in range(60):
                    if wlan.isconnected():
                        break
                    await asyncio.sleep(0.5)
                self.wifi_connecting = False
                if wlan.isconnected():
                    print("[WiFi] Connected, IP {}".format(wlan.ifconfig()[0]))
                else:
                    print("[WiFi] Failed — retrying in {} s".format(cfg.WIFI_RETRY_S))
            await asyncio.sleep(cfg.WIFI_RETRY_S)

    async def status_loop(self):
        tick = 0
        while True:
            tick += 1
            if self.wifi_connecting:
                self.status_led.set_rgb(0, 0, 2 + (tick % 6))       # blue pulse
            elif not self.wlan.isconnected():
                self.status_led.set_rgb(5, 2, 0)                    # orange
            elif not self.mqtt.connected:
                self.status_led.set_rgb(4, 0, 4)                    # magenta
            else:
                self.status_led.set_rgb(0, 3, 0)                    # green
            await asyncio.sleep(0.1)

    # ── Start-up ──────────────────────────────────────────────────

    async def run(self):
        print("=" * 50)
        print("  Lightbar {} — Plasma 2350 W".format(VERSION))
        print("=" * 50)
        print("  LEDs: {}   Lights: {}".format(cfg.NUM_LEDS, ", ".join(cfg.LIGHT_NAMES)))
        print("  Device id: {}".format(self.device_id))
        print("  MQTT broker: {}:{}".format(cfg.MQTT_HOST, cfg.MQTT_PORT))

        self.bar.restore(cfg.POWER_ON)

        tasks = [
            self.render_loop(), self.button_loop(), self.sync_loop(),
            self.save_loop(), self.wifi_loop(), self.status_loop(),
            self.mqtt.run(can_connect=self.wlan.isconnected),
        ]
        for coro in tasks:
            asyncio.create_task(coro)

        if cfg.HTTP_ENABLED:
            token = getattr(self.secrets, "API_TOKEN", None)
            if not token:
                print("  WARNING: API_TOKEN not set — REST API is open to the LAN")
            api = RestApi(self.bar, token, info={
                "name": cfg.DEVICE_NAME, "model": "Plasma 2350 W",
                "firmware": VERSION, "device_id": self.device_id,
                "num_leds": cfg.NUM_LEDS, "lights": list(cfg.LIGHT_NAMES),
            })
            await api.start(cfg.HTTP_PORT)
            print("  REST API on port {}".format(cfg.HTTP_PORT))

        gc.collect()
        while True:
            await asyncio.sleep(3600)


def main():
    try:
        import secrets
    except ImportError:
        raise SystemExit("secrets.py missing — copy secrets.example.py and fill it in")
    if len(cfg.DEFAULT_COLORS) < len(cfg.LIGHT_NAMES):
        raise SystemExit("config.py: DEFAULT_COLORS needs one entry per LIGHT_NAMES")
    asyncio.run(App(secrets).run())
