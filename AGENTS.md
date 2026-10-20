# Agents

## Project Overview

Tools for the Moen Smart Leak Detector (ESP32-WROVER "puck"): onboarding it to the Moen Flo cloud from a Mac, pushing stock firmware over its local AP, and notes from running ESPHome on it.

## Architecture

- **moen_puck_onboard.py** — Interactive onboarding. Logs in to Moen IoT, gets a provisioning token from `api-gw.meetflo.com`, sends `/puck/v1/pair` over the puck's AP, monitors `/props` until paired, then verifies cloud registration. Mirrors the Moen Flo app's `SWDProvisioningHelper` flow.
- **puck_fw_update.py** — Pushes a stock firmware image to `/puck/v1/fwUpdate`.
- **puck_firmware/** — Gitignored. Stock `.bin` images extracted from the Moen Flo APK. Never commit them.
- **ESPHOME.md** — Hardware/GPIO findings and the unsolved temperature/humidity problems.

## Conventions

- Python 3 with `requests` only; no package structure
- `ruff check` must pass
- Conventional Commits for git history
- Release Please for versioning
