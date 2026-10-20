#!/usr/bin/env python3
"""
Moen Smart Leak Detector (puck) onboarding script.
Reverse-engineered from Moen Flo APK v3.60.0.7869.

Usage: python3 moen_puck_onboard.py
"""

import base64
import getpass
import json
import os
import sys
import time

import requests

MOEN_AUTH_URL = "https://api.prod.iot.moen.com/v1/oauth2/token"
FLO_BASE = "https://api-gw.meetflo.com/api"
PUCK_BASE = "http://192.168.4.1/puck/v1"
CLIENT_ID = "6qn9pep31dglq6ed4fvlq6rp5t"
DEVICE_TYPE = "puck_oem"
DEVICE_MODEL = "puck_v1"
FIRMWARE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "puck_firmware")
# The app targets 1.2.1 (SWDProvisioningHelper default), even though 1.2.6
# also ships in assets/firmware.
BUNDLED_FW_VERSION = "1.2.1"
BUNDLED_FW_VERSION_INT = 10201  # 1*10000 + 02*100 + 01


# ── helpers ──────────────────────────────────────────────────────────────────

def die(msg):
    print(f"\n✗ {msg}", file=sys.stderr)
    sys.exit(1)


def ok(label, data=None):
    print(f"✓ {label}")
    if data is not None:
        print(json.dumps(data, indent=2))
    return data


def prompt(msg, default=None, secret=False):
    suffix = f" [{default}]" if default else ""
    full = f"{msg}{suffix}: "
    val = (getpass.getpass(full) if secret else input(full)).strip()
    return val or default


def pause(msg):
    input(f"\n  ➜  {msg}\n  Press ENTER when ready...")


# ── step 1: login ─────────────────────────────────────────────────────────────

def decode_jwt_payload(token):
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def login(email, password):
    print("\n[1/6] Logging in to Moen IoT...")
    r = requests.post(
        MOEN_AUTH_URL,
        json={
            "username": email,
            "password": password,
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
        },
        timeout=15,
    )
    if not r.ok:
        die(f"Login failed {r.status_code}: {r.text}")
    body = r.json()
    token_obj = body.get("token", body)
    access_token = token_obj.get("access_token")
    if not access_token:
        die(f"No access_token in response: {body}")

    user_id = None
    id_token = token_obj.get("id_token")
    if id_token:
        claims = decode_jwt_payload(id_token)
        user_id = claims.get("sub")

    ok("Logged in", {"user_id": user_id})
    return access_token, user_id


# ── step 2: detector pair init ────────────────────────────────────────────────

def detector_pair_init(auth_token):
    print("\n[2/6] Requesting provisioning slot from Flo cloud...")
    r = requests.post(
        f"{FLO_BASE}/v2/devices/pair/init/puck",
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=15,
    )
    if not r.ok:
        die(f"detectorPairInit failed {r.status_code}: {r.text}")
    data = r.json()
    prov_token = data.get("token")
    if not prov_token:
        die("detectorPairInit returned no token — cannot pair without it.")
    prov_claims = decode_jwt_payload(prov_token)
    ok("Got provisioning token", {
        "id": data.get("id"),
        "serialNumber": data.get("serialNumber"),
        "token": prov_token[:20] + "..." if prov_token else None,
        "token_claims": prov_claims,
    })
    return data


# ── step 3: get location id ────────────────────────────────────────────────────

def get_flo_user_id(auth_token, cognito_user_id):
    r = requests.get(
        f"{FLO_BASE}/v2/moen/sync/me",
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=15,
    )
    if r.ok:
        data = r.json()
        flo_id = data.get("id") or data.get("userId") or data.get("user_id")
        if flo_id:
            return flo_id

    r2 = requests.get(
        f"{FLO_BASE}/v2/users/{cognito_user_id}",
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=15,
    )
    if r2.ok:
        data = r2.json()
        flo_id = data.get("id") or data.get("userId")
        if flo_id:
            return flo_id

    return cognito_user_id


