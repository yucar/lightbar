# secrets.py — per-install credentials. NEVER commit the real file.
# Copy this file to secrets.py, fill it in, and upload it to the Plasma.

WIFI_SSID = "YourWiFiNetwork"          # 2.4 GHz only
WIFI_PASSWORD = "YourWiFiPassword"

# Must match MQTT_DEVICE_USER / MQTT_DEVICE_PASSWORD in hub/.env
MQTT_USER = "lightbar"
MQTT_PASSWORD = "change-me-device"

# Bearer token for the local REST API. Every request must send
#   Authorization: Bearer <API_TOKEN>
# Set to None to leave the API open (not recommended).
API_TOKEN = "change-me-api-token"

# Optional static IP (recommended). Delete or comment out to use DHCP.
# STATIC_IP = "192.168.1.161"
# SUBNET = "255.255.255.0"
# GATEWAY = "192.168.1.1"
# DNS = "192.168.1.1"
