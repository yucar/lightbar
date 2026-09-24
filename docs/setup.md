# Lightbar — Setup Guide
<!-- Version: 3.0.0 -->

**Single-board WiFi LED gradient light: Home Assistant (MQTT) + Apple Home (HomeKit Bridge)**

---

## What You Need

### Hardware

| Item | Notes |
|---|---|
| **Pimoroni Plasma 2350 W** | [shop.pimoroni.com](https://shop.pimoroni.com/products/plasma-2350-w) |
| **2× WS2812 LED strips** | 1 m / 96 LEDs each (192 total) |
| **USB-C cable** | Data + power capable |
| **Raspberry Pi** | Pi 4 / Pi 5 (64-bit OS) or any Linux machine with Docker |

### Software

| Item | Notes |
|---|---|
| **Pimoroni MicroPython** | `.uf2` for Plasma 2350 W (NOT the generic RP2350) |
| **mpremote** or **Thonny** | To copy files to the Plasma (`pip install mpremote`) |
| **Docker + Docker Compose** | On the Pi |

---

## Architecture

```
┌──────────────────┐        WiFi / MQTT        ┌─────────────── Raspberry Pi (Docker Compose) ──────────────┐
│  Plasma 2350 W   │ ────────────────────────► │  Mosquitto  ◄──►  Home Assistant  ── HomeKit Bridge ──►    │──► Apple Home / Siri
│  LEDs · button   │ ◄──────────────────────── │  (users+ACL)       (MQTT discovery)                        │
└──────────────────┘   commands / state        └────────────────────────────────────────────────────────────┘
```

Nothing is installed into Home Assistant: the Lightbar announces itself through
MQTT discovery, and HomeKit Bridge is part of HA's core.

---

## Step 1: Wire the LED Strips

Connect both strips **in series** to the Plasma 2350 W screw terminals
(**DAT** → DIN, **5V** → VCC, **GND** → GND; strip 1 DOUT → strip 2 DIN).
Details and power notes: [wiring/wiring.md](../wiring/wiring.md).

---

## Step 2: Start the Hub (Raspberry Pi)

### 2.1 — Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER      # log out and back in afterwards
```

### 2.2 — Configure

Copy the `hub/` folder to the Pi, then:

```bash
cd hub
cp .env.example .env
nano .env
```

Every setting lives in `.env`:

| Variable | Purpose |
|---|---|
| `HA_VERSION` | Home Assistant image tag. `stable`, or pin a release such as `2026.9.3` |
| `MOSQUITTO_VERSION` | Mosquitto image tag (default `2`) |
| `TZ` | Time zone, e.g. `Europe/Madrid` |
| `MQTT_PORT` | Broker port on the Pi (default `1883`) |
| `MQTT_HA_USER` / `MQTT_HA_PASSWORD` | Home Assistant's broker login |
| `MQTT_DEVICE_USER` / `MQTT_DEVICE_PASSWORD` | The Lightbar's login. It may only use its own topics |
| `MQTT_TOPIC_PREFIX` | Must match `config.py` (default `lightbar`) |
| `HOMEKIT_NAME` / `HOMEKIT_PORT` | Name and port of the bridge in Apple Home |
| `HOMEKIT_ENTITY_GLOB` | Which HA entities go to Apple Home (default `light.lightbar*`) |

The broker **refuses to start** while a password is still `change-me`.
Use long random passwords, e.g. `openssl rand -base64 18`.

### 2.3 — Start

```bash
docker compose up -d
docker compose ps          # mosquitto should be "healthy"
```

To change a setting later, edit `.env` and run `docker compose up -d` again.
Broker users and ACLs are regenerated on every start.

### 2.4 — Home Assistant onboarding

1. Open **http://\<pi-ip\>:8123** and create your user.
2. **Settings → Devices & services → Add integration → MQTT**
   - Broker: `127.0.0.1` · Port: your `MQTT_PORT`
   - Username / password: `MQTT_HA_USER` / `MQTT_HA_PASSWORD` from `.env`

---

## Step 3: Flash the Plasma Firmware

### 3.1 — MicroPython

1. Download the **Plasma 2350 W** `.uf2` from
   https://github.com/pimoroni/plasma/releases/latest
2. Hold **BOOT**, tap **RESET** → drag the `.uf2` onto the `RP2350` drive.

### 3.2 — Configure

```bash
cp plasma2350w/secrets.example.py plasma2350w/secrets.py
```

`secrets.py` (never committed):

| Setting | Value |
|---|---|
| `WIFI_SSID` / `WIFI_PASSWORD` | 2.4 GHz network |
| `MQTT_USER` / `MQTT_PASSWORD` | `MQTT_DEVICE_USER` / `MQTT_DEVICE_PASSWORD` from `hub/.env` |
| `API_TOKEN` | Any long random string; protects the local REST API (`None` = open) |
| `STATIC_IP` … | Optional static IP |

`config.py`: set **`MQTT_HOST`** to the Pi's IP. Everything else is optional:

| Setting | Default | Notes |
|---|---|---|
| `LIGHT_NAMES` | `("Start", "End")` | One virtual light per name, evenly spaced. 3 names = start/middle/end |
| `DEFAULT_COLORS` | blue → purple | `(hue, sat)` per light, used until changed |
| `EXPOSE_ALL_LIGHT` | `True` | Extra "Lightbar" light controlling all of them |
| `FADE_S` / `BRIGHTNESS_FADE_S` / `COLOR_FADE_S` | 1.0 / 0.5 / 0.5 | Transition times (HA can override per command) |
| `POWER_ON` | `"restore"` | `"off"`, `"on"` or `"restore"` after a power cut |
| `MAX_BRIGHTNESS` | `1.0` | Global cap for the 3 A USB-C power budget |
| `HTTP_ENABLED` | `True` | Turn the REST API off completely |

### 3.3 — Copy to the board

```bash
mpremote cp plasma2350w/*.py : + reset
```

(Or upload every `.py` in `plasma2350w/` with Thonny: `main.py`, `app.py`,
`config.py`, `secrets.py`, `lightbar.py`, `gradient.py`, `ha.py`, `mqtt.py`,
`http_api.py`.)

### 3.4 — Verify

Serial console (`mpremote repl`):

```
==================================================
  Lightbar 2.0.0 — Plasma 2350 W
==================================================
  LEDs: 192   Lights: Start, End
  Device id: lightbar_a1b2c3
  MQTT broker: 192.168.1.10:1883
  REST API on port 80
[WiFi] Connected, IP 192.168.1.161
[MQTT] Connected to 192.168.1.10:1883
```

The status LED turns **green**. In HA, **Settings → Devices & services → MQTT**
now shows a **Lightbar** device with `light.lightbar`, `light.lightbar_start`,
`light.lightbar_end` and `button.lightbar_randomize`.

---

## Step 4: Pair with Apple Home

1. **Restart Home Assistant once** after the Lightbar entities first appear
   (Settings → ⋮ → Restart). HomeKit Bridge only picks up entities that exist
   when it starts. Later restarts don't need this.
2. Open HA's **Notifications** (bell icon) → *HomeKit Pairing* shows a QR code.
3. iPhone **Home** app → **+** → **Add Accessory** → scan it.
4. **Lightbar**, **Lightbar Start** and **Lightbar End** appear as lights.

The iPhone and the Pi must be on the same network / VLAN (HomeKit uses mDNS).
For control away from home you need an Apple home hub (HomePod / Apple TV).

Don't want the "all" light in Apple Home? Set `EXPOSE_ALL_LIGHT = False` in
`config.py`, or narrow `HOMEKIT_ENTITY_GLOB` in `.env`.

### Google Home / Alexa

HA can serve these without extra software through its built-in
`google_assistant` / `alexa` integrations. They need HA reachable over HTTPS
from the internet, or a Home Assistant Cloud (Nabu Casa) subscription, which
does it in a few clicks. HA cannot expose its entities over **Matter** by
itself. That needs a separate bridge such as Matterbridge (with its HA plugin)
or Home Assistant Matter Hub.

---

## Step 5: Use It

### Physical button (A)

| Action | Effect |
|---|---|
| Click (off) | All lights on |
| Click (on, within 2 s of turning on) | Randomize colours |
| Click (on, after 2 s) | All lights off |
| Hold | Dim. The direction alternates with each hold; from off it brightens from minimum |

Every button action shows up in HA / Apple Home within ~0.2 s.

### REST API

```bash
P=http://192.168.1.161
T="Authorization: Bearer <API_TOKEN>"

curl -X POST -H "$T" $P/on                                   # all on
curl -X POST -H "$T" "$P/off?light=1"                        # End off (Start stays on)
curl -X POST -H "$T" "$P/brightness?value=40"                # all, ratios kept
curl -X POST -H "$T" "$P/brightness?light=0&value=100"       # Start 100 %
curl -X POST -H "$T" "$P/color?light=1&h=0&s=100"            # End red
curl -X POST -H "$T" "$P/color?light=0&r=255&g=80&b=0"       # Start orange (RGB)
curl -X POST -H "$T" -d '{"light":1,"h":200,"s":60}' $P/color  # JSON body works too
curl -X POST -H "$T" $P/randomize
curl -H "$T" $P/status
```

Brightness is always **0-100 %**. v1 treated values ≤ 1 as fractions, so
1 % used to mean 100 %.

---

## Troubleshooting

### Status LED is orange
- 2.4 GHz only (CYW43439); SSID and password are case-sensitive.

### Status LED is magenta (WiFi OK, no MQTT)
- `MQTT_HOST` in `config.py` must be the Pi's IP; port must match `MQTT_PORT`.
- `MQTT_USER` / `MQTT_PASSWORD` must match `MQTT_DEVICE_USER` /
  `MQTT_DEVICE_PASSWORD`. Look for `bad username or password` on the serial console.
- `docker compose logs mosquitto` shows refused logins.

### Entities don't appear in HA
- Check that the MQTT integration is set up (Step 2.4).
- Watch the traffic: `docker exec -it lightbar-mosquitto mosquitto_sub -u <MQTT_HA_USER> -P <pw> -t 'lightbar/#' -t 'homeassistant/#' -v`
- `MQTT_TOPIC_PREFIX` must be the same in `.env` and `config.py`, or the ACL
  blocks the device.

### Lights missing in Apple Home
- Restart HA once after the entities first appear (Step 4.1).
- Check that `HOMEKIT_ENTITY_GLOB` matches the entity IDs.

### Mosquitto keeps restarting
- `docker compose logs mosquitto`: usually a `change-me` password or an empty variable in `.env`.

---

## File Versions (current)

| File | Version |
|---|---|
| `plasma2350w/main.py`, `app.py`, `config.py`, `lightbar.py`, `gradient.py`, `http_api.py` | 2.0.0 |
| `plasma2350w/ha.py`, `mqtt.py` | 1.0.0 |
| `hub/docker-compose.yml`, `.env.example`, `mosquitto/*`, `homeassistant/configuration.yaml` | 2.0.0 |
