# ESPHome on the Moen puck — findings

Notes from running [ESPHome](https://esphome.io) on the Moen Smart Leak Detector ("puck") instead of Moen's cloud firmware. This repo no longer ships an ESPHome build. The last working config is [`moen-puck.yaml` at ce2dd93](https://github.com/zackwag/moen-puck-tools/blob/ce2dd93da69b3409c99f29c5a351113999bc165e/moen-puck.yaml).

**Status:** water detection, battery, LEDs, buzzer and the button work. **Temperature and humidity are unsolved.**

## Hardware

The puck is an ESP32-WROVER (rev 1.0), so it uses the ESPHome `esp32dev` board.

| GPIO | Function | Status | Notes |
|------|----------|--------|-------|
| 27 | Water sensor | Works | Digital input, high when wet |
| 32 | Battery ADC | Works | About 3.0 V fresh, 1.8 V cutoff, 12 dB attenuation |
| 13 | Red LED | Works | PWM, active-low |
| 12 | Blue LED | Works | PWM, active-low, strapping pin (`ignore_strapping_warning`) |
| 18 | Buzzer | Works | PWM piezo, active-high, ~2 kHz |
| 34 | Button | Works | Input-only pin, 10 ms debounce |
| 33 | Sensor power | Required | Must stay configured as an ADC input or the humidity/temperature circuit loses power |
| 35 | Humidity ADC | **Unsolved** | See below |
| ? (ADC2) | Temperature | **Unsolved** | See below |
| 16, 17 | PSRAM | Reserved | Do not use |

## Humidity (unsolved)

The humidity sensor is analog and reads on GPIO 35 (ADC1, so it works while WiFi is on). The ESPHome config applied a two-point linear calibration:

```yaml
filters:
  - calibrate_linear:
      - 0.155 -> 61.0
      - 0.577 -> 95.0
```

Those two points were never checked against a reference across the full range, so the readings can't be trusted yet. Open questions:

- Is the sensor's output actually linear, or does the stock firmware use a curve or lookup table?
- Does the reading depend on temperature? Many capacitive and resistive RH sensors need temperature compensation, so this may be blocked on temperature.
- Does the sensor need time to settle after GPIO 33 powers the circuit?

## Temperature (unsolved)

The stock firmware reads temperature with the ESP32's **ULP coprocessor** from an **ADC2** channel. The main CPU can't use ADC2 while WiFi is running (an ESP32 hardware limitation), so a normal ESPHome `adc` sensor can't read it.

Ideas that haven't been tried yet:

1. **Find the channel.** Disassemble the ULP program in the stock image (`1.2.1.bin`) to see which ADC2 channel/GPIO it samples and how it converts the raw value.
2. **Read before WiFi starts.** Sample ADC2 in an `on_boot` hook that runs before WiFi starts, then publish the value once connected. This works best with deep sleep, where every wake is a fresh boot.
3. **Use the ULP like stock does.** ESPHome has no built-in ULP support, so this would need an external component.

## Flashing and reverting

- **Installing:** the stock firmware's local OTA endpoint, `POST http://192.168.4.1/puck/v1/fwUpdate` (raw `application/octet-stream`), accepts any valid ESP32 app image, including ESPHome's `firmware.ota.bin`. Join the puck's `FloDetector-XXXX` AP first. Battery must be at least 30%.
- **What it leaves alone:** this path only writes the inactive app slot. The stock bootloader, partition table and NVS (radio MAC and calibration) are not rewritten.
- **Reverting to stock:** ESPHome's own OTA (`esphome` platform, port 3232) is also a generic app-slot writer, so pushing the stock `1.2.1.bin` through it boots back into Moen firmware cleanly. If the config uses deep sleep, the puck is only awake for a few seconds per wake. Start the OTA handshake inside that window; once the data phase begins, the puck can't sleep until the transfer finishes. A failed attempt is safe because ESPHome only switches boot slots after a verified write.
- **Targeting:** on a network with other ESPHome devices, confirm the puck by its MAC or `board: esp32dev` in the mDNS TXT records before flashing. A sweep by IP can hit the wrong device.
