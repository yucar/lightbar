# Lightbar
<!-- Version: 3.0.0 -->

**Smart LED gradient light — single board, WiFi, Home Assistant + Apple Home**

---

## What It Is

A single-board smart light that displays a smooth polychromatic HSV gradient
across two 1-metre WS2812 LED strips (192 LEDs total). The gradient runs
between **virtual lights** ("Start" and "End" by default). Each one has its own
on/off, **brightness** and colour, and the strip blends smoothly from one to the
next in both colour and brightness.

It connects to **Home Assistant** over MQTT and is created there automatically
(MQTT discovery). HA's **built-in HomeKit Bridge** then puts it in
**Apple Home / Siri**. No add-ons, custom components or patched plugins are
needed.

## Hardware

| Component | Role |
|---|---|
| **Pimoroni Plasma 2350 W** | LED driver + WiFi + MQTT client (RP2350 + CYW43439) |
| **2× WS2812 LED strips** | 1 m / 96 RGB LEDs each, in series (192 total) |
| **Raspberry Pi** (or any Linux box with Docker) | Runs Home Assistant + Mosquitto via Docker Compose |

## Architecture

```
 LED strips ◄── Plasma 2350 W ──MQTT──► Mosquitto ◄──► Home Assistant ──HomeKit──► Apple Home
                (button, REST)   WiFi   └──────── Docker Compose on the Pi ───────┘
```

- **Two-way state.** Every change is published back to HA, including the
  physical button and REST calls, so HA and Apple Home always show what the
  strip is really doing.
- **Availability.** If the Plasma loses power or WiFi, the broker marks it
  *offline* in HA (MQTT Last Will).
- **Restores after a power cut.** State is saved to flash; `POWER_ON` in
  `config.py` picks what happens at boot.

### Why not Matter?

Home Assistant's Matter support is a **controller** only. From the official
docs: *"Home Assistant is not a bridge itself and it cannot turn existing
devices within Home Assistant into Matter compatible devices."* Publishing HA
entities over Matter needs an extra bridge (Matterbridge, Home Assistant Matter
Hub). For Apple Home, HA's built-in HomeKit Bridge does the same job with no
extras, so this project uses it. See [docs/setup.md](docs/setup.md#google-home--alexa)
for Google Home / Alexa.

## Entities in Home Assistant

| Entity | Controls |
|---|---|
| `light.lightbar` | All lights: on/off, and brightness scaled proportionally (ratios kept) |
| `light.lightbar_start` | Start of the strip: on/off, brightness, colour |
| `light.lightbar_end` | End of the strip: on/off, brightness, colour |
| `button.lightbar_randomize` | New random gradient |

Turning one light off (or dimming it) fades that end of the strip smoothly
while the other end stays lit.

## Button A

| Action | Effect |
|---|---|
| Click (off) | All lights on (1 s fade) |
| Click (on, within 2 s of turning on) | Randomize gradient colours |
| Click (on, after 2 s) | All lights off |
| Hold | Dim. The direction alternates with each hold; from off it starts at minimum and brightens |

## Status LED

| Colour | Meaning |
|---|---|
| Blue pulse | Connecting to WiFi |
| Orange | WiFi disconnected (retrying) |
| Magenta | WiFi OK, MQTT broker unreachable |
| Green | All OK |

## REST API (optional, local)

For scripts and debugging. When `API_TOKEN` is set in `secrets.py`, every
request needs `Authorization: Bearer <token>`. Changes are **POST only**.

| Method | Path | Params (query or JSON body) | Description |
|---|---|---|---|
| `GET` | `/status` | — | Full state |
| `GET` | `/info` | — | Device info |
| `POST` | `/on` · `/off` · `/toggle` | `light=N` (optional) | All lights, or light N |
| `POST` | `/brightness` | `value=0-100`, `light=N` (optional) | Without `light`: scales all |
| `POST` | `/color` | `light=N` + `h=0-360&s=0-100` **or** `r,g,b=0-255` | Set a light's colour |
| `POST` | `/randomize` | — | Random gradient |

```bash
T="Authorization: Bearer <API_TOKEN>"
curl -X POST -H "$T" 'http://lightbar.local/on'
curl -X POST -H "$T" 'http://lightbar.local/brightness?light=1&value=30'   # End at 30 %
curl -X POST -H "$T" 'http://lightbar.local/color?light=0&h=240&s=100'     # Start blue
curl -H "$T" http://lightbar.local/status
```

## File Structure

```
lightbar/
├── README.md                    ← this file
├── plasma2350w/                 ← firmware (Pimoroni MicroPython)
│   ├── main.py                  ← boot entry point
│   ├── app.py                   ← wiring: WiFi, button, status LED, tasks
│   ├── config.py                ← settings: LEDs, light names, timings, MQTT host
│   ├── secrets.example.py       ← copy to secrets.py: WiFi / MQTT / API token
│   ├── lightbar.py              ← light state, crossfade renderer, save/restore
│   ├── gradient.py              ← gradient + blend maths (flat float buffers)
│   ├── ha.py                    ← Home Assistant MQTT discovery + commands
│   ├── mqtt.py                  ← tiny non-blocking MQTT 3.1.1 client
│   └── http_api.py              ← local REST API
├── hub/                         ← Docker Compose: Home Assistant + Mosquitto
│   ├── docker-compose.yml
│   ├── .env.example             ← copy to .env: every setting lives here
│   ├── mosquitto/               ← broker config + entrypoint (users/ACL from .env)
│   └── homeassistant/configuration.yaml
├── tests/                       ← host tests (python3 -m unittest discover -s tests)
├── wiring/wiring.md
├── docs/setup.md                ← full setup guide
├── plasma/                      ← (legacy) Plasma 2040 firmware
└── esp32c6/                     ← (legacy) ESP32-C6 Matter firmware
```

## Quick Start

Full guide: **[docs/setup.md](docs/setup.md)**

```bash
# 1. Hub (on the Pi)
cd hub
cp .env.example .env && nano .env        # set the two MQTT passwords
docker compose up -d                     # → http://<pi-ip>:8123

# 2. Firmware
cp plasma2350w/secrets.example.py plasma2350w/secrets.py   # WiFi + MQTT_PASSWORD
# edit plasma2350w/config.py → MQTT_HOST = "<pi-ip>"
mpremote cp plasma2350w/*.py : + reset    # copies secrets.py too

# 3. In HA: add the MQTT integration (127.0.0.1, MQTT_HA_USER / MQTT_HA_PASSWORD),
#    restart HA once, then scan the HomeKit QR code from HA's notifications.
```

## Development

```bash
sudo apt install mosquitto mosquitto-clients   # optional: enables the MQTT tests
python3 -m unittest discover -s tests -v
```

The tests run the firmware under CPython with stand-ins for the hardware
modules. They cover the gradient maths, per-light brightness and fades, the
button state machine, the REST API (auth, validation) and MQTT discovery and
commands against a real Mosquitto broker.

## Status

- [x] Firmware: per-light on/off, brightness and colour with smooth blending
- [x] Firmware: non-blocking crossfades (any change, even mid-fade)
- [x] Firmware: MQTT + Home Assistant discovery, two-way state, availability
- [x] Firmware: state saved to flash, configurable power-on behaviour
- [x] Firmware: authenticated, POST-only REST API
- [x] Hub: Docker Compose (HA + Mosquitto with per-user ACLs), all config in `.env`
- [x] Apple Home via HA HomeKit Bridge
- [ ] Google Home / Alexa (possible through HA; not tested)
- [ ] Tested on real Plasma hardware after the v2 firmware rewrite
