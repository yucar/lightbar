#!/usr/bin/env python3
"""Generate a color-coded wiring schematic for the Lightbar project."""

from PIL import Image, ImageDraw, ImageFont
import os

W, H = 1400, 900
BG = (24, 24, 32)
WHITE = (240, 240, 240)
GRAY = (120, 120, 130)
DARK_GRAY = (60, 60, 70)

# Wire colors
BLACK_WIRE = (40, 40, 40)
RED_WIRE = (220, 50, 50)
BLUE_WIRE = (60, 120, 220)
YELLOW_WIRE = (230, 200, 50)
GREEN_WIRE = (50, 200, 80)
ORANGE_WIRE = (240, 150, 30)

# Board colors
PLASMA_BG = (35, 55, 80)
PLASMA_BORDER = (60, 100, 160)
XIAO_BG = (55, 35, 70)
XIAO_BORDER = (120, 60, 160)
LED_BG = (30, 50, 30)
LED_BORDER = (60, 120, 60)
USB_COLOR = (80, 80, 90)

img = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(img)

# Try to get a decent font
font_path = None
for fp in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
    if os.path.exists(fp):
        font_path = fp
        break

def make_font(size):
    if font_path:
        return ImageFont.truetype(font_path, size)
    return ImageFont.load_default()

title_font = make_font(28)
board_font = make_font(18)
pin_font = make_font(14)
label_font = make_font(12)
small_font = make_font(11)

