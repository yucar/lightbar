# main.py — Lightbar Plasma 2350 W Firmware
#
# Drives 192 WS2812 LEDs with a polychromatic HSV gradient.
# Listens for commands from the XIAO ESP32-C6 over UART (Qw/ST cable).
#
# Button behavior (single BOOT/user button on GP23):
#   Click (off)  → turn on
#   Click (on)   → turn off
#   Click again while on (within RECLICK_WINDOW_MS) → randomize colors
#     (keeps randomizing on each subsequent click while LEDs stay on)
#
# Status LED (very dim, 1-5 per channel):
#   White  → all OK
#   Green  → Matter/Thread issue (reported by ESP32)
#   Orange → ESP32 connectivity lost
#
# Flash with Pimoroni's official MicroPython firmware:
#   https://github.com/pimoroni/plasma/releases/latest

import plasma
from pimoroni import RGBLED
from machine import UART, Pin
import time
import math
import random

from gradient import gradient_2color, gradient_3color

# ─── Configuration ───────────────────────────────────────────────────

NUM_LEDS = 192          # Total LEDs (two 96-LED strips in series)
NUM_LIGHTS = 2          # Virtual lights exposed to Matter (2 or 3) — match ESP32
FPS = 60                # LED refresh rate
FADE_DURATION = 1.0     # Seconds for on/off fade transition
UART_BAUD = 115200      # Serial baud rate

# Button timing
HOLD_THRESHOLD_MS = 600     # ms before a press becomes a "hold"
HOLD_REPEAT_MS = 50         # ms between brightness steps while holding
BRIGHTNESS_STEP = 0.02      # Brightness change per hold tick
MIN_BRIGHTNESS = 0.02       # Don't go fully dark via hold
RECLICK_WINDOW_MS = 2000    # Window after turning on in which a click randomizes colors

# Health timeout
ESP32_HEALTH_TIMEOUT_S = 10  # Seconds without HEALTH msg → orange status

# Default gradient colors (HSV: hue 0.0-1.0, saturation 0.0-1.0, value 0.0-1.0)
DEFAULT_COLOR_1 = (0.6, 1.0, 1.0)    # Blue
DEFAULT_COLOR_2 = (0.85, 1.0, 1.0)   # Purple
DEFAULT_COLOR_3 = (0.0, 1.0, 1.0)    # Red (midpoint, only if NUM_LIGHTS==3)

# ─── Hardware Setup ──────────────────────────────────────────────────

led_strip = plasma.WS2812(NUM_LEDS)
led_strip.start(FPS)

# Plasma 2350 W has a single user button on GP23 (the BOOT/user button)
btn_a_pin = Pin(23, Pin.IN, Pin.PULL_UP)

status_led = RGBLED("LED_R", "LED_G", "LED_B")

# UART1 on GP4 (TX) / GP5 (RX) — exposed via Qw/ST connector
uart = UART(1, baudrate=UART_BAUD, tx=Pin(4), rx=Pin(5))

# ─── State ───────────────────────────────────────────────────────────

is_on = False
brightness = 1.0           # Target brightness (0.0 - 1.0)
current_brightness = 0.0   # Actual brightness (animated during fade)
num_gradient_colors = NUM_LIGHTS  # 2 or 3 color gradient

# Gradient endpoint colors (HSV)
color_1 = list(DEFAULT_COLOR_1)
color_2 = list(DEFAULT_COLOR_2)
color_3 = list(DEFAULT_COLOR_3)

gradient_dirty = True   # Recalculate gradient when colors change
gradient_cache = []     # Pre-computed gradient HSV values

# Button state machine (single button)
btn_a_down = False
btn_a_down_time = 0
btn_a_last_hold_tick = 0
btn_a_was_hold = False

# Tracks when the LEDs were last turned on, so rapid follow-up clicks randomize
btn_last_on_time = 0  # ticks_ms when LEDs were most recently turned on

# Health / status LED
esp32_health = "UNKNOWN"     # OK, MATTER_ISSUE, or UNKNOWN
esp32_last_health_ms = 0     # ticks_ms of last HEALTH message

# ─── Easing: easeInOutCirc ───────────────────────────────────────────

def ease_in_out_circ(t):
    """easeInOutCirc easing function. t in [0, 1] → [0, 1]."""
    if t < 0.5:
        return (1.0 - math.sqrt(1.0 - (2.0 * t) ** 2)) / 2.0
    else:
        return (math.sqrt(1.0 - (-2.0 * t + 2.0) ** 2) + 1.0) / 2.0


# ─── Random Color Generation ────────────────────────────────────────

def random_hue():
    """Generate a random hue value (0.0-1.0)."""
    return random.random()


def randomize_colors():
    """Set gradient colors to random hues with full saturation and value."""
    global gradient_dirty
    color_1[0] = random_hue()
    color_1[1] = 1.0
    color_1[2] = 1.0
    color_2[0] = random_hue()
    color_2[1] = 1.0
    color_2[2] = 1.0
    if num_gradient_colors == 3:
        color_3[0] = random_hue()
        color_3[1] = 1.0
        color_3[2] = 1.0
    gradient_dirty = True


