# Zone Geometry Profile Format

`keylight live --mapper calibrated` uses a JSON profile that defines normalized rectangles for each logical zone.

## Schema

```json
{
  "version": 1,
  "zones": [
    { "zone_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.1, "y1": 0.5 }
  ]
}
```

## Rules

- `version` must be a positive integer.
- `zones` must include every index exactly once from `0` to `N-1`.
- Coordinates are normalized (`0.0..1.0`) and must satisfy:
  - `x0 < x1`
  - `y0 < y1`
- Coordinates are mapped to pixel spans per frame at runtime.

## Starter Profile

- `config/mapping/msi_vector16_2x12.json` provides a baseline 24-zone profile aligned to a 2x12 layout.
- You can copy and edit this file as on-device calibration improves.

## Builder Command

Generate profile files with CLI instead of manual JSON editing:

```powershell
python -m keylight.cli build-zone-profile `
  --rows 2 `
  --columns 12 `
  --column-weights "1,1,1,1,1,1,1,1,1,1,1,1" `
  --output config/mapping/generated.json
```

Advanced options:
- `--row-column-weights` for different column widths per row (`"1,1,2;1,2,1"` format).
- `--x-start/--x-end/--y-start/--y-end` to crop active screen region.
- `--row-direction`, `--column-direction`, and `--serpentine` to match logical zone traversal.
