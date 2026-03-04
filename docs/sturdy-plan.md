# Sturdy Implementation Plan

## Objective

Build a reliable Windows app that maps live screen colors to the correct 24 keyboard zones on MSI Vector 16 HX AI A2XW with low latency and stable long-run behavior.

## Constraints

- Keyboard control path is not yet confirmed (MSI API vs SteelSeries vs direct HID).
- Real-time loops must keep stable frame pacing under CPU/GPU load.
- Other RGB/overlay apps can contend for lighting control or degrade capture stability.

## Success Criteria

- Correct 24-zone physical alignment (validated by on-device sweep tests).
- End-to-end latency low enough to feel synchronized (target p95 under 80 ms).
- Stable run for 8+ hours without crashing or losing keyboard control.
- Deterministic preflight process that handles app conflicts before runtime.

## Milestones

### M1. Hardware Discovery and Control Path

- Build a hardware probe CLI to enumerate candidate providers and devices.
- Implement one-zone color write tests for each candidate backend.
- Record evidence in `docs/hardware-notes.md`.

Acceptance gate:
- We can set an arbitrary color on any chosen zone repeatedly.

### M2. Zone Index Mapping and Calibration

- Add zone sweep utility (0..23) with visible delay between writes.
- Build a calibration profile format mapping logical zones to physical firmware indexes.
- Validate left-to-right and top-to-bottom behavior on-device.

Acceptance gate:
- All 24 zones map correctly with stored calibration profile.

### M3. Real Screen Capture Backend

- Implement Windows capture backend with monitor selection.
- Add frame downscaling path dedicated to zone-mapping workload.
- Add capture timing metrics.

Acceptance gate:
- Stable capture at configured FPS (30/60) with no memory growth.

### M4. Mapping and Color Pipeline

- Add calibrated zone geometry mapper (not just rectangular grid).
- Add smoothing filter and brightness limiter.
- Add gamma/white-balance correction hooks.

Acceptance gate:
- Visually stable transitions with no flicker in dynamic scenes.

### M5. Runtime Reliability

- Add retry/reconnect strategy for temporary driver failures.
- Add watchdog-style health signals and structured logs.
- Add graceful shutdown that restores previous lighting state (optional toggle).

Acceptance gate:
- Runtime survives transient errors and exits cleanly.

### M6. Conflict Management and Preflight

- Maintain known conflict app list (RGB controllers + overlays).
- Add startup preflight to detect and close/skip based on policy.
- Log exactly what was terminated before runtime starts.

Acceptance gate:
- Startup is deterministic with explicit conflict report every run.

### M7. Packaging and UX

- Add production CLI entry with config profiles.
- Add optional tray UI for quick start/stop/profile switching.
- Package as Windows distributable.

Acceptance gate:
- Single-command or one-click launch with persistent settings.

## Risk Register

- Unknown vendor protocol:
  - Mitigation: multi-backend probe tooling early (M1) before capture tuning.
- Zone order mismatch:
  - Mitigation: mandatory calibration profile and sweep verification (M2).
- Capture jitter/perf issues:
  - Mitigation: frame downscaling + timing metrics + pacing guards (M3/M4).
- App conflicts:
  - Mitigation: enforced preflight closure + conflict allowlist policy (M6).
- Hardware lockups:
  - Mitigation: bounded retries, cooldown backoff, and safe fallback behavior (M5).

## Immediate Next Steps

1. Implement `drivers/probe.py` and CLI command `keylight probe`.
2. Add first real Windows capture backend abstraction.
3. Build `keylight sweep` command for physical zone calibration.
4. Extend tests for calibration profile parsing and mapper correctness.

