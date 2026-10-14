# moen-puck-esphome

Custom [ESPHome](https://esphome.io) firmware for the Moen Smart Leak Detector ("puck"), replacing the stock cloud-dependent firmware with a fully local Home Assistant integration.

## Features

| Feature | GPIO | Notes |
|---------|------|-------|
| Humidity | 35 | Analog sensor, calibrated |
| Water Detection | 27 | Binary moisture sensor |
| Battery | 32 | ADC with percentage calculation |
| Red LED | 13 | PWM, active-low |
| Blue LED | 12 | PWM, active-low |
| Buzzer | 18 | PWM piezo |
| Button | 34 | Input with debounce |

The humidity sensor is powered by the battery rail through GPIO 33 (kept as an ADC input to maintain power).

### Known Limitations

**Temperature** is read by the stock firmware via the ESP32 ULP coprocessor from an ADC2 channel, which cannot be accessed by the main CPU while WiFi is active. This is a hardware limitation of the ESP32.

## Prerequisites

- Python 3
- [ESPHome](https://esphome.io) (`pip install esphome`)
- The puck must have battery level >= 30%

## Setup

1. **Configure WiFi and compile firmware:**

   ```sh
   ./setup.sh
   ```

2. **Connect to the puck's WiFi AP** (`FloDetector-XXXX`) from your computer.

3. **Flash the firmware:**

   ```sh
   python3 flash_ota.py
   ```

   This reads the puck's serial number, sets it as the hostname (e.g., `fb256859cbcj.local`), compiles, and flashes over HTTP.

4. **Reconnect to your home WiFi.** The puck will join the network you configured and appear in Home Assistant.

## Updating

Once running ESPHome, future updates are flashed over-the-air:

```sh
esphome upload moen-puck.yaml --device <puck-ip>
```

## Files

| File | Purpose |
|------|---------|
| `moen-puck.yaml` | ESPHome device configuration |
| `secrets.yaml.example` | Template for WiFi/API credentials |
| `setup.sh` | Interactive first-time setup |
| `flash_ota.py` | Flashes firmware to stock puck via HTTP OTA |
| `scripts/configure-repo.sh` | GitHub repo settings (squash-merge, branch protection) |