def pick_location(auth_token, user_id):
    print("\n[3/6] Fetching your Flo locations...")
    flo_user_id = get_flo_user_id(auth_token, user_id)
    if flo_user_id != user_id:
        ok(f"Flo user ID: {flo_user_id}")

    r = requests.get(
        f"{FLO_BASE}/v2/locations",
        headers={"Authorization": f"Bearer {auth_token}"},
        params={"userId": flo_user_id, "expand": "devices"},
        timeout=15,
    )
    if not r.ok:
        die(f"getLocations failed {r.status_code}: {r.text}")

    body = r.json()
    locations = body.get("items", [body] if "id" in body else [])
    if not locations:
        die("No locations found on your account.")

    for i, loc in enumerate(locations):
        print(f"  {i+1}) {loc.get('nickname') or loc.get('address', {}).get('address1', 'Unknown')}  (id: {loc['id']})")

    if len(locations) == 1:
        chosen = locations[0]
        ok(f"Using location: {chosen.get('nickname', chosen['id'])}")
    else:
        idx = int(prompt("Choose location number", default="1")) - 1
        chosen = locations[idx]

    return chosen["id"]


# ── puck connectivity helpers ─────────────────────────────────────────────────

def puck_get(path, timeout=8):
    return requests.get(f"{PUCK_BASE}{path}", timeout=timeout)


def puck_post(path, body, timeout=8):
    return requests.post(f"{PUCK_BASE}{path}", json=body, timeout=timeout)


def wait_for_puck(retries=10, delay=3):
    print("  Waiting for puck HTTP server to respond...")
    for i in range(retries):
        try:
            r = puck_get("/props")
            if r.ok:
                return r.json()
        except requests.exceptions.ConnectionError:
            pass
        print(f"  ... attempt {i+1}/{retries}")
        time.sleep(delay)
    die("Could not reach puck at 192.168.4.1. Are you connected to its WiFi AP?")


# ── step 4: connect to puck + check properties ────────────────────────────────

def connect_to_puck():
    print("\n[4/6] Connect your Mac to the puck's WiFi AP")
    print("  1. Press and hold the puck's button until it flashes (pairing mode).")
    print("  2. Open System Settings → Wi-Fi and join the network that starts with")
    print('     "FloDetector-" (the puck broadcasts its own AP).')
    pause("Once connected to the puck's WiFi AP")

    props = wait_for_puck()
    result = props.get("result", props)

    print("\n  Puck info:")
    print(f"    device_id    : {result.get('device_id')}")
    print(f"    serial       : {result.get('serial_number')}")
    print(f"    fw_version   : {result.get('fw_version')}")
    print(f"    pairing_state: {result.get('pairing_state')}")
    print(f"    ap_ssid      : {result.get('wifi_ap_ssid')}")

    return result


# ── step 5: pick home WiFi ────────────────────────────────────────────────────

def pick_wifi():
    print("\n[5/6] Selecting home WiFi to provision the puck onto")
    print("  Fetching visible networks from the puck...")
    try:
        r = puck_get("/scanList")
        networks = r.json().get("result", r.json()) if r.ok else []
        if isinstance(networks, dict):
            networks = networks.get("list", [])
    except (requests.exceptions.RequestException, ValueError):
        networks = []

    visible = dedupe_networks(networks)
    if visible:
        print("\n  Networks the puck can see:")
        for i, net in enumerate(visible):
            ssid = net.get("ssid", "?")
            enc  = net.get("encryption", "?")
            sig  = net.get("signal", "?")
            print(f"    {i+1}) {ssid:30s}  enc={enc}  signal={sig}")
        print()

    choice = prompt("Pick a network number, or type an SSID")
    if visible and choice.isdigit() and 1 <= int(choice) <= len(visible):
        picked = visible[int(choice) - 1]
        ssid = picked["ssid"]
        enc = picked.get("encryption", "wpa2-psk")
    else:
        ssid = choice
        enc = "wpa2-psk"
        for net in networks:
            if net.get("ssid") == ssid:
                enc = net.get("encryption", "wpa2-psk")
                break

    password = prompt(f"Password for '{ssid}'", secret=True) or ""
    enc = prompt("WiFi encryption type", default=default_encryption(enc, password))

    return ssid, password, enc


