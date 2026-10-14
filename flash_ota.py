#!/usr/bin/env python3
"""
Flash custom firmware to the Moen/Flo puck via its HTTP OTA endpoint.

Usage:
  1. Run setup.sh first to configure WiFi and generate secrets.yaml
  2. Connect to the puck's WiFi AP (SSID: FloDetector-XXXX)
  3. Run: python3 flash_ota.py

This script will:
  - Read the puck's serial number
  - Set hostname to the serial number (lowercase)
  - Compile ESPHome firmware
  - Flash it to the puck
"""
import sys, os, time, subprocess, re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SECRETS_FILE = os.path.join(SCRIPT_DIR, "secrets.yaml")
YAML_FILE = os.path.join(SCRIPT_DIR, "moen-puck.yaml")
PUCK_OTA_URL = "http://192.168.4.1/puck/v1/fwUpdate"
PUCK_PROPS_URL = "http://192.168.4.1/puck/v1/props"


def check_puck():
    import requests
    try:
        r = requests.get(PUCK_PROPS_URL, timeout=5)
        data = r.json()
        props = data.get("result", data)
        print(f"Connected to puck:")
        print(f"  Device ID: {props.get('device_id', 'unknown')}")
        print(f"  Serial:    {props.get('serial_number', 'unknown')}")
        print(f"  FW:        {props.get('fw_name', 'unknown')} (build {props.get('fw_version', '?')})")
        print(f"  Battery:   {props.get('telemetry_battery_percent', 'unknown')}%")
        return props
    except Exception as e:
        print(f"Cannot reach puck at 192.168.4.1: {e}")
        print("Make sure you're connected to the puck's WiFi AP (FloDetector-XXXX)")
        return None


def update_device_name(serial):
    name = serial.lower()
    with open(SECRETS_FILE) as f:
        content = f.read()

    content = re.sub(
        r'^device_name:.*$',
        f'device_name: "{name}"',
        content, flags=re.MULTILINE
    )
    content = re.sub(
        r'^friendly_name:.*$',
        f'friendly_name: "Moen Puck {serial}"',
        content, flags=re.MULTILINE
    )

    with open(SECRETS_FILE, "w") as f:
        f.write(content)

    print(f"\nDevice name set to: {name}")
    print(f"Hostname will be: {name}.local")


def compile_firmware():
    print("\nCompiling firmware...")
    result = subprocess.run(
        ["esphome", "compile", YAML_FILE],
        cwd=SCRIPT_DIR,
    )
    if result.returncode != 0:
        print("Compilation failed!")
        sys.exit(1)

    for root, dirs, files in os.walk(os.path.join(SCRIPT_DIR, ".esphome")):
        for f in files:
            if f == "firmware.ota.bin":
                return os.path.join(root, f)

    print("ERROR: firmware.ota.bin not found after compilation")
    sys.exit(1)


def flash_firmware(firmware_path):
    import requests
    with open(firmware_path, "rb") as f:
        firmware = f.read()

    if firmware[0] != 0xE9:
        print(f"ERROR: Invalid magic byte 0x{firmware[0]:02X} (expected 0xE9)")
        sys.exit(1)

    print(f"\nFirmware: {len(firmware)} bytes ({len(firmware)/1024:.1f} KB)")

    print(f"\n*** ABOUT TO FLASH FIRMWARE ***")
    print(f"*** This will replace the puck's original Moen firmware ***")
    confirm = input("\nType 'FLASH' to proceed: ")
    if confirm != "FLASH":
        print("Aborted.")
        sys.exit(0)

    print(f"\nUploading...")
    start = time.time()

    r = requests.post(
        PUCK_OTA_URL,
        data=firmware,
        headers={"Content-Type": "application/octet-stream"},
        timeout=120,
    )

    elapsed = time.time() - start
    print(f"Upload completed in {elapsed:.1f}s — status {r.status_code}")

    if r.status_code == 200:
        print("\nFlash successful! The puck will reboot into ESPHome.")
        print("Disconnect from the puck's AP and reconnect to your WiFi.")
    else:
        print(f"\nFlash may have failed (status {r.status_code}).")


def main():
    if not os.path.exists(SECRETS_FILE):
        print("Run setup.sh first to configure WiFi credentials.")
        sys.exit(1)

    props = check_puck()
    if props is None:
        sys.exit(1)

    battery = props.get("telemetry_battery_percent", 0)
    if isinstance(battery, (int, float)) and battery < 30:
        print(f"\nBattery is {battery}% — puck requires >= 30% for OTA.")
        sys.exit(1)

    serial = props.get("serial_number", "")
    if serial:
        update_device_name(serial)
    else:
        print("\nWARNING: Could not read serial number. Using default device name.")

    firmware_path = compile_firmware()
    flash_firmware(firmware_path)


if __name__ == "__main__":
    main()