# ── Title ──
draw.text((W // 2, 30), "LIGHTBAR — Wiring Schematic", fill=WHITE,
          font=title_font, anchor="mt")
draw.text((W // 2, 62), "Color-coded Qw/ST cable connections",
          fill=GRAY, font=label_font, anchor="mt")

# ── Plasma 2040 Board ──
px, py = 100, 180
pw, ph = 380, 320
draw.rounded_rectangle([px, py, px + pw, py + ph], radius=12,
                        fill=PLASMA_BG, outline=PLASMA_BORDER, width=3)
draw.text((px + pw // 2, py + 20), "Pimoroni Plasma 2040",
          fill=WHITE, font=board_font, anchor="mt")
draw.text((px + pw // 2, py + 45), "(RP2040)", fill=GRAY,
          font=label_font, anchor="mt")

# USB-C on Plasma
ux, uy = px + pw // 2 - 40, py - 15
draw.rounded_rectangle([ux, uy, ux + 80, uy + 18], radius=4,
                        fill=USB_COLOR, outline=(140, 140, 150), width=2)
draw.text((ux + 40, uy + 9), "USB-C", fill=WHITE, font=small_font, anchor="mm")
draw.text((ux + 40, uy - 12), "⚡ Power Input", fill=ORANGE_WIRE,
          font=small_font, anchor="mm")

# Qw/ST connector (right side of Plasma)
qx, qy = px + pw - 10, py + 100
draw.rounded_rectangle([qx - 50, qy - 15, qx + 5, qy + 75], radius=6,
                        fill=(40, 50, 65), outline=(100, 140, 200), width=2)
draw.text((qx - 22, qy - 28), "Qw/ST", fill=(100, 180, 255),
          font=pin_font, anchor="mm")

# Pin labels on Qw/ST
qw_pins = [
    ("GND", BLACK_WIRE, 0),
    ("3V3", RED_WIRE, 20),
    ("SDA/GP4", BLUE_WIRE, 40),
    ("SCL/GP5", YELLOW_WIRE, 60),
]
for label, color, offset in qw_pins:
    y = qy + offset
    draw.ellipse([qx - 8, y - 4, qx, y + 4], fill=color, outline=WHITE, width=1)
    draw.text((qx - 42, y), label, fill=color, font=small_font, anchor="rm")

# Screw terminals (left side of Plasma)
sx, sy = px + 10, py + 200
draw.rounded_rectangle([sx, sy, sx + 90, sy + 80], radius=4,
                        fill=(40, 50, 40), outline=(80, 120, 80), width=2)
draw.text((sx + 45, sy - 12), "Screw Terminals", fill=GREEN_WIRE,
          font=small_font, anchor="mm")
terms = [("DA", GREEN_WIRE, 0), ("5V", RED_WIRE, 20), ("GND", BLACK_WIRE, 40)]
for label, color, offset in terms:
    y = sy + 15 + offset
    draw.rounded_rectangle([sx + 5, y - 6, sx + 20, y + 6], radius=2,
                            fill=color)
    draw.text((sx + 28, y), label, fill=color, font=small_font, anchor="lm")

# Buttons
draw.rounded_rectangle([px + 140, py + 260, px + 180, py + 290], radius=4,
                        fill=(60, 70, 80), outline=GRAY, width=1)
draw.text((px + 160, py + 275), "A", fill=WHITE, font=small_font, anchor="mm")
draw.rounded_rectangle([px + 200, py + 260, px + 240, py + 290], radius=4,
                        fill=(60, 70, 80), outline=GRAY, width=1)
draw.text((px + 220, py + 275), "B", fill=WHITE, font=small_font, anchor="mm")

# ── XIAO ESP32-C6 Board ──
xx, xy = 830, 200
xw, xh = 340, 280
draw.rounded_rectangle([xx, xy, xx + xw, xy + xh], radius=12,
                        fill=XIAO_BG, outline=XIAO_BORDER, width=3)
draw.text((xx + xw // 2, xy + 20), "XIAO ESP32-C6",
          fill=WHITE, font=board_font, anchor="mt")
draw.text((xx + xw // 2, xy + 45), "(Matter / Thread / WiFi 6)",
          fill=GRAY, font=label_font, anchor="mt")

# USB-C on XIAO (for programming only)
ux2 = xx + xw // 2 - 40
uy2 = xy - 15
draw.rounded_rectangle([ux2, uy2, ux2 + 80, uy2 + 18], radius=4,
                        fill=(50, 50, 55), outline=(90, 90, 95), width=2)
draw.text((ux2 + 40, uy2 + 9), "USB-C", fill=GRAY, font=small_font, anchor="mm")
draw.text((ux2 + 40, uy2 - 12), "(programming only)", fill=GRAY,
          font=small_font, anchor="mm")

# XIAO pin labels (left side, matching Qw/ST cable)
xiao_pins = [
    ("GND", BLACK_WIRE, 100),
    ("3V3", RED_WIRE, 130),
    ("D7/RX (GPIO17)", BLUE_WIRE, 160),
    ("D6/TX (GPIO16)", YELLOW_WIRE, 190),
]
for label, color, offset in xiao_pins:
    y = xy + offset
    draw.ellipse([xx + 8, y - 4, xx + 16, y + 4], fill=color, outline=WHITE, width=1)
    draw.text((xx + 24, y), label, fill=color, font=pin_font, anchor="lm")

# ── Qw/ST Cable Wires (Plasma → XIAO) ──
wire_specs = [
    (BLACK_WIRE, qy + 0, xy + 100, "GND", 4),
    (RED_WIRE, qy + 20, xy + 130, "3V3 (power)", 4),
    (BLUE_WIRE, qy + 40, xy + 160, "TX → RX (data)", 4),
    (YELLOW_WIRE, qy + 60, xy + 190, "RX ← TX (data)", 4),
]

for color, y_start, y_end, label, width in wire_specs:
    # Wire from Plasma Qw/ST to XIAO
    x_start = qx + 5
    x_end = xx + 8
    mid_x = (x_start + x_end) // 2

    # Curved wire path
    points = []
    steps = 40
    for i in range(steps + 1):
        t = i / steps
        # Bezier-like curve
        cx = x_start + (x_end - x_start) * t
        cy = y_start + (y_end - y_start) * t
        # Add slight curve
        curve = 20 * (4 * t * (1 - t))  # Parabolic bulge
        cy -= curve
        points.append((cx, cy))

    for i in range(len(points) - 1):
        draw.line([points[i], points[i + 1]], fill=color, width=width)

    # Wire label
    draw.text((mid_x, (y_start + y_end) // 2 - 28), label,
              fill=color, font=small_font, anchor="mm")

# ── LED Strips ──
lx, ly = 50, 600
lw, lh = 550, 80
draw.rounded_rectangle([lx, ly, lx + lw, ly + lh], radius=8,
                        fill=LED_BG, outline=LED_BORDER, width=2)

# Rainbow gradient inside to represent LEDs
for i in range(lw - 20):
    t = i / (lw - 20)
    # Blue to purple gradient
    r = int(60 + 140 * t)
    g = int(60 - 40 * t)
    b = int(220 - 20 * t)
    x = lx + 10 + i
    draw.line([(x, ly + 25), (x, ly + 55)], fill=(r, g, b), width=1)

draw.text((lx + lw // 2, ly + 12), "2× WS2812 LED Strips (192 LEDs total)",
          fill=WHITE, font=pin_font, anchor="mt")
draw.text((lx + 10, ly + 65), "Strip 1 (96 LEDs)", fill=GREEN_WIRE,
          font=small_font, anchor="lm")
draw.text((lx + lw - 10, ly + 65), "Strip 2 (96 LEDs)", fill=GREEN_WIRE,
          font=small_font, anchor="rm")
draw.text((lx + lw // 2, ly + 65), "→ daisy-chained →", fill=GRAY,
          font=small_font, anchor="mm")

# Wires from screw terminals to LED strip
led_wires = [
    (GREEN_WIRE, "DA", sx + 12, sy + 15, lx + 40, ly),
    (RED_WIRE, "5V", sx + 12, sy + 35, lx + 80, ly),
    (BLACK_WIRE, "GND", sx + 12, sy + 55, lx + 120, ly),
]
for color, label, x1, y1, x2, y2 in led_wires:
    # Vertical down then horizontal
    mid_y = (y1 + y2) // 2 + 20
    draw.line([(x1, y1 + 6), (x1, mid_y)], fill=color, width=3)
    draw.line([(x1, mid_y), (x2, mid_y)], fill=color, width=3)
    draw.line([(x2, mid_y), (x2, y2)], fill=color, width=3)

# ── Legend ──
legend_x, legend_y = 750, 580
draw.rounded_rectangle([legend_x, legend_y, legend_x + 580, legend_y + 200],
                        radius=10, fill=(30, 30, 40), outline=DARK_GRAY, width=2)
draw.text((legend_x + 290, legend_y + 15), "Wire Legend",
          fill=WHITE, font=board_font, anchor="mt")

legend_items = [
    (BLACK_WIRE, "Black — GND (common ground)"),
    (RED_WIRE, "Red — 3.3V power (Plasma → XIAO)"),
    (BLUE_WIRE, "Blue — UART TX: Plasma GP4 → XIAO D7/RX"),
    (YELLOW_WIRE, "Yellow — UART RX: XIAO D6/TX → Plasma GP5"),
    (GREEN_WIRE, "Green — LED data (DA screw terminal)"),
]

for i, (color, text) in enumerate(legend_items):
    y = legend_y + 45 + i * 28
    draw.rounded_rectangle([legend_x + 20, y - 5, legend_x + 50, y + 5],
                            radius=3, fill=color, outline=WHITE, width=1)
    draw.text((legend_x + 60, y), text, fill=WHITE, font=pin_font, anchor="lm")

# ── Protocol info ──
draw.text((xx + xw // 2, xy + xh - 30), "UART @ 115200 baud",
          fill=(150, 130, 200), font=pin_font, anchor="mm")

# ── Apple Home indicator ──
draw.text((xx + xw - 20, xy + xh + 20), "→ Apple Home (via Thread/WiFi)",
          fill=(150, 130, 200), font=pin_font, anchor="rm")

# ── Save ──
out = "/home/openclaw/.openclaw/workspace/lightbar/docs/Lightbar-Wiring-Schematic.png"
img.save(out, "PNG", dpi=(150, 150))
print(f"Saved: {out}")
print(f"Size: {img.size}")