def signal_of(net):
    try:
        return int(net.get("signal", 0))
    except (TypeError, ValueError):
        return 0


def dedupe_networks(networks):
    # Mesh systems show up once per node; keep the strongest entry per SSID.
    best = {}
    for net in networks:
        ssid = net.get("ssid")
        if ssid and (ssid not in best or signal_of(net) > signal_of(best[ssid])):
            best[ssid] = net
    return sorted(best.values(), key=signal_of, reverse=True)


def default_encryption(scanned, password):
    # The puck's scan can report a secured network as "none", so let the
    # password decide: if there is one, the network isn't open.
    if password and scanned == "none":
        return "wpa2-psk"
    if not password:
        return "none"
    return scanned


# ── step 5b: firmware update (if needed) ─────────────────────────────────────

def check_and_update_firmware(puck_props):
    fw_version = puck_props.get("fw_version", 0)
    fw_name = puck_props.get("fw_name", "?")
    if fw_version >= BUNDLED_FW_VERSION_INT:
        print(f"  Firmware {fw_name} (v{fw_version}) is up to date.")
        return False

    print(f"\n  ⚠  Puck firmware {fw_name} (v{fw_version}) is outdated.")
    print(f"     Bundled firmware: {BUNDLED_FW_VERSION} (v{BUNDLED_FW_VERSION_INT})")

    fw_path = os.path.join(FIRMWARE_DIR, f"{BUNDLED_FW_VERSION}.bin")
    if not os.path.isfile(fw_path):
        print(f"  ✗ Firmware file not found at {fw_path}")
        print("    See the README for how to get it from the Moen Flo app.")
        print("    Skipping firmware update — pairing may fail with old firmware.")
        return False

    fw_size = os.path.getsize(fw_path)
    print(f"     Firmware file: {fw_path} ({fw_size} bytes)")
    ans = prompt("  Push firmware update before pairing? (y/n)", default="y")
    if ans.lower() != "y":
        return False

    print("  Uploading firmware to puck (this takes ~30 seconds)...")
    with open(fw_path, "rb") as f:
        fw_data = f.read()

    try:
        r = requests.post(
            f"{PUCK_BASE}/fwUpdate",
            data=fw_data,
            headers={"Content-Type": "application/octet-stream"},
            timeout=120,
        )
        if r.ok:
            ok("Firmware upload accepted", r.json() if r.text else {"status": "ok"})
        else:
            print(f"  ⚠  Firmware upload returned {r.status_code}: {r.text}")
            return False
    except requests.exceptions.ConnectionError:
        print("  Connection lost during upload — puck may be rebooting.")

    # The puck's AP goes down while it reboots, so the Mac drops off it.
    ap_ssid = puck_props.get("wifi_ap_ssid") or "FloDetector-XXXX"
    print("\n  The puck is rebooting, which disconnects your Mac from its WiFi.")
    print(f"  ➜  Rejoin '{ap_ssid}' in System Settings → Wi-Fi if your Mac")
    print("     doesn't reconnect on its own.\n")
    print("  Waiting for puck to reboot (up to 90 seconds)...")
    time.sleep(15)
    for i in range(15):
        try:
            pr = puck_get("/props", timeout=5)
            if pr.ok:
                result = pr.json().get("result", pr.json())
                new_fw = result.get("fw_version", 0)
                print(f"  Puck is back! fw_version={new_fw}")
                if new_fw > fw_version:
                    ok(f"Firmware updated: {fw_version} → {new_fw}")
                else:
                    print(f"  ⚠  Firmware version unchanged ({new_fw}). Update may not have applied.")
                return True
        except requests.exceptions.ConnectionError:
            pass
        print(f"  ... waiting ({i+1}/15)")
        time.sleep(5)

    print(f"  ⚠  Puck did not come back. Make sure your Mac is on '{ap_ssid}';")
    print("     if that network is gone, hold the button to re-enter pairing mode.")
    return True


# ── step 6: pair ──────────────────────────────────────────────────────────────

