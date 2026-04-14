# main.py — Lightbar Plasma 2350 W Firmware (Single-Board WiFi)
# Version: 1.5.0
#
# Drives 192 WS2812 LEDs with a polychromatic HSV gradient.
# Exposes a REST API over WiFi for smart home control via Matterbridge.
#
# Button behavior (BUTTON_A only):
#   Click (off)  → turn on
#   Click (on)   → turn off (or randomize if within RECLICK_WINDOW_MS)
#   Hold         → increase brightness
#
# Status LED:
#   Blue pulse → connecting to WiFi
#   Green      → connected, all OK
#   Orange     → WiFi disconnected, trying to reconnect
#
# Flash with Pimoroni's official MicroPython firmware for Plasma 2350 W:
#   https://github.com/pimoroni/plasma/releases/latest

import plasma
from pimoroni import RGBLED
from machine import Pin
import network
import time
import math
import random
import json
import asyncio

from gradient import gradient_2color, gradient_3color

# ─── Configuration ───────────────────────────────────────────────────

NUM_LEDS = 192          # Total LEDs (two 96-LED strips in series)
NUM_LIGHTS = 2          # Virtual lights exposed to Matterbridge (2 or 3)
FPS = 60                # LED refresh rate
FADE_DURATION = 1.0     # Seconds for on/off fade transition
COLOR_FADE_DURATION = 0.5  # Seconds for colour-change crossfade
HTTP_PORT = 80          # REST API port

# Button timing
HOLD_REPEAT_MS = 50     # Interval between brightness steps while held
BRIGHTNESS_STEP = 0.02
MIN_BRIGHTNESS = 0.02
RECLICK_WINDOW_MS = 2000  # Window after turn-on in which a click randomizes

# WiFi
WIFI_RETRY_INTERVAL_S = 10
MDNS_HOSTNAME = "lightbar"

# Default gradient colors (HSV: hue 0.0-1.0, saturation 0.0-1.0, value 0.0-1.0)
DEFAULT_COLOR_1 = (0.6, 1.0, 1.0)    # Blue
DEFAULT_COLOR_2 = (0.85, 1.0, 1.0)   # Purple
DEFAULT_COLOR_3 = (0.0, 1.0, 1.0)    # Red (midpoint, only if NUM_LIGHTS==3)

# ─── Hardware Setup ──────────────────────────────────────────────────

led_strip = plasma.WS2812(NUM_LEDS)
led_strip.start(FPS)

# User button "A" on the Plasma 2350 W — GP23, active low.
btn_pin = Pin(23, Pin.IN, Pin.PULL_UP)

status_led = RGBLED("LED_R", "LED_G", "LED_B")

# WiFi
wlan = network.WLAN(network.STA_IF)

# ─── State ───────────────────────────────────────────────────────────

is_on = False
brightness = 1.0
current_brightness = 0.0
num_gradient_colors = NUM_LIGHTS

color_1 = list(DEFAULT_COLOR_1)
color_2 = list(DEFAULT_COLOR_2)
color_3 = list(DEFAULT_COLOR_3)

gradient_dirty = True
gradient_cache = []     # Target gradient (what we're fading TO)
gradient_prev = []      # Previous gradient (what we're fading FROM)
color_fade_t = 1.0      # 0.0 = full prev, 1.0 = full target (done)
color_fade_start_ms = 0

wifi_connected = False

# Button state (raw Pin, manual debounce + hold detection)
btn_down = False
btn_down_time = 0
btn_was_hold = False
btn_last_hold_tick = 0
btn_last_on_time = 0

HOLD_THRESHOLD_MS = 600  # ms before a press counts as a hold

# ─── WiFi ────────────────────────────────────────────────────────────

