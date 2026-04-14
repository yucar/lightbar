#!/bin/sh
# Version: 1.1.0
# ══════════════════════════════════════════════════════════════════
# Lightbar Matter Bridge — setup.sh
#
# Run this ONCE on the Raspberry Pi before starting the container.
# It creates the Matterbridge data directories and pre-seeds the
# matterbridge-webhooks plugin config with your Plasma 2350 W's
# REST API endpoints.
#
# Usage:
#   1. Edit .env (set LIGHTBAR_HOST to your Plasma's IP)
#   2. ./setup.sh
#   3. docker compose up -d
#
# ══════════════════════════════════════════════════════════════════

set -e

# Load .env
if [ -f .env ]; then
    # shellcheck disable=SC1091
    . ./.env
fi

HOST="${LIGHTBAR_HOST:-192.168.1.100}"
PORT="${LIGHTBAR_PORT:-80}"
NAME="${LIGHTBAR_NAME:-Lightbar}"
BASE="http://${HOST}:${PORT}"

MB_DIR="${HOME}/.matterbridge"
PLUGIN="matterbridge-webhooks"

echo "════════════════════════════════════════════════"
echo "  Lightbar Matter Bridge — Setup"
echo "════════════════════════════════════════════════"
echo "  Plasma 2350 W : ${BASE}"
echo "  Device name   : ${NAME}"
echo ""

# ── Create directories ───────────────────────────────────────────
echo "[setup] Creating Matterbridge directories..."
mkdir -p "${HOME}/Matterbridge"
mkdir -p "${MB_DIR}"
mkdir -p "${HOME}/.mattercert"

# ── Write matterbridge.config.json ──────────────────────────────
# Registers the matterbridge-webhooks plugin with Matterbridge.
# Only writes if the plugin isn't already registered.
MB_CONFIG="${MB_DIR}/matterbridge.config.json"

if [ -f "${MB_CONFIG}" ] && grep -q "${PLUGIN}" "${MB_CONFIG}" 2>/dev/null; then
    echo "[setup] Plugin already registered in ${MB_CONFIG} — skipping."
else
    echo "[setup] Writing ${MB_CONFIG}..."
    # Preserve existing config if present, otherwise start fresh.
    if [ -f "${MB_CONFIG}" ]; then
        # Use node to merge — avoids overwriting other plugins
        node - <<JSEOF
const fs = require('fs');
const path = '${MB_CONFIG}';
let config = {};
try { config = JSON.parse(fs.readFileSync(path, 'utf8')); } catch(e) {}
if (!Array.isArray(config.plugins)) config.plugins = [];
if (!config.plugins.find(p => p && p.name === '${PLUGIN}')) {
    config.plugins.push({ name: '${PLUGIN}', enabled: true });
}
fs.writeFileSync(path, JSON.stringify(config, null, 2));
console.log('[setup] Plugin registered in', path);
JSEOF
    else
        cat > "${MB_CONFIG}" << EOF
{
  "plugins": [
    { "name": "${PLUGIN}", "enabled": true }
  ]
}
EOF
        echo "[setup] Created ${MB_CONFIG}"
    fi
fi

# ── Write matterbridge-webhooks.config.json ──────────────────────
# This is the plugin-specific config: device list + webhook URLs.
# Re-written every time so IP changes in .env are always picked up.
PLUGIN_CONFIG="${MB_DIR}/${PLUGIN}.config.json"

echo "[setup] Writing ${PLUGIN_CONFIG}..."

cat > "${PLUGIN_CONFIG}" << EOF
{
  "name": "${PLUGIN}",
  "type": "DynamicPlatform",
  "deviceList": [
    {
      "name": "${NAME} Start",
      "deviceType": "extendedLight",
      "on":         "POST#${BASE}/on",
      "off":        "POST#${BASE}/off",
      "brightness": "POST#${BASE}/brightness?value=\${LEVEL100f}",
      "colorRgb":   "POST#${BASE}/color?index=0&r=\${red}&g=\${green}&b=\${blue}"
    },
    {
      "name": "${NAME} End",
      "deviceType": "extendedLight",
      "on":         "POST#${BASE}/on",
      "off":        "POST#${BASE}/off",
      "brightness": "POST#${BASE}/brightness?value=\${LEVEL100f}",
      "colorRgb":   "POST#${BASE}/color?index=1&r=\${red}&g=\${green}&b=\${blue}"
    }
  ]
}
EOF

echo "[setup] Done."
echo ""
echo "  Config files written to ${MB_DIR}/"
echo ""
echo "  Next step:"
echo "    docker compose up -d"
echo ""
echo "  Then open http://\$(hostname -I | awk '{print \$1}'):8283"
echo "  and scan the QR code with Apple Home."
