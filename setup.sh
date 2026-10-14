#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SECRETS_FILE="$SCRIPT_DIR/secrets.yaml"
FIRMWARE="$SCRIPT_DIR/firmware.ota.bin"

echo "=== Moen Puck ESPHome Setup ==="
echo

if [ -f "$FIRMWARE" ]; then
    echo "Firmware already built: $FIRMWARE"
    echo "To rebuild, delete it and run setup again."
    exit 0
fi

if [ -f "$SECRETS_FILE" ] && ! grep -q "YOUR_WIFI" "$SECRETS_FILE"; then
    read -rp "secrets.yaml already exists. Overwrite? [y/N] " overwrite
    if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
        echo "Keeping existing secrets.yaml"
    else
        WRITE_SECRETS=1
    fi
else
    WRITE_SECRETS=1
fi

if [ "${WRITE_SECRETS:-0}" = 1 ]; then
    echo "Device name will be set automatically from the puck's serial number."
    echo "You can change it later in secrets.yaml."
    echo

    read -rp "WiFi SSID: " wifi_ssid
    read -rsp "WiFi password: " wifi_password
    echo

    api_key=$(python3 -c "import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())")

    cat > "$SECRETS_FILE" <<EOF
device_name: "moen-puck"
friendly_name: "Moen Leak Detector"
wifi_ssid: "$wifi_ssid"
wifi_password: "$wifi_password"
ap_password: "moen-fallback"
api_key: "$api_key"
ota_password: "moen-puck-ota"
EOF

    echo
    echo "secrets.yaml written."
    echo "API encryption key: $api_key"
fi

echo
echo "Compiling firmware..."
if ! command -v esphome &>/dev/null; then
    echo "ESPHome not found. Installing..."
    pip install esphome
fi

cd "$SCRIPT_DIR"
esphome compile moen-puck.yaml

BUILD_BIN=$(find "$SCRIPT_DIR/.esphome" -name "firmware.ota.bin" -print -quit 2>/dev/null)
if [ -n "$BUILD_BIN" ]; then
    cp "$BUILD_BIN" "$FIRMWARE"
    echo
    echo "Firmware ready: $FIRMWARE"
    echo
    echo "Next steps:"
    echo "  1. Connect to the puck's WiFi (FloDetector-XXXX)"
    echo "  2. Flash: python3 flash_ota.py firmware.ota.bin"
else
    echo "ERROR: Compilation failed — no firmware.ota.bin produced."
    exit 1
fi