def pair_puck(prov_data, location_id, wifi_ssid, wifi_password, wifi_enc, nickname):
    print("\n[6/6] Sending pair command to puck...")
    masked_pw = wifi_password[0] + "*" * (len(wifi_password) - 1) if wifi_password else "(empty)"
    print("\n  Summary:")
    print(f"    WiFi SSID      : {wifi_ssid}")
    print(f"    WiFi password  : {masked_pw}")
    print(f"    Encryption     : {wifi_enc}")
    print(f"    Nickname       : {nickname}")
    print(f"    Location       : {location_id}")
    print(f"    Provisioning ID: {prov_data.get('id', '?')}")
    print()
    body = {
        "cloud_hostname": "api-gw.meetflo.com",
        "api_access_token": prov_data["token"],
        "wifi_ssid": wifi_ssid,
        "wifi_password": wifi_password,
        "wifi_encryption": wifi_enc,
        "location_id": location_id,
        "nickname": nickname,
        "device_type": DEVICE_TYPE,
        "device_model": DEVICE_MODEL,
    }
    send_pair(body)
    return monitor_pairing(body)


def send_pair(body, fatal=True):
    # The app ignores failures on re-sends (it just logs them), so only the
    # first send is fatal.
    fail = die if fatal else (lambda msg: print(f"  ⚠  {msg} (continuing)"))
    print("  Sending to http://192.168.4.1/puck/v1/pair ...")
    try:
        r = puck_post("/pair", body, timeout=15)
    except requests.exceptions.ConnectionError as e:
        return fail(f"Lost connection to puck: {e}")

    if not r.ok:
        return fail(f"pair failed {r.status_code}: {r.text}")

    ok("Pair command accepted", r.json() if r.text else {"status": "ok"})


# Mirrors the app's SWD status-check loop: poll /props every 15s, max 18 tries.
PAIR_POLL_INTERVAL = 15
PAIR_POLL_ATTEMPTS = 18


def monitor_pairing(body):
    """Returns "disconnected", "left_ap" or "timeout"."""
    print("\n  Monitoring puck pairing progress (stay on the puck's WiFi)...")
    result = {}
    errors = 0
    for i in range(PAIR_POLL_ATTEMPTS):
        time.sleep(PAIR_POLL_INTERVAL)
        try:
            pr = puck_get("/props", timeout=5)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            # The app treats an unreachable puck as "it left AP mode" and
            # moves straight on to the cloud check.
            print(f"  [{i+1}] Lost connection to puck (it may have switched to home WiFi)")
            return "left_ap"
        if not pr.ok:
            continue
        result = pr.json().get("result", pr.json())
        state = result.get("pairing_state", "?")
        led = result.get("led_pattern", "?")
        reason = result.get("reason", "")
        rssi = result.get("telemetry_rssi", "")
        sta_ssid = result.get("wifi_sta_ssid", "")
        ap_timeout = result.get("timer_wifi_ap_timeout", "")
        extra = ""
        if reason:
            extra += f"  reason={reason}"
        if sta_ssid:
            extra += f"  wifi={sta_ssid}"
        if rssi:
            extra += f"  rssi={rssi}"
        if ap_timeout != "":
            extra += f"  ap_timeout={ap_timeout}"
        print(f"  [{i+1}/{PAIR_POLL_ATTEMPTS}] state={state}  led={led}{extra}")

        if led == "led_purple_solid" and state == "paired":
            ok("Puck reports paired!")
            return disconnect_puck()
        # The app re-sends on this LED unless authenticating; the puck rejects
        # a re-send while "pairing" (error 8: already started), so skip that too.
        if (body and led == "led_blue_purple_blink_slow"
                and state not in ("authenticating", "pairing")):
            print("  Puck is back in pairing mode; re-sending pair command (as the app does)...")
            send_pair(body, fatal=False)
        # The app never special-cases error_pair: it re-sends /pair (above)
        # and keeps polling until it gets "paired" or runs out of attempts.
        if state == "error_pair":
            errors += 1
            print(f"  ⚠  error_pair #{errors}; keeping on as the app does.")

    print("\n  ⚠  Puck never reported 'paired'. Last props:")
    print(f"  {json.dumps(result, indent=2)}")
    return "timeout"