def wifi_connect():
    global wifi_connected

    try:
        from secrets import WIFI_SSID, WIFI_PASSWORD
    except ImportError:
        print("ERROR: secrets.py not found — create it with WIFI_SSID and WIFI_PASSWORD")
        return False

    wlan.active(True)

    try:
        from secrets import STATIC_IP, SUBNET, GATEWAY, DNS
        wlan.ifconfig((STATIC_IP, SUBNET, GATEWAY, DNS))
        print("  Static IP: {}".format(STATIC_IP))
    except ImportError:
        pass

    if wlan.isconnected():
        wifi_connected = True
        return True

    print("  Connecting to '{}'...".format(WIFI_SSID))
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    for i in range(30):
        if wlan.isconnected():
            break
        status_led.set_rgb(0, 0, int(2 + 3 * ((i % 6) / 5)))
        time.sleep(0.5)

    if wlan.isconnected():
        wifi_connected = True
        print("  Connected! IP: {}".format(wlan.ifconfig()[0]))
        return True
    else:
        wifi_connected = False
        print("  WiFi connection failed")
        return False


async def wifi_watchdog():
    global wifi_connected
    while True:
        if not wlan.isconnected():
            wifi_connected = False
            print("WiFi lost — reconnecting...")
            wifi_connect()
        else:
            wifi_connected = True
        await asyncio.sleep(WIFI_RETRY_INTERVAL_S)


# ─── Easing ──────────────────────────────────────────────────────────

def ease_in_out_circ(t):
    if t < 0.5:
        return (1.0 - math.sqrt(1.0 - (2.0 * t) ** 2)) / 2.0
    else:
        return (math.sqrt(1.0 - (-2.0 * t + 2.0) ** 2) + 1.0) / 2.0


# ─── Gradient ────────────────────────────────────────────────────────

def recalculate_gradient(crossfade=False):
    global gradient_cache, gradient_prev, gradient_dirty
    global color_fade_t, color_fade_start_ms

    if crossfade and is_on and gradient_cache:
        gradient_prev = list(gradient_cache)
        color_fade_t = 0.0
        color_fade_start_ms = time.ticks_ms()
    else:
        color_fade_t = 1.0

    if num_gradient_colors == 3:
        gradient_cache = gradient_3color(
            NUM_LEDS,
            color_1[0], color_1[1], color_1[2],
            color_3[0], color_3[1], color_3[2],
            color_2[0], color_2[1], color_2[2],
            polychromatic=True,
        )
    else:
        gradient_cache = gradient_2color(
            NUM_LEDS,
            color_1[0], color_1[1], color_1[2],
            color_2[0], color_2[1], color_2[2],
            polychromatic=True,
        )
    gradient_dirty = False


def _hsv_lerp_short(h1, s1, v1, h2, s2, v2, t):
    dh = h2 - h1
    if dh > 0.5:
        dh -= 1.0
    elif dh < -0.5:
        dh += 1.0
    return (h1 + dh * t) % 1.0, s1 + (s2 - s1) * t, v1 + (v2 - v1) * t


def apply_gradient():
    t = color_fade_t
    if t >= 1.0 or not gradient_prev:
        for i in range(NUM_LEDS):
            h, s, v = gradient_cache[i]
            led_strip.set_hsv(i, h, s, v * current_brightness)
    else:
        te = ease_in_out_circ(t)
        for i in range(NUM_LEDS):
            h1, s1, v1 = gradient_prev[i]
            h2, s2, v2 = gradient_cache[i]
            h, s, v = _hsv_lerp_short(h1, s1, v1, h2, s2, v2, te)
            led_strip.set_hsv(i, h, s, v * current_brightness)


def leds_off():
    for i in range(NUM_LEDS):
        led_strip.set_hsv(i, 0, 0, 0)


def fade_to(target, duration):
    global current_brightness
    if duration <= 0:
        current_brightness = target
        if target <= 0.001:
            leds_off()
        else:
            apply_gradient()
        return
    start = current_brightness
    steps = int(duration * FPS)
    if steps < 1:
        steps = 1
    for step in range(steps + 1):
        t = ease_in_out_circ(step / steps)
        current_brightness = start + (target - start) * t
        if current_brightness <= 0.001:
            leds_off()
        else:
            apply_gradient()
        time.sleep(1.0 / FPS)


