# lightbar.py — Light state + renderer for Lightbar
# Version: 2.0.0
#
# Holds the state of every virtual light and renders it to the strip.
# Nothing here blocks: a change only sets a new target frame, and tick()
# (called every frame by the render loop) crossfades towards it.
#
# All front-ends (button, REST API, Home Assistant) go through the same
# methods below, so they can never disagree about the state.

import json
import os
import random

from time import ticks_ms, ticks_diff

import gradient

STATE_FILE = "state.json"


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def ease_in_out_circ(t):
    if t < 0.5:
        return (1.0 - (1.0 - (2.0 * t) ** 2) ** 0.5) / 2.0
    return ((1.0 - (-2.0 * t + 2.0) ** 2) ** 0.5 + 1.0) / 2.0


class Light:
    """One gradient anchor. Brightness is kept while the light is off."""

    def __init__(self, index, name, hue, sat):
        self.index = index
        self.name = name
        self.on = False
        self.brightness = 1.0
        self.hue = hue
        self.sat = sat

    def to_dict(self):
        return {
            "name": self.name,
            "on": self.on,
            "brightness": round(self.brightness, 4),
            "hue": round(self.hue, 4),
            "sat": round(self.sat, 4),
        }


class Lightbar:
    def __init__(self, strip, cfg):
        self.strip = strip
        self.cfg = cfg
        self.num_leds = cfg.NUM_LEDS
        self.lights = [
            Light(i, name, cfg.DEFAULT_COLORS[i][0], cfg.DEFAULT_COLORS[i][1])
            for i, name in enumerate(cfg.LIGHT_NAMES)
        ]
        # Called with no arguments after every state change (sync + save).
        self.on_change = None
        self.last_change_ms = ticks_ms()

        n = self.num_leds
        self._from = gradient.new_frame(n)     # frame at the start of a fade
        self._to = gradient.new_frame(n)       # target frame
        self._shown = gradient.new_frame(n)    # what is on the strip now
        self._fade_start = 0
        self._fade_ms = 0
        self._animating = False

    # ── Queries ───────────────────────────────────────────────────

    def any_on(self):
        for light in self.lights:
            if light.on:
                return True
        return False

    def master_brightness(self):
        """Brightness of the "All" light: the brightest light that is on."""
        lit = [l.brightness for l in self.lights if l.on]
        return max(lit) if lit else max(l.brightness for l in self.lights)

    def state(self):
        return {
            "on": self.any_on(),
            "brightness": round(self.master_brightness(), 4),
            "lights": [l.to_dict() for l in self.lights],
        }

    # ── Commands ──────────────────────────────────────────────────

    def set_light(self, index, on=None, brightness=None, hue=None, sat=None,
                  transition=None):
        """Change one light. Unspecified fields keep their value."""
        light = self.lights[index]
        duration = None
        if hue is not None or sat is not None:
            if hue is not None:
                light.hue = hue % 1.0
            if sat is not None:
                light.sat = clamp(sat)
            duration = self.cfg.COLOR_FADE_S
        if brightness is not None:
            light.brightness = clamp(brightness)
            duration = self.cfg.BRIGHTNESS_FADE_S
        if on is not None and on != light.on:
            light.on = on
            duration = self.cfg.FADE_S
        if duration is not None:
            self._changed(duration if transition is None else transition)

    def set_all(self, on=None, brightness=None, transition=None):
        """Change every light at once.

        brightness scales all lights proportionally so the brightest one
        ends up at `brightness` and the others keep their relative level.
        """
        duration = None
        if brightness is not None:
            brightness = clamp(brightness)
            current = self.master_brightness()
            for light in self.lights:
                if current > 0:
                    light.brightness = clamp(light.brightness * brightness / current)
                else:
                    light.brightness = brightness
            duration = self.cfg.BRIGHTNESS_FADE_S
        if on is not None:
            for light in self.lights:
                if light.on != on:
                    light.on = on
                    duration = self.cfg.FADE_S
        if duration is not None:
            self._changed(duration if transition is None else transition)

    def notify(self):
        """Ask the front-ends to re-sync (publish state, schedule a save)."""
        if self.on_change:
            self.on_change()

    def toggle_all(self):
        self.set_all(on=not self.any_on())

    def randomize(self):
        for light in self.lights:
            light.hue = random.random()
            light.sat = 1.0
        self._changed(self.cfg.COLOR_FADE_S)

    # ── Rendering ─────────────────────────────────────────────────

    def _anchors(self):
        cap = self.cfg.MAX_BRIGHTNESS
        return [
            (l.hue, l.sat, l.brightness * cap if l.on else 0.0)
            for l in self.lights
        ]

    def _changed(self, duration_s, notify=True):
        """Start a crossfade from what is shown now to the new state."""
        n3 = self.num_leds * 3
        shown, start = self._shown, self._from
        for j in range(n3):
            start[j] = shown[j]
        gradient.build(self._to, self.num_leds, self._anchors())
        self._fade_start = ticks_ms()
        self._fade_ms = int(max(0.0, duration_s) * 1000)
        self._animating = True
        self.last_change_ms = self._fade_start
        if notify:
            self.notify()

    def tick(self):
        """Advance the current fade by one frame. Cheap when idle."""
        if not self._animating:
            return
        if self._fade_ms <= 0:
            t = 1.0
        else:
            t = clamp(ticks_diff(ticks_ms(), self._fade_start) / self._fade_ms)
        gradient.blend(self._shown, self._from, self._to,
                       ease_in_out_circ(t), self.num_leds)
        _write(self.strip, self._shown, self.num_leds)
        if t >= 1.0:
            self._animating = False

    # ── Persistence ───────────────────────────────────────────────

    def save(self):
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump([l.to_dict() for l in self.lights], f)
        os.rename(tmp, STATE_FILE)      # atomic: never leaves a half-written file

    def restore(self, power_on):
        """Load saved state and apply the power-on policy. Call once at boot."""
        try:
            with open(STATE_FILE) as f:
                saved = json.load(f)
            for light, data in zip(self.lights, saved):
                light.brightness = clamp(float(data["brightness"]))
                light.hue = float(data["hue"]) % 1.0
                light.sat = clamp(float(data["sat"]))
                light.on = bool(data["on"])
        except (OSError, ValueError, KeyError, TypeError):
            pass                            # first boot or unreadable: defaults
        if power_on == "off":
            for light in self.lights:
                light.on = False
        elif power_on == "on":
            for light in self.lights:
                light.on = True
        self._changed(self.cfg.FADE_S, notify=False)


try:
    from micropython import native as _native
except ImportError:
    def _native(f):
        return f


@_native
def _write(strip, frame, num_leds):
    for i in range(num_leds):
        j = i * 3
        strip.set_hsv(i, frame[j], frame[j + 1], frame[j + 2])
