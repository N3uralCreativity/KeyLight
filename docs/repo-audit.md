# Repository Audit (2026-03-03)

## Summary

The repository is cleanly scaffolded and build tooling is operational, but it is still in pre-implementation state for real hardware and real capture integration.

## What Is Solid

- Python package structure is coherent and minimal.
- Lint/type/test stack is configured and passing.
- Core contracts separate capture, mapping, and driver responsibilities.
- Baseline docs exist for architecture, roadmap, and hardware evidence logging.

## Gaps To Close Before Production

1. Hardware control backend:
  - No implementation for MSI Vector 16 HX AI A2XW zone writes yet.
2. Real screen capture:
  - Only mock gradient capture exists.
3. Calibration system:
  - No persistent profile to map logical zone index to physical zone index.
4. Runtime controls:
  - No config loader, logging, retries, or error recovery path.
5. Conflict handling:
  - Now added preflight script, but full integration into app startup is pending.

## Technical Risks

- Vendor API ambiguity can delay hardware write capability.
- Zone index order may differ from expected 2x12 logical order.
- Conflicting RGB software may reclaim keyboard control during runtime.
- CPU-heavy pixel representation (`list[list[RgbColor]]`) may be insufficient at higher FPS.

## Readiness Actions Already Added

- `docs/sturdy-plan.md` with milestone gates and risk mitigations.
- `scripts/preflight.ps1` for conflict detection/closure before runtime.

## Recommended Immediate Build Order

1. `keylight probe`: identify usable hardware control path.
2. `keylight sweep`: verify all 24 zone indexes physically.
3. Real capture backend implementation with monitor selection.
4. Calibrated mapper + smoothing + brightness cap.
5. Structured runtime logging, retry behavior, and startup preflight integration.