def randomize_colors():
    global gradient_dirty
    color_1[0] = random.random()
    color_1[1] = 1.0
    color_1[2] = 1.0
    color_2[0] = random.random()
    color_2[1] = 1.0
    color_2[2] = 1.0
    if num_gradient_colors == 3:
        color_3[0] = random.random()
        color_3[1] = 1.0
        color_3[2] = 1.0
    gradient_dirty = True


# ─── Status LED ──────────────────────────────────────────────────────

def update_status_led():
    if not wifi_connected:
        status_led.set_rgb(5, 2, 0)  # Orange
    else:
        status_led.set_rgb(0, 3, 0)  # Green


# ─── REST API ────────────────────────────────────────────────────────

def get_state():
    colors = [
        {"h": round(color_1[0], 4), "s": round(color_1[1], 4), "v": round(color_1[2], 4)},
        {"h": round(color_2[0], 4), "s": round(color_2[1], 4), "v": round(color_2[2], 4)},
    ]
    if num_gradient_colors == 3:
        colors.insert(1, {"h": round(color_3[0], 4), "s": round(color_3[1], 4), "v": round(color_3[2], 4)})
    return {
        "on": is_on,
        "brightness": round(brightness, 4),
        "num_colors": num_gradient_colors,
        "colors": colors,
        "num_leds": NUM_LEDS,
        "wifi_ip": wlan.ifconfig()[0] if wlan.isconnected() else None,
    }


def clamp(v, lo=0, hi=1.0):
    return max(lo, min(hi, v))


def parse_body(raw):
    try:
        idx = raw.find(b"\r\n\r\n")
        if idx < 0:
            return {}
        body = raw[idx + 4:]
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))
    except Exception:
        return {}


def parse_query(qs):
    result = {}
    if not qs:
        return result
    for pair in qs.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            result[k] = v
        elif pair:
            result[pair] = ""
    return result


def rgb_to_hsv(r, g, b):
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    cmax = max(r, g, b)
    cmin = min(r, g, b)
    delta = cmax - cmin
    v = cmax
    s = 0.0 if cmax == 0 else delta / cmax
    if delta == 0:
        h = 0.0
    elif cmax == r:
        h = (((g - b) / delta) % 6) / 6.0
    elif cmax == g:
        h = ((b - r) / delta + 2) / 6.0
    else:
        h = ((r - g) / delta + 4) / 6.0
    return h % 1.0, s, v


