# moen-puck-tools

Tools for the Moen Smart Leak Detector ("puck"):

- **`moen_puck_onboard.py`** onboards a puck to your Moen Flo account from a Mac, with no phone app needed.
- **`puck_fw_update.py`** pushes stock Moen firmware to a puck over its local WiFi AP.
- **[ESPHOME.md](ESPHOME.md)** collects findings from running ESPHome on the puck. Temperature and humidity are still unsolved.

The onboarding flow and endpoints were reverse-engineered from the Moen Flo Android app (v3.60.0.7869).

## Prerequisites

- Python 3 and `requests`:

  ```sh
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  ```

- A Moen Flo account with at least one location.
- Stock firmware images in `puck_firmware/` (only needed for firmware updates; see [Firmware](#firmware)).

## Onboarding a puck

```sh
.venv/bin/python moen_puck_onboard.py
```

The script walks through six steps:

1. Logs in to Moen IoT with your Flo email and password.
2. Requests a provisioning token from the Flo cloud.
3. Picks your Flo location.
4. Asks you to put the puck in pairing mode (hold the button until it flashes) and join its `FloDetector-XXXX` WiFi. It then reads the puck's info and offers a firmware update if the puck is older than 1.2.1.
5. Lists the networks the puck can see (one entry per SSID, strongest signal first) and asks for your home WiFi.
6. Sends the pair command, watches the puck until it reports `paired`, and tells it to leave AP mode. After you rejoin your home WiFi, it waits for the puck to come online in the cloud and marks it configured.

Then open the Moen Flo app to confirm the detector is online.

**WiFi encryption:** the puck's scan sometimes reports a secured network as `enc=none`. If you enter a password, the script defaults to `wpa2-psk`. You can still override it at the prompt.

If the puck was already mid-pairing from an earlier run, the script picks up where it left off instead of sending a new pair command, which the puck would reject.

## Firmware

The Moen Flo app bundles stock puck firmware in its APK under `assets/firmware/` (`1.2.1.bin` and `1.2.6.bin`). The app installs 1.2.1. The images are Moen's, so they aren't committed here (`*.bin` is gitignored). To get them, extract them from the APK:

```sh
mkdir -p puck_firmware
unzip -j moen-flo.apk 'assets/firmware/*' -d puck_firmware
```

To update a puck outside of onboarding, run the script and then join the puck's `FloDetector-XXXX` WiFi:

```sh
.venv/bin/python puck_fw_update.py                         # defaults to puck_firmware/1.2.1.bin
.venv/bin/python puck_fw_update.py puck_firmware/1.2.6.bin
```

The script checks that the file is an ESP32 app image for project `puck` and skips the update if the puck is already on that version or newer. The upload goes to `POST /puck/v1/fwUpdate`.

## Puck local API

While in pairing mode, the puck serves `http://192.168.4.1/puck/v1/` on its own AP:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/props` | GET | Device ID (WiFi MAC), serial, firmware, pairing state, LED pattern, telemetry |
| `/scanList` | GET | WiFi networks the puck can see |
| `/pair` | POST | WiFi credentials, provisioning token, location, nickname |
| `/disconnect` | POST | Leave AP mode once paired |
| `/fwUpdate` | POST | Raw ESP32 app image (`application/octet-stream`) |

## Files

| File | Purpose |
|------|---------|
| `moen_puck_onboard.py` | Onboard a puck to Moen Flo from a Mac |
| `puck_fw_update.py` | Push stock firmware over the puck's AP |
| `ESPHOME.md` | ESPHome hardware findings and open problems |
| `scripts/configure-repo.sh` | GitHub repo settings (squash-merge, branch protection) |
