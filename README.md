# Lightbar
<!-- Version: 2.0.0 -->

**Smart LED gradient light — single board, WiFi, Apple Home / Google / Alexa via Matter**

---

## What It Is

A single-board smart light that displays a smooth polychromatic HSV gradient
across two 1-metre WS2812 LED strips (192 LEDs total). Controlled via
Apple Home, Google Home, or Amazon Alexa through **Matter** using
[Matterbridge](https://github.com/Luligu/matterbridge) with the
[matterbridge-webhooks](https://github.com/Luligu/matterbridge-webhooks) plugin.

## Hardware

| Component | Role |
|---|---|
| **Pimoroni Plasma 2350 W** | LED driver + WiFi REST server (RP2350 + CYW43439) |
| **2× WS2812 LED strips** | 1 m / 96 RGB LEDs each, in series (192 total) |
| **Raspberry Pi** | Runs Matterbridge Docker container |

One USB-C cable powers everything on the Plasma side.

## Architecture

```
                    USB-C (power + programming)
                         │
              ┌──────────┴──────────┐
              │  Pimoroni Plasma    │
              │     2350 W          │
              │  RP2350 + CYW43439  │
 LED strips ◄─┤  Screw terminals    │
              │  REST API over WiFi │
              └──────────┬──────────┘
                         │ HTTP
                    Home WiFi
                         │
              ┌──────────┴──────────┐
              │    Raspberry Pi     │
              │  Docker container   │
              │  Matterbridge +     │
              │  webhooks plugin    │
              │                     │
              │  → Apple Home       │
              │  → Google Home      │
              │  → Alexa            │
              └─────────────────────┘
```

## Features

- **On/Off** via Apple Home, Siri, Google Assistant, Alexa, or physical button
- **Smooth fade** transitions (easeInOutCirc, 1 s)
- **Colour crossfade** — smooth 500 ms transition between colour changes
- **2-colour gradient** — pick a colour for each end of the strip
- **Polychromatic HSV** — hue travels forward around the colour wheel
- **Local control** — button A works without network
- **REST API** — full HTTP control over WiFi
- **Matter via Matterbridge** — works with Apple Home, Google Home, Alexa

## REST API

| Method | Path | Body / Params | Description |
|---|---|---|---|
| `GET` | `/status` | — | Current state |
| `GET` | `/info` | — | Device info + endpoints |
| `POST` | `/on` | — | Turn on with fade |
| `POST` | `/off` | — | Turn off with fade |
| `POST` | `/toggle` | — | Toggle on/off |
| `POST` | `/brightness` | `?value=0-100` or `{"value":0-1}` | Set brightness |
| `POST` | `/color` | `?idx=N&h=0-360&s=0-100` | Set gradient endpoint colour (hue/sat) |
| `POST` | `/color` | `?idx=N&r=0-255&g=0-255&b=0-255` | Set gradient endpoint colour (RGB) |
| `POST` | `/color` | `{"colors":[{"h":H,"s":S,"v":V},...]}` | Set full gradient (JSON body) |
| `POST` | `/randomize` | — | Randomize gradient colours |

### Examples

```bash
# Turn on
curl -X POST http://lightbar.local/on

# Set blue-to-purple gradient
curl -X POST 'http://lightbar.local/color?idx=0&h=240&s=100'
curl -X POST 'http://lightbar.local/color?idx=1&h=300&s=100'

# Brightness to 60%
curl -X POST 'http://lightbar.local/brightness?value=60'

# Check status
curl http://lightbar.local/status
```

## Button Controls

| Button | Action | Effect |
|---|---|---|
| **A** click (off) | Turn on | Fades to current gradient |
| **A** click (on, within 2s of turning on) | Randomize | New random gradient colours |
| **A** click (on, after 2s) | Turn off | Fades to black |
| **A** hold | Brightness up | Increases while held |

## Status LED

| Colour | Meaning |
|---|---|
| Blue pulse | Connecting to WiFi |
| Green | Connected, all OK |
| Orange | WiFi disconnected (retrying) |

## File Structure

```
lightbar/
├── README.md                          ← this file (v2.0.0)
├── RESEARCH-Plasma2350W.md            ← hardware research & options analysis
├── plasma2350w/                       ← Plasma 2350 W firmware (MicroPython)
│   ├── main.py                        ← v1.5.0 — LED driver + WiFi + REST API
│   ├── gradient.py                    ← v1.1.0 — HSV gradient math
│   └── secrets.py                     ← v1.0.0 — WiFi credentials (edit before flashing)
├── bridge/                            ← Matterbridge bridge for Raspberry Pi
│   ├── docker-compose.yml             ← v1.2.0 — Docker deployment
│   ├── .env                           ← v1.1.0 — Plasma IP + display name
│   └── setup.sh                       ← v1.1.0 — One-time config setup script
├── plasma/                            ← (legacy) Plasma 2040 firmware
├── esp32c6/                           ← (legacy) ESP32-C6 Matter firmware
├── wiring/
│   └── wiring.md                      ← v2.0.0 — wiring diagram
└── docs/
    └── setup.md                       ← v2.0.0 — full setup guide
```

## Quick Start

### 1. Flash the Plasma 2350 W

1. Download Pimoroni MicroPython for **Plasma 2350 W**:
   https://github.com/pimoroni/plasma/releases/latest
2. Hold BOOT, tap RESET → drag `.uf2` onto the `RP2350` drive
3. Edit `secrets.py` with your WiFi credentials (static IP recommended)
4. Copy `main.py`, `gradient.py`, `secrets.py` to the Plasma via Thonny

### 2. Set Up Matterbridge on Raspberry Pi

See **[docs/setup.md](docs/setup.md)** for the full step-by-step guide.

Short version:

```bash
# Create data dirs
mkdir -p ~/Matterbridge ~/.matterbridge ~/.mattercert

# Write config files (see docs/setup.md for full content)
# Then start:
cd ~/lightbar-bridge
sudo docker compose up -d

# Add the plugin, apply patches, restart
sudo docker exec -it matterbridge matterbridge --docker --add matterbridge-webhooks
# (apply bug patches — see docs/setup.md Step 3.5)
sudo docker compose restart
```

### 3. Pair with Apple Home

1. Open Matterbridge web UI → **http://\<pi-ip\>:8283**
2. Scan the QR code with the Apple Home app
3. **"Lightbar Start"** and **"Lightbar End"** appear as lights
4. Group them in Apple Home for unified control (optional)

## Status

- [x] Hardware: Plasma 2350 W single-board design
- [x] Firmware: LED driving + PIO WS2812
- [x] Firmware: WiFi + REST API
- [x] Firmware: Button A control (on/off/randomize/brightness)
- [x] Firmware: Status LED
- [x] Firmware: Smooth fade (easeInOutCirc, 1 s)
- [x] Firmware: Colour crossfade (500 ms)
- [x] Firmware: Polychromatic gradient (2-colour)
- [x] Bridge: Matterbridge + webhooks plugin (Docker on Pi)
- [x] Bridge: On/Off working via Apple Home
- [x] Bridge: Brightness working via Apple Home
- [x] Bridge: Colour working via Apple Home
- [x] Apple Home pairing tested ✅
- [ ] Google Home pairing tested
- [ ] 3-colour gradient via Apple Home