def handle_request(method, path, query, body):
    merged = dict(body)
    merged.update(query)
    global is_on, brightness, num_gradient_colors, gradient_dirty

    if path == "/status" and method in ("GET", "POST"):
        return 200, get_state()

    elif path == "/on" and method in ("POST", "GET"):
        is_on = True
        if gradient_dirty:
            recalculate_gradient()
        fade_to(brightness, FADE_DURATION)
        return 200, get_state()

    elif path == "/off" and method in ("POST", "GET"):
        is_on = False
        fade_to(0.0, FADE_DURATION)
        return 200, get_state()

    elif path == "/toggle" and method in ("POST", "GET"):
        if is_on:
            is_on = False
            fade_to(0.0, FADE_DURATION)
        else:
            is_on = True
            if gradient_dirty:
                recalculate_gradient()
            fade_to(brightness, FADE_DURATION)
        return 200, get_state()

    elif path == "/brightness" and method in ("POST", "GET"):
        if "value" in merged:
            raw_val = float(merged["value"])
            brightness = clamp(raw_val / 100.0 if raw_val > 1.0 else raw_val)
            if is_on:
                fade_to(brightness, FADE_DURATION * 0.5)
        return 200, get_state()

    elif path == "/color" and method in ("POST", "GET"):
        if "r" in merged and "g" in merged and "b" in merged:
            # RGB: ?idx=N&r=R&g=G&b=B (0-255)
            r = clamp(int(merged["r"]), 0, 255)
            g = clamp(int(merged["g"]), 0, 255)
            b = clamp(int(merged["b"]), 0, 255)
            idx = int(merged.get("idx", merged.get("index", 0)))
            h, s, v = rgb_to_hsv(r, g, b)
            if idx == 0:
                color_1[:] = [h, s, v]
            elif idx == 1:
                color_2[:] = [h, s, v]
            elif idx == 2:
                color_3[:] = [h, s, v]
                num_gradient_colors = 3
            gradient_dirty = True
            if is_on:
                recalculate_gradient(crossfade=True)
                apply_gradient()
        elif "h" in merged and "s" in merged:
            # Hue/Sat: ?idx=N&h=H&s=S  (h: 0-360, s: 0-100)
            h = clamp(float(merged["h"]) / 360.0)
            s = clamp(float(merged["s"]) / 100.0)
            idx = int(merged.get("idx", merged.get("index", 0)))
            if idx == 0:
                color_1[:] = [h, s, 1.0]
            elif idx == 1:
                color_2[:] = [h, s, 1.0]
            elif idx == 2:
                color_3[:] = [h, s, 1.0]
                num_gradient_colors = 3
            gradient_dirty = True
            if is_on:
                recalculate_gradient(crossfade=True)
                apply_gradient()
        else:
            # JSON body: {"colors": [{"h":H,"s":S,"v":V}, ...]}
            colors = body.get("colors", [])
            if len(colors) >= 2:
                color_1[0] = clamp(float(colors[0].get("h", 0)))
                color_1[1] = clamp(float(colors[0].get("s", 1)))
                color_1[2] = clamp(float(colors[0].get("v", 1)))
                color_2[0] = clamp(float(colors[1].get("h", 0)))
                color_2[1] = clamp(float(colors[1].get("s", 1)))
                color_2[2] = clamp(float(colors[1].get("v", 1)))
                num_gradient_colors = 2
                if len(colors) >= 3:
                    color_3[0] = clamp(float(colors[2].get("h", 0)))
                    color_3[1] = clamp(float(colors[2].get("s", 1)))
                    color_3[2] = clamp(float(colors[2].get("v", 1)))
                    num_gradient_colors = 3
                gradient_dirty = True
                if is_on:
                    recalculate_gradient(crossfade=True)
        return 200, get_state()

    elif path == "/randomize" and method in ("POST", "GET"):
        randomize_colors()
        if is_on:
            recalculate_gradient(crossfade=True)
            apply_gradient()
        return 200, get_state()

    elif path == "/info" and method in ("GET", "POST"):
        return 200, {
            "name": "Lightbar",
            "model": "Plasma 2350 W",
            "firmware": "1.0.0",
            "num_leds": NUM_LEDS,
            "num_lights": NUM_LIGHTS,
            "endpoints": [
                "GET  /status",
                "POST /on",
                "POST /off",
                "POST /toggle",
                "POST /brightness  {value: 0.0-1.0}",
                "POST /color        {colors: [{h,s,v},...]} OR ?idx=N&h=H&s=S OR ?idx=N&r=R&g=G&b=B",
                "POST /randomize",
                "GET  /info",
            ],
        }

    else:
        return 404, {"error": "Not found", "path": path}


async def http_server():
    async def handle_client(reader, writer):
        try:
            raw = await asyncio.wait_for(reader.read(2048), timeout=5.0)
            if not raw:
                writer.close()
                await writer.wait_closed()
                return

            first_line = raw.split(b"\r\n")[0].decode("utf-8")
            parts = first_line.split(" ")
            method = parts[0] if len(parts) >= 1 else "GET"
            full_path = parts[1] if len(parts) >= 2 else "/"

            if "?" in full_path:
                path, qs = full_path.split("?", 1)
            else:
                path, qs = full_path, ""

            query = parse_query(qs)
            body = parse_body(raw) if method == "POST" else {}

            status, response = handle_request(method, path, query, body)

            response_json = json.dumps(response)
            http_response = (
                "HTTP/1.1 {} {}\r\n"
                "Content-Type: application/json\r\n"
                "Access-Control-Allow-Origin: *\r\n"
                "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
                "Access-Control-Allow-Headers: Content-Type\r\n"
                "Connection: close\r\n"
                "Content-Length: {}\r\n"
                "\r\n"
                "{}"
            ).format(
                status,
                "OK" if status == 200 else "Not Found",
                len(response_json),
                response_json,
            )

            writer.write(http_response.encode("utf-8"))
            await writer.drain()

        except Exception as e:
            try:
                err = json.dumps({"error": str(e)})
                writer.write(
                    "HTTP/1.1 500 Internal Server Error\r\n"
                    "Content-Type: application/json\r\n"
                    "Connection: close\r\n"
                    "Content-Length: {}\r\n"
                    "\r\n"
                    "{}".format(len(err), err).encode("utf-8")
                )
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "0.0.0.0", HTTP_PORT)
    ip = wlan.ifconfig()[0] if wlan.isconnected() else "?"
    print("  HTTP server on http://{}:{}".format(ip, HTTP_PORT))

    while True:
        await asyncio.sleep(1)