def disconnect_puck():
    # The app sends this once the puck reports paired; it tells the puck to
    # drop its AP and finish connecting to the home network.
    print("  Sending disconnect to puck...")
    try:
        r = requests.post(f"{PUCK_BASE}/disconnect", timeout=8)
        if r.ok:
            ok("Disconnect accepted", r.json() if r.text else {"status": "ok"})
        else:
            print(f"  ⚠  disconnect returned {r.status_code}: {r.text}")
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        print("  Puck dropped the connection (expected once it leaves AP mode).")
    return "disconnected"


# ── verify cloud registration ─────────────────────────────────────────────────

def verify_registration(auth_token, mac_address, prov_id, retries=18, delay=15):
    print("\n  Reconnect your Mac to your home WiFi now.")
    pause("Back on home WiFi")

    headers = {"Authorization": f"Bearer {auth_token}"}
    print(f"  Waiting for puck {mac_address} to come online in the cloud...")
    for i in range(retries):
        try:
            r = requests.get(
                f"{FLO_BASE}/v2/devices",
                headers=headers,
                params={"macAddress": mac_address},
                timeout=15,
            )
        except requests.exceptions.RequestException as e:
            print(f"  ... attempt {i+1}/{retries}: {e}")
            r = None
        if r is not None and r.ok and r.text:
            device = r.json()
            if device.get("isConnected"):
                ok(f"Puck online! device id: {device.get('id')}")
                configure_puck(auth_token, device["id"])
                return device
            print(f"  ... attempt {i+1}/{retries}: found, isConnected=false")
        elif r is not None:
            print(f"  ... attempt {i+1}/{retries}: {r.status_code}")
        time.sleep(delay)

    print("\n  ⚠  Puck never showed as connected in the cloud.")
    print(f"     MAC: {mac_address}  Provisioning id: {prov_id}")


def configure_puck(auth_token, device_id):
    # Final step in the app (SWDProvisioningHelper.configureDevice); without
    # it the app treats the puck as not yet set up.
    r = requests.post(
        f"{FLO_BASE}/v2/devices/{device_id}",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"puckConfig": {"isConfigured": True}},
        timeout=15,
    )
    if r.ok:
        ok("Marked puck as configured")
    else:
        print(f"  ⚠  configure failed {r.status_code}: {r.text}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Moen Smart Leak Detector — Mac onboarding script")
    print("=" * 60)

    email    = prompt("Moen Flo account email")
    password = prompt("Moen Flo account password", secret=True)
    nickname = prompt("Nickname for this detector", default="Leak Detector")

    auth_token, user_id = login(email, password)
    prov_data   = detector_pair_init(auth_token)
    location_id = pick_location(auth_token, user_id)

    puck_props = connect_to_puck()
    check_and_update_firmware(puck_props)

    # Resume a pairing left over from an earlier run instead of re-sending
    # /pair, which the puck rejects once it has started.
    state = puck_props.get("pairing_state", "")
    if state == "paired":
        print("\n  Puck is already paired; skipping straight to disconnect.")
        outcome = disconnect_puck()
    elif state in ("pairing", "authenticating"):
        print(f"\n  Puck is already {state}; monitoring instead of sending a new pair command.")
        outcome = monitor_pairing(None)
    else:
        wifi_ssid, wifi_password, wifi_enc = pick_wifi()
        outcome = pair_puck(prov_data, location_id, wifi_ssid, wifi_password, wifi_enc, nickname)
    if outcome == "timeout":
        ans = prompt("Puck did not finish pairing. Check the cloud anyway? (y/n)", default="n")
        if ans.lower() != "y":
            die("Pairing did not complete. Reset the puck and try again.")
    verify_registration(auth_token, puck_props.get("device_id", ""), prov_data.get("id", ""))

    print("\n✓ Done. Open the Moen Flo app to confirm the detector is online.\n")


if __name__ == "__main__":
    main()
