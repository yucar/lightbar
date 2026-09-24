# ha.py — Home Assistant integration over MQTT (auto-discovery)
# Version: 1.0.0
#
# Publishes MQTT discovery messages so Home Assistant creates the entities
# by itself — no YAML on the HA side:
#
#   light.lightbar          "All" light (on/off + brightness for every light)
#   light.lightbar_start    per-light on/off, brightness and colour
#   light.lightbar_end      …
#   button.lightbar_randomize
#
# State is published (retained) after every change, whatever caused it —
# button, REST API or HA — so HA / Apple Home always show the real state.
#
# Topics (<base> = MQTT_TOPIC_PREFIX/<device_id>):
#   <base>/availability        "online" / "offline" (Last Will)
#   <base>/all/set|state       JSON light schema
#   <base>/light/<n>/set|state JSON light schema
#   <base>/randomize           "PRESS"

import json

VERSION = "2.0.0"


class HomeAssistant:
    def __init__(self, bar, client, cfg, device_id):
        self.bar = bar
        self.mqtt = client
        self.cfg = cfg
        self.device_id = device_id
        self.base = "{}/{}".format(cfg.MQTT_TOPIC_PREFIX, device_id)
        self.availability = self.base + "/availability"
        self.birth_topic = cfg.HA_DISCOVERY_PREFIX + "/status"
        client.will = (self.availability, b"offline")
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        self._resend = False            # set when HA restarts (birth message)

    # ── Discovery ─────────────────────────────────────────────────

    def _device(self):
        return {
            "identifiers": [self.device_id],
            "name": self.cfg.DEVICE_NAME,
            "manufacturer": "Lightbar (DIY)",
            "model": "Pimoroni Plasma 2350 W",
            "sw_version": VERSION,
        }

    def _light_config(self, uid, name, topic, color):
        return {
            "unique_id": "{}_{}".format(self.device_id, uid),
            "name": name,                       # None → entity takes the device name
            "schema": "json",
            "command_topic": topic + "/set",
            "state_topic": topic + "/state",
            "availability_topic": self.availability,
            "brightness": True,
            "brightness_scale": 255,
            "supported_color_modes": ["hs"] if color else ["brightness"],
            "device": self._device(),
        }

    async def publish_discovery(self):
        prefix = self.cfg.HA_DISCOVERY_PREFIX
        if self.cfg.EXPOSE_ALL_LIGHT:
            await self._publish_json(
                "{}/light/{}/all/config".format(prefix, self.device_id),
                self._light_config("all", None, self.base + "/all", color=False),
                retain=True)
        for light in self.bar.lights:
            await self._publish_json(
                "{}/light/{}/light{}/config".format(prefix, self.device_id, light.index),
                self._light_config("light{}".format(light.index), light.name,
                                   "{}/light/{}".format(self.base, light.index),
                                   color=True),
                retain=True)
        await self._publish_json(
            "{}/button/{}/randomize/config".format(prefix, self.device_id),
            {
                "unique_id": "{}_randomize".format(self.device_id),
                "name": "Randomize",
                "icon": "mdi:palette",
                "command_topic": self.base + "/randomize",
                "payload_press": "PRESS",
                "availability_topic": self.availability,
                "device": self._device(),
            },
            retain=True)

    # ── State ─────────────────────────────────────────────────────

    async def publish_state(self):
        if not self.mqtt.connected:
            return
        if self._resend:
            self._resend = False
            await self.publish_discovery()
        bar = self.bar
        if self.cfg.EXPOSE_ALL_LIGHT:
            await self._publish_json(self.base + "/all/state", {
                "state": "ON" if bar.any_on() else "OFF",
                "brightness": _to255(bar.master_brightness()),
                "color_mode": "brightness",
            }, retain=True)
        for light in bar.lights:
            await self._publish_json(
                "{}/light/{}/state".format(self.base, light.index), {
                    "state": "ON" if light.on else "OFF",
                    "brightness": _to255(light.brightness),
                    "color_mode": "hs",
                    "color": {"h": round(light.hue * 360, 2),
                              "s": round(light.sat * 100, 2)},
                }, retain=True)

    # ── MQTT callbacks ────────────────────────────────────────────

    async def _on_connect(self):
        await self.mqtt.subscribe(self.base + "/+/set")
        await self.mqtt.subscribe(self.base + "/light/+/set")
        await self.mqtt.subscribe(self.base + "/randomize")
        await self.mqtt.subscribe(self.birth_topic)
        await self.publish_discovery()
        await self.mqtt.publish(self.availability, "online", retain=True)
        await self.publish_state()

    def _on_message(self, topic, payload):
        if topic == self.birth_topic:
            # HA restarted: resend discovery + state on the next sync.
            if payload == b"online":
                self._resend = True
                self.bar.notify()
            return
        if topic == self.base + "/randomize":
            self.bar.randomize()
            return
        if not topic.endswith("/set"):
            return
        try:
            cmd = json.loads(payload)
        except ValueError:
            print("[HA] Ignoring non-JSON command on", topic)
            return
        if not isinstance(cmd, dict):
            return

        on = _parse_on(cmd.get("state"))
        brightness = cmd.get("brightness")
        if brightness is not None:
            brightness = clamp255(brightness) / 255
            if brightness == 0:             # "0 %" means off; keep the old level
                on, brightness = False, None
        transition = cmd.get("transition")
        if transition is not None:
            transition = min(max(float(transition), 0.0), 60.0)

        if topic == self.base + "/all/set":
            self.bar.set_all(on=on, brightness=brightness, transition=transition)
            self.bar.notify()
            return

        # <base>/light/<n>/set
        try:
            index = int(topic[len(self.base) + 7:-4])
            light_valid = 0 <= index < len(self.bar.lights)
        except ValueError:
            light_valid = False
        if not light_valid:
            return
        hue = sat = None
        color = cmd.get("color")
        if isinstance(color, dict) and "h" in color and "s" in color:
            hue = float(color["h"]) / 360
            sat = float(color["s"]) / 100
        self.bar.set_light(index, on=on, brightness=brightness, hue=hue, sat=sat,
                           transition=transition)
        # HA expects a state echo even when nothing changed (e.g. repeated ON).
        self.bar.notify()

    async def _publish_json(self, topic, obj, retain=False):
        await self.mqtt.publish(topic, json.dumps(obj), retain=retain)


def _parse_on(value):
    if value == "ON":
        return True
    if value == "OFF":
        return False
    return None


def clamp255(v):
    v = int(round(float(v)))
    return 0 if v < 0 else 255 if v > 255 else v


def _to255(v):
    return clamp255(v * 255)