# ─── Button State Machine ───────────────────────────────────────────

def update_buttons():
    """Button A (GP23): click to toggle on/off (or randomize), hold to brighten."""
    global is_on, brightness, current_brightness
    global btn_down, btn_down_time, btn_was_hold, btn_last_hold_tick, btn_last_on_time
    global gradient_dirty

    now = time.ticks_ms()
    pressed = btn_pin.value() == 0  # active low

    if pressed and not btn_down:
        # Button just pressed
        btn_down = True
        btn_down_time = now
        btn_last_hold_tick = now
        btn_was_hold = False

    elif pressed and btn_down:
        # Button held — check for hold threshold
        held_ms = time.ticks_diff(now, btn_down_time)
        if held_ms >= HOLD_THRESHOLD_MS:
            btn_was_hold = True
            if time.ticks_diff(now, btn_last_hold_tick) >= HOLD_REPEAT_MS:
                btn_last_hold_tick = now
                if is_on:
                    brightness = min(1.0, brightness + BRIGHTNESS_STEP)
                    current_brightness = brightness
                    apply_gradient()

    elif not pressed and btn_down:
        # Button just released
        btn_down = False
        if not btn_was_hold:
            # Single click
            if not is_on:
                is_on = True
                btn_last_on_time = now
                if gradient_dirty:
                    recalculate_gradient()
                fade_to(brightness, FADE_DURATION)
            else:
                if time.ticks_diff(now, btn_last_on_time) <= RECLICK_WINDOW_MS:
                    btn_last_on_time = now
                    randomize_colors()
                    recalculate_gradient(crossfade=True)
                    apply_gradient()
                else:
                    is_on = False
                    fade_to(0.0, FADE_DURATION)


# ─── Background Tasks ───────────────────────────────────────────────

async def color_fade_loop():
    global color_fade_t
    frame_s = 1.0 / FPS
    while True:
        if color_fade_t < 1.0 and is_on:
            elapsed = time.ticks_diff(time.ticks_ms(), color_fade_start_ms) / 1000.0
            color_fade_t = min(1.0, elapsed / COLOR_FADE_DURATION)
            apply_gradient()
        await asyncio.sleep(frame_s)


async def button_and_status_loop():
    counter = 0
    while True:
        update_buttons()
        counter += 1
        if counter >= 50:
            counter = 0
            update_status_led()
        await asyncio.sleep(0.01)


# ─── Main ────────────────────────────────────────────────────────────

def main():
    recalculate_gradient()
    leds_off()

    print("=" * 50)
    print("  Lightbar — Plasma 2350 W")
    print("=" * 50)
    print("  LEDs: {}".format(NUM_LEDS))
    print("  Lights: {} (gradient endpoints)".format(NUM_LIGHTS))
    print("  Gradient: polychromatic HSV")
    print("  Fade: easeInOutCirc over {}s".format(FADE_DURATION))
    print("  Color crossfade: {}s".format(COLOR_FADE_DURATION))
    print()

    print("[WiFi]")
    if wifi_connect():
        status_led.set_rgb(0, 3, 0)
    else:
        status_led.set_rgb(5, 2, 0)
        print("  Will keep retrying in background...")

    print()
    print("[Server]")

    loop = asyncio.get_event_loop()
    loop.create_task(http_server())
    loop.create_task(button_and_status_loop())
    loop.create_task(color_fade_loop())
    loop.create_task(wifi_watchdog())
    loop.run_forever()


main()