# ─── Gradient ────────────────────────────────────────────────────────

def recalculate_gradient():
    """Recompute the polychromatic gradient and cache it."""
    global gradient_cache, gradient_dirty

    if num_gradient_colors == 3:
        gradient_cache = gradient_3color(
            NUM_LEDS,
            color_1[0], color_1[1], color_1[2],
            color_3[0], color_3[1], color_3[2],  # Midpoint
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


def apply_gradient():
    """Write the cached gradient to the LED strip, scaled by current brightness."""
    for i in range(NUM_LEDS):
        h, s, v = gradient_cache[i]
        led_strip.set_hsv(i, h, s, v * current_brightness)


def leds_off():
    """Turn all LEDs fully off."""
    for i in range(NUM_LEDS):
        led_strip.set_hsv(i, 0, 0, 0)


# ─── Fade Animation (easeInOutCirc) ─────────────────────────────────

def fade_to(target, duration):
    """Smoothly fade current_brightness to target using easeInOutCirc."""
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
        t = step / steps
        t = ease_in_out_circ(t)
        current_brightness = start + (target - start) * t

        if current_brightness <= 0.001:
            leds_off()
        else:
            apply_gradient()

        # Check for UART commands during fade (non-blocking)
        check_uart()

        time.sleep(1.0 / FPS)


# ─── Status LED ──────────────────────────────────────────────────────

def update_status_led():
    """Set the onboard RGB LED based on system health.

    Very dim (values 1-5) to avoid distraction.
    Priority: ESP32 disconnected > Matter issue > all OK.
    (No current sensing on Plasma 2350 W.)
    """
    # Orange: ESP32 connectivity lost
    now = time.ticks_ms()
    if esp32_health == "UNKNOWN" or \
       time.ticks_diff(now, esp32_last_health_ms) > ESP32_HEALTH_TIMEOUT_S * 1000:
        status_led.set_rgb(5, 2, 0)
        return

    # Green: Matter/Thread issue (reported by ESP32)
    if esp32_health == "MATTER_ISSUE":
        status_led.set_rgb(0, 3, 0)
        return

    # White: all OK
    status_led.set_rgb(2, 2, 2)


# ─── UART Protocol ───────────────────────────────────────────────────

def send_response(msg):
    """Send a response line over UART."""
    uart.write((msg + "\n").encode())


def get_status_string():
    """Build status response."""
    state = "ON" if is_on else "OFF"
    c1 = "{:.3f} {:.3f} {:.3f}".format(color_1[0], color_1[1], color_1[2])
    c2 = "{:.3f} {:.3f} {:.3f}".format(color_2[0], color_2[1], color_2[2])
    if num_gradient_colors == 3:
        c3 = "{:.3f} {:.3f} {:.3f}".format(color_3[0], color_3[1], color_3[2])
        return "OK {} BRI {:.3f} COLORS 3 {} {} {}".format(state, brightness, c1, c2, c3)
    else:
        return "OK {} BRI {:.3f} COLORS 2 {} {}".format(state, brightness, c1, c2)


def parse_float(s):
    """Parse a string to float, clamped to 0.0-1.0."""
    try:
        v = float(s)
        return max(0.0, min(1.0, v))
    except (ValueError, TypeError):
        return 0.0


def handle_command(line):
    """Process a single UART command."""
    global is_on, brightness, num_gradient_colors, gradient_dirty
    global esp32_health, esp32_last_health_ms

    parts = line.strip().split()
    if not parts:
        return

    cmd = parts[0].upper()

    if cmd == "ON":
        is_on = True
        if gradient_dirty:
            recalculate_gradient()
        fade_to(brightness, FADE_DURATION)
        send_response("OK ON")

    elif cmd == "OFF":
        is_on = False
        fade_to(0.0, FADE_DURATION)
        send_response("OK OFF")

    elif cmd == "STATUS":
        send_response(get_status_string())

    elif cmd == "BRIGHTNESS" and len(parts) >= 2:
        brightness = parse_float(parts[1])
        if is_on:
            fade_to(brightness, FADE_DURATION * 0.5)
        send_response("OK BRIGHTNESS {:.3f}".format(brightness))

    elif cmd == "COLOR2" and len(parts) >= 7:
        color_1[0] = parse_float(parts[1])
        color_1[1] = parse_float(parts[2])
        color_1[2] = parse_float(parts[3])
        color_2[0] = parse_float(parts[4])
        color_2[1] = parse_float(parts[5])
        color_2[2] = parse_float(parts[6])
        num_gradient_colors = 2
        gradient_dirty = True
        if is_on:
            recalculate_gradient()
            apply_gradient()
        send_response("OK COLOR2")

    elif cmd == "COLOR3" and len(parts) >= 10:
        color_1[0] = parse_float(parts[1])
        color_1[1] = parse_float(parts[2])
        color_1[2] = parse_float(parts[3])
        color_3[0] = parse_float(parts[4])  # Midpoint
        color_3[1] = parse_float(parts[5])
        color_3[2] = parse_float(parts[6])
        color_2[0] = parse_float(parts[7])  # End
        color_2[1] = parse_float(parts[8])
        color_2[2] = parse_float(parts[9])
        num_gradient_colors = 3
        gradient_dirty = True
        if is_on:
            recalculate_gradient()
            apply_gradient()
        send_response("OK COLOR3")

    elif cmd == "PING":
        send_response("OK PONG")

    elif cmd == "HEALTH" and len(parts) >= 2:
        # ESP32 reports its health status periodically
        esp32_health = parts[1].upper()
        esp32_last_health_ms = time.ticks_ms()
        send_response("OK HEALTH")

    else:
        send_response("ERR UNKNOWN {}".format(cmd))


uart_buffer = ""

def check_uart():
    """Non-blocking UART read. Processes complete lines."""
    global uart_buffer

    while uart.any():
        char = uart.read(1)
        if char is None:
            break
        char = char.decode("utf-8", "ignore")
        if char == "\n":
            if uart_buffer.strip():
                handle_command(uart_buffer)
            uart_buffer = ""
        else:
            uart_buffer += char
            # Prevent buffer overflow
            if len(uart_buffer) > 256:
                uart_buffer = ""


# ─── Button State Machine ───────────────────────────────────────────

def update_buttons():
    """Handle the single BOOT/user button (GP23) with click vs. long-press.

    Click (off)  → turn on
    Click (on)   → turn off
                   UNLESS within RECLICK_WINDOW_MS of the last turn-on,
                   in which case → randomize colors (keeps cycling on each click)
    Hold         → increase brightness (while on)
    """
    global is_on, brightness, current_brightness
    global btn_a_down, btn_a_down_time, btn_a_last_hold_tick, btn_a_was_hold
    global btn_last_on_time
    global gradient_dirty

    now = time.ticks_ms()

    # Button is active-low (pressed = 0)
    a_pressed = btn_a_pin.value() == 0

    # ── Button ──
    if a_pressed and not btn_a_down:
        # Just pressed
        btn_a_down = True
        btn_a_down_time = now
        btn_a_last_hold_tick = now
        btn_a_was_hold = False

    elif a_pressed and btn_a_down:
        # Held down — check if past hold threshold
        held_ms = time.ticks_diff(now, btn_a_down_time)
        if held_ms >= HOLD_THRESHOLD_MS:
            btn_a_was_hold = True
            tick_ms = time.ticks_diff(now, btn_a_last_hold_tick)
            if tick_ms >= HOLD_REPEAT_MS:
                btn_a_last_hold_tick = now
                # Increase brightness (only when on)
                if is_on:
                    brightness = min(1.0, brightness + BRIGHTNESS_STEP)
                    current_brightness = brightness
                    apply_gradient()
                    send_response("OK BRIGHTNESS {:.3f}".format(brightness))

    elif not a_pressed and btn_a_down:
        # Just released
        btn_a_down = False
        if not btn_a_was_hold:
            # Single click
            if not is_on:
                # ── Turn on ──
                is_on = True
                btn_last_on_time = now
                if gradient_dirty:
                    recalculate_gradient()
                fade_to(brightness, FADE_DURATION)
                send_response("OK ON")
            else:
                # Already on — decide: turn off or randomize?
                since_on_ms = time.ticks_diff(now, btn_last_on_time)
                if since_on_ms <= RECLICK_WINDOW_MS:
                    # ── Randomize colors ──
                    # Reset the window so each follow-up click also randomizes
                    btn_last_on_time = now
                    randomize_colors()
                    recalculate_gradient()
                    apply_gradient()
                    send_response(get_status_string())
                else:
                    # ── Turn off ──
                    is_on = False
                    fade_to(0.0, FADE_DURATION)
                    send_response("OK OFF")


# ─── Main Loop ───────────────────────────────────────────────────────

# Status LED update counter (don't read ADC every loop)
_status_counter = 0
_STATUS_INTERVAL = 50  # Every 50 loops ≈ 500ms at 100Hz

def main():
    global _status_counter

    # Initial gradient calculation
    recalculate_gradient()
    leds_off()
    update_status_led()

    print("Lightbar Plasma 2350 W ready")
    print("  LEDs: {}".format(NUM_LEDS))
    print("  Lights: {} (gradient endpoints)".format(NUM_LIGHTS))
    print("  UART: GP4(TX)/GP5(RX) @ {}".format(UART_BAUD))
    print("  Fade: easeInOutCirc over {}s".format(FADE_DURATION))
    print("  Gradient: polychromatic HSV")
    print("  Waiting for commands...")

    send_response("OK READY")

    while True:
        # ── Buttons ──
        update_buttons()

        # ── UART commands ──
        check_uart()

        # ── Status LED (periodic) ──
        _status_counter += 1
        if _status_counter >= _STATUS_INTERVAL:
            _status_counter = 0
            update_status_led()

        time.sleep(0.01)  # 100 Hz poll rate


main()
