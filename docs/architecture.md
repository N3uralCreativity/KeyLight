# Architecture Baseline

## Goal

Map live screen colors to the correct physical zones on the MSI Vector 16 HX AI A2XW 24-zone RGB keyboard.

## Core Runtime Flow

1. `ScreenCapturer` provides a frame.
2. `ZoneMapper` converts frame regions into 24 RGB zone colors.
3. `KeyboardLightingDriver` applies colors to the keyboard.
4. `Pipeline` repeats at target FPS.

## Design Principles

- Hardware isolation: keep vendor/protocol-specific code in `drivers/`.
- Algorithm isolation: keep zone mapping and smoothing independent from hardware APIs.
- Deterministic testing: run mapper and pipeline logic via mocked frames and simulated driver.
- Runtime safety: clamp colors, limit update rate, and fail fast on driver errors.

## Planned Components

- `capture/windows_graphics.py` (future):
  - Windows desktop capture backend.
  - Optional monitor selection.
- `mapping/grid_mapper.py`:
  - Stable reference implementation using rectangular grid zones.
  - Supports arbitrary `rows x columns`.
- `mapping/calibrated_mapper.py`:
  - Uses custom normalized zone rectangles from JSON profile files for better physical alignment.
  - Current starter profile: `config/mapping/msi_vector16_2x12.json`.
- `drivers/msi_vector16.py` (future):
  - Real keyboard backend for MSI Vector 16 HX AI A2XW.
- `drivers/msi_mystic_hid.py`:
  - Experimental HID backend targeting `VID 0x1462 / PID 0x1603` (`MysticLight MS-1603`).
  - Uses templated per-zone packet writes and configurable report parameters.
- `drivers/simulated.py`:
  - Debug backend for local algorithm development.

## Known Unknowns (Hardware)

- Exact software/API path required to write 24 zones on this model:
  - MSI Center SDK?
  - SteelSeries Engine/GG local API?
  - HID/USB vendor protocol?
- Zone indexing order expected by the firmware.
- Maximum stable update rate before dropped updates or keyboard-side buffering.
