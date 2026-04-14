# Lightbar — Setup Guide
<!-- Version: 2.0.0 -->

**Single-board WiFi LED gradient light — Matter via Matterbridge on Raspberry Pi**

---

## What You Need

### Hardware

| Item | Notes |
|---|---|
| **Pimoroni Plasma 2350 W** | [shop.pimoroni.com](https://shop.pimoroni.com/products/plasma-2350-w) — get the A4 stepping |
| **2× WS2812 LED strips** | 1 m / 96 LEDs each (192 total) |
| **USB-C cable** | Data + power capable |
| **Raspberry Pi** | Any model with Docker support (Pi 3B+ or newer recommended) |

### Software

| Item | Notes |
|---|---|
| **Pimoroni MicroPython** | `.uf2` for Plasma 2350 W (NOT the generic RP2350) |
| **Thonny IDE** | For copying files to the Plasma — [thonny.org](https://thonny.org) |
| **Docker + Docker Compose** | For the Matterbridge bridge on the Pi |

---

## Architecture

```
                    USB-C (power)
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
              │                     │
              │  Matterbridge +     │
              │  webhooks plugin    │
              │                     │
              │  → Apple Home       │
              │  → Google Home      │
              │  → Alexa            │
              └─────────────────────┘
```

---

## Step 1: Wire the LED Strips

Connect both LED strips **in series** to the Plasma 2350 W screw terminals:

- **DAT** → data-in of strip 1
- **5V** → 5V of strip 1
- **GND** → GND of strip 1
- Strip 1 data-out → strip 2 data-in (series connection)

Both strips share power from the Plasma's USB-C (up to 3 A). For gradients
this is plenty — only full-white at maximum brightness approaches the limit.

---

## Step 2: Flash the Plasma Firmware

### 2.1 — Download Pimoroni MicroPython for Plasma 2350 W

Go to: https://github.com/pimoroni/plasma/releases/latest

Download the `.uf2` file labelled **Plasma 2350 W** (not Plasma 2350).

### 2.2 — Flash

1. Hold **BOOT**, tap **RESET** (or plug in USB-C while holding BOOT)
2. A drive called `RP2350` appears
3. Drag the `.uf2` onto it — the Plasma reboots automatically

### 2.3 — Edit WiFi credentials

Open `plasma2350w/secrets.py` and fill in your network details:

```python
# secrets.py — WiFi credentials
# Version: 1.0.0

WIFI_SSID = "YourWiFiNetwork"
WIFI_PASSWORD = "YourWiFiPassword"

# Recommended: set a static IP so Matterbridge always finds the Plasma
# STATIC_IP = "192.168.1.161"
# SUBNET    = "255.255.255.0"
# GATEWAY   = "192.168.1.1"
# DNS       = "192.168.1.1"
```

### 2.4 — Copy files to the Plasma

In **Thonny**:

1. Connect the Plasma via USB-C
2. Set interpreter: **MicroPython (RP2040)** — works for RP2350 too
3. Upload these three files to the root of the device:
   - `plasma2350w/main.py` ← v1.5.0
   - `plasma2350w/gradient.py` ← v1.1.0
   - `plasma2350w/secrets.py` ← v1.0.0

Or via `mpremote`:

```bash
mpremote connect /dev/tty.usbmodem* cp plasma2350w/main.py :main.py
mpremote connect /dev/tty.usbmodem* cp plasma2350w/gradient.py :gradient.py
mpremote connect /dev/tty.usbmodem* cp plasma2350w/secrets.py :secrets.py
mpremote connect /dev/tty.usbmodem* reset
```

### 2.5 — Verify

After reset the serial console should show:

```
==================================================
  Lightbar — Plasma 2350 W
==================================================
  LEDs: 192
  Lights: 2 (gradient endpoints)
  Gradient: polychromatic HSV
  Fade: easeInOutCirc over 1.0s
  Color crossfade: 0.5s

[WiFi]
  Connecting to 'YourWiFiNetwork'...
  Connected! IP: 192.168.1.161

[Server]
  HTTP server on http://192.168.1.161:80
```

Test the REST API:

```bash
curl http://192.168.1.161/info
curl -X POST http://192.168.1.161/on
curl -X POST 'http://192.168.1.161/color?idx=0&h=0&s=100'    # red start
curl -X POST 'http://192.168.1.161/color?idx=1&h=240&s=100'  # blue end
curl http://192.168.1.161/status
```

The status response should reflect the new colours:
```json
{"on": true, "brightness": 1.0, "colors": [{"h": 0.0, ...}, {"h": 0.667, ...}]}
```

---

## Step 3: Set Up the Matterbridge Bridge on Raspberry Pi

### 3.1 — Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group membership to take effect
```

### 3.2 — Create Matterbridge data directories

```bash
mkdir -p ~/Matterbridge ~/.matterbridge ~/.mattercert
```

### 3.3 — Write the Matterbridge config files

Replace `192.168.1.161` with your Plasma's actual IP.

```bash
# Register the matterbridge-webhooks plugin
cat > ~/.matterbridge/matterbridge.config.json << 'EOF'
{
  "plugins": [
    { "name": "matterbridge-webhooks", "enabled": true }
  ]
}
EOF

# Configure the plugin with Lightbar endpoints
cat > ~/.matterbridge/matterbridge-webhooks.config.json << 'EOF'
{
  "name": "matterbridge-webhooks",
  "type": "DynamicPlatform",
  "webhooks": {},
  "outlets": {},
  "lights": {
    "Lightbar Start": {
      "onUrl":         "POST#http://192.168.1.161/on",
      "offUrl":        "POST#http://192.168.1.161/off",
      "brightnessUrl": "POST#http://192.168.1.161/brightness?value=${LEVEL100}",
      "colorTempUrl":  "",
      "rgbUrl":        "POST#http://192.168.1.161/color?idx=0&h=${HUE}&s=${SATURATION}"
    },
    "Lightbar End": {
      "onUrl":         "POST#http://192.168.1.161/on",
      "offUrl":        "POST#http://192.168.1.161/off",
      "brightnessUrl": "POST#http://192.168.1.161/brightness?value=${LEVEL100}",
      "colorTempUrl":  "",
      "rgbUrl":        "POST#http://192.168.1.161/color?idx=1&h=${HUE}&s=${SATURATION}"
    }
  }
}
EOF
```

> **Important:** Always edit these files with `sudo` if you run
> `docker compose` with `sudo`, because `${HOME}` resolves to `/root`.
> In that case replace `~` with `/root` in all paths above.

### 3.4 — Write the docker-compose.yml

Copy `bridge/docker-compose.yml` (v1.2.0) to the Pi, or create it:

```bash
mkdir -p ~/lightbar-bridge
cat > ~/lightbar-bridge/docker-compose.yml << 'EOF'
services:
  matterbridge:
    container_name: matterbridge
    image: luligu/matterbridge:latest
    network_mode: host
    restart: always
    volumes:
      - "${HOME}/Matterbridge:/root/Matterbridge"
      - "${HOME}/.matterbridge:/root/.matterbridge"
      - "${HOME}/.mattercert:/root/.mattercert"
EOF
```

### 3.5 — Patch the webhooks plugin bug

The `luligu/matterbridge:latest` image ships with `matterbridge-webhooks`
pre-installed but has a bug where `moveToHueAndSaturation` crashes with
`Behavior colorControl is not supported`. Patch it after first start:

```bash
# Start once to pull the image
cd ~/lightbar-bridge
sudo docker compose up -d

# Apply the fix (removes the broken stateOf() call)
sudo docker exec -it matterbridge sh -c "
  sed -i '245s/.*/  \/\/ stateOf() removed: attributes already set by command handler/' \
    /usr/local/lib/node_modules/matterbridge-webhooks/dist/module.js
"

# Patch HUE/SATURATION to read from attributes instead of request
sudo docker exec -it matterbridge sh -c "
  sed -i '212s/data\.request\.hue/data.attributes.currentHue/g' \
    /usr/local/lib/node_modules/matterbridge-webhooks/dist/module.js
  sed -i '213s/data\.request\.hue/data.attributes.currentHue/g' \
    /usr/local/lib/node_modules/matterbridge-webhooks/dist/module.js
  sed -i '215s/data\.request\.saturation/data.attributes.currentSaturation/g' \
    /usr/local/lib/node_modules/matterbridge-webhooks/dist/module.js
  sed -i '216s/data\.request\.saturation/data.attributes.currentSaturation/g' \
    /usr/local/lib/node_modules/matterbridge-webhooks/dist/module.js
"

# Restart to apply
sudo docker compose restart
```

> **Note:** These patches are lost if the container image is updated
> (`docker compose pull`). Re-apply after any image update.

### 3.6 — Add the plugin via CLI

```bash
sudo docker exec -it matterbridge matterbridge --docker --add matterbridge-webhooks
sudo docker compose restart
```

### 3.7 — Verify

```bash
sudo docker compose logs -f
```

You should see the plugin load and devices register:

```
[PluginManager] Loading plugin matterbridge-webhooks type AnyPlatform
[Matterbridge webhooks plugin] Initializing platform: matterbridge-webhooks
[PluginManager] Started plugin matterbridge-webhooks type DynamicPlatform
[Matterbridge] Matterbridge bridge started successfully
```

Open the Matterbridge web UI: **http://\<pi-ip\>:8283**

---

## Step 4: Pair with Apple Home

1. Open the **Home** app
2. Tap **+** → **Add Accessory**
3. Scan the **QR code** shown in the Matterbridge web UI
4. **"Lightbar Start"** and **"Lightbar End"** appear as Extended Color Lights
5. Assign them to a room

### Grouping (optional)

Long-press one Lightbar tile → **Settings** → **Group with Other Accessories**
→ select the other endpoint. They'll appear as one accessory with two colour controls.

---

## Step 5: Use It

### Physical Button (A button on the Plasma)

| Action | Effect |
|---|---|
| Click (lights off) | Turn on with fade |
| Click (lights on, within 2s of turning on) | Randomize gradient colours |
| Click (lights on, after 2s) | Turn off with fade |
| Hold | Increase brightness |

### REST API

```bash
PLASMA=192.168.1.161

# On/Off
curl -X POST http://$PLASMA/on
curl -X POST http://$PLASMA/off
curl -X POST http://$PLASMA/toggle

# Brightness (0.0–1.0, or 0–100)
curl -X POST "http://$PLASMA/brightness?value=0.5"

# Colour by hue/sat (hue 0–360°, saturation 0–100%)
curl -X POST "http://$PLASMA/color?idx=0&h=0&s=100"    # start = red
curl -X POST "http://$PLASMA/color?idx=1&h=240&s=100"  # end = blue

# Colour by RGB (0–255)
curl -X POST "http://$PLASMA/color?idx=0&r=255&g=80&b=0"

# Full gradient via JSON body
curl -X POST http://$PLASMA/color \
  -H "Content-Type: application/json" \
  -d '{"colors": [{"h":0.08,"s":1,"v":1}, {"h":0.75,"s":0.8,"v":1}]}'

# Randomize
curl -X POST http://$PLASMA/randomize

# Status
curl http://$PLASMA/status
```

---

## Troubleshooting

### Plasma won't connect to WiFi
- Only 2.4 GHz networks supported (CYW43439 chip)
- Check `secrets.py` — SSID and password are case-sensitive
- Status LED is orange while retrying

### Matterbridge can't reach the Plasma
- Test directly: `curl http://<plasma-ip>/status`
- Use a static IP in `secrets.py` to avoid DHCP changes
- Both Pi and Plasma must be on the same network/VLAN

### Lights don't appear in Apple Home after pairing Matterbridge
- Open Matterbridge web UI → Plugins → check matterbridge-webhooks is listed and enabled
- Check logs: `sudo docker compose logs -f`
- Re-add the plugin: `sudo docker exec -it matterbridge matterbridge --docker --add matterbridge-webhooks`

### Colour changes don't work (Invalid URL or failed errors in logs)
- Re-apply the plugin patches from Step 3.5
- Check the config file: `sudo cat /root/.matterbridge/matterbridge-webhooks.config.json`
- Confirm `rgbUrl` uses `${HUE}` and `${SATURATION}` (uppercase), not `${red}/${green}/${blue}`

### Plugin patches lost after image update
- Re-apply Step 3.5 after every `docker compose pull`

### mDNS warning about tailscale0
- If the Pi has Tailscale installed, add `--mdnsinterface eth0` to the
  Matterbridge command to force it to use the correct interface:
  ```yaml
  command: ["matterbridge", "--docker", "--mdnsinterface", "eth0"]
  ```

---

## File Versions (current)

| File | Version |
|---|---|
| `plasma2350w/main.py` | 1.5.0 |
| `plasma2350w/gradient.py` | 1.1.0 |
| `plasma2350w/secrets.py` | 1.0.0 |
| `bridge/docker-compose.yml` | 1.2.0 |
| `bridge/.env` | 1.1.0 |
| `bridge/setup.sh` | 1.1.0 |
