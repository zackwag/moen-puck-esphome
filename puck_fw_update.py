#!/usr/bin/env python3
"""
Push bundled firmware to a Moen Smart Leak Detector (puck) over its WiFi AP.

Mirrors the Moen Flo app (v3.60.0.7869): if the puck's fw_name is older than
the target, POST the raw image to /puck/v1/fwUpdate as application/octet-stream.

Start it, then join the puck's "FloDetector-xxxx" network; it waits for the
puck to respond. Usage: python3 puck_fw_update.py [firmware.bin]
"""

import json
import os
import struct
import sys
import time

import requests

PUCK_BASE = "http://192.168.4.1/puck/v1"
DEFAULT_FW = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "puck_firmware", "1.2.1.bin")
WAIT_FOR_PUCK_SECS = 600
REBOOT_WAIT_SECS = 180


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def die(msg):
    log(f"✗ {msg}")
    sys.exit(1)


def read_image(path):
    """Validate an ESP32 app image and return (data, version, project)."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 0x100 or data[0] != 0xE9:
        die(f"{path} is not an ESP32 app image")
    if struct.unpack_from("<I", data, 0x20)[0] != 0xABCD5432:
        die(f"{path} has no ESP-IDF app descriptor")
    text = lambda off, n: data[off:off + n].split(b"\0")[0].decode()
    version, project = text(0x30, 32), text(0x50, 32)
    if project != "puck":
        die(f"{path} is for project '{project}', not 'puck'")
    return data, version, project


def version_tuple(name):
    return tuple(int(p) for p in name.split(".") if p.isdigit())


def get_props(timeout=5):
    r = requests.get(f"{PUCK_BASE}/props", timeout=timeout)
    r.raise_for_status()
    body = r.json()
    return body.get("result", body)


def wait_for_puck(total_secs):
    log(f"Waiting up to {total_secs // 60} min for the puck at 192.168.4.1 "
        "(join its FloDetector-xxxx WiFi now)...")
    deadline = time.time() + total_secs
    while time.time() < deadline:
        try:
            return get_props()
        except requests.exceptions.RequestException:
            time.sleep(3)
    return None


def main():
    fw_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FW
    fw_data, fw_version, _ = read_image(fw_path)
    log(f"Firmware: {fw_path} (version {fw_version}, {len(fw_data)} bytes)")

    props = wait_for_puck(WAIT_FOR_PUCK_SECS)
    if props is None:
        die("Puck never responded. Is it in pairing mode and are you on its WiFi?")

    current = props.get("fw_name", "?")
    log(f"Puck {props.get('device_id')} serial={props.get('serial_number')} "
        f"fw_name={current} fw_version={props.get('fw_version')} "
        f"state={props.get('pairing_state')} led={props.get('led_pattern')} "
        f"battery={props.get('telemetry_battery_voltage')}")

    if version_tuple(current) >= version_tuple(fw_version):
        log(f"✓ Puck already on {current} (>= {fw_version}); nothing to do.")
        return

    log(f"Uploading {fw_version} to /fwUpdate (do not power off the puck)...")
    started = time.time()
    try:
        r = requests.post(
            f"{PUCK_BASE}/fwUpdate",
            data=fw_data,
            headers={"Content-Type": "application/octet-stream"},
            timeout=300,
        )
        log(f"fwUpdate -> HTTP {r.status_code} after {time.time() - started:.0f}s: {r.text.strip()}")
        if not r.ok:
            die("Puck rejected the firmware upload.")
    except requests.exceptions.RequestException as e:
        # The puck may reboot into the new image before answering.
        log(f"Connection ended during/after upload ({type(e).__name__}); "
            "puck may be rebooting.")

    log(f"Waiting up to {REBOOT_WAIT_SECS}s for the puck to come back...")
    time.sleep(10)
    props = wait_for_puck(REBOOT_WAIT_SECS)
    if props is None:
        log("⚠  Puck did not come back on 192.168.4.1. Re-enter pairing mode "
            "(hold the button), rejoin its WiFi and run this again to check the version.")
        sys.exit(2)

    new = props.get("fw_name", "?")
    log(f"Puck is back: fw_name={new} fw_version={props.get('fw_version')} "
        f"state={props.get('pairing_state')} led={props.get('led_pattern')}")
    log(json.dumps(props, indent=2))
    if version_tuple(new) >= version_tuple(fw_version):
        log(f"✓ Firmware updated {current} -> {new}")
    else:
        log(f"⚠  Version still {new}; the update did not apply.")
        sys.exit(3)


if __name__ == "__main__":
    main()
