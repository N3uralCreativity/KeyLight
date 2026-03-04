# Implementation Roadmap

## Phase 0: Foundation (Done)

- Clean repository structure.
- Core interfaces and pipeline skeleton.
- Basic mapper + simulator driver + unit tests.
- Dev tooling (`ruff`, `mypy`, `pytest`) and helper scripts.

## Phase 1: Hardware Discovery

- Confirm control method for MSI Vector 16 HX AI A2XW 24-zone keyboard.
- Build a minimal "set single zone color" hardware probe.
- Validate zone index order against physical keyboard.

Exit criteria:
- Reliable write access to all 24 zones.

## Phase 2: Real Capture + Mapping

- Implement Windows screen capture backend.
- Implement calibrated zone geometry for the keyboard.
- Add temporal smoothing and brightness limiter.

Exit criteria:
- Screen colors map to correct zones with low latency and stable transitions.

Current progress:
- Basic live runtime command (`keylight live`) is implemented with optional `windows-mss` capture and color processing.
- `keylight live` supports TOML defaults via `config/default.toml` (CLI flags override).
- Runtime includes bounded error retry/backoff controls (`max_consecutive_errors`, `error_backoff_ms`, `stop_on_error`).
- Calibrated zone geometry mapper is implemented (`--mapper calibrated --zone-profile <json>`).
- Zone geometry profile builder command is implemented (`build-zone-profile`).
- Guided zone-index calibration workflow is implemented (`calibrate-zones`).
- `calibrate-zones` supports post-build verification sweeps (`--verify`, `--verify-output`).
- `calibrate-zones` supports short live-runtime verification (`--verify-live`).
- Live runtime writes a structured JSON report (`artifacts/live_report.json`) with iteration/error/timing metrics.
- Live runtime supports periodic watchdog snapshots (`--watchdog-interval`, `--watchdog-output`).
- Live runtime supports persistent JSONL event logs (`--event-log-interval`, `--event-log-output`).
- Live runtime supports bounded driver recovery attempts (`--reconnect-on-error`, `--reconnect-attempts`).
- Live runtime supports fixed-duration sessions via `--duration-seconds` (auto-computes iterations from FPS).
- Post-run quality gating command is available (`analyze-live`) for threshold-based pass/fail checks.
- Live reports include frame pacing metrics (`effective_fps`, `overrun_iterations`, `avg_overrun_ms`).
- Post-run quality gating supports frame pacing thresholds (`--min-effective-fps`, `--max-overrun-percent`).
- Environment readiness gating command is available (`readiness-check`) for launch preconditions.
- Live runtime supports optional exit-state restore (`--restore-on-exit`, `--restore-color`).
- Guided hardware finalization script is available (`scripts/finalize-hardware.ps1`).
- Long-run helper supports optional pre-run readiness gates (`scripts/longrun.ps1 -RunReadinessCheck`).
- Readiness gates support strict production checks (hardware backend, calibrated mapper, non-identity calibration profile).
- Readiness gates can require calibration workflow evidence (`profile_built`, verify executed/live-verify success, zone-count match).
- Readiness gates support calibration profile freshness checks (`max-calibration-profile-age-seconds`).
- Calibration profiles now include provenance metadata (`generated_at_utc`, method, observed_order, workflow path) for deterministic auditability.
- Readiness gates can require preflight quality evidence (`is_admin`, `strict_mode`, no `access_denied_count`).
- Readiness gates can enforce calibration profile metadata quality and workflow linkage (`--require-calibration-profile-generated-timestamp`, `--require-calibration-profile-provenance`, `--require-calibration-profile-provenance-workflow-match`).
- Readiness gates can enforce analysis-threshold policy (ensure analysis run used strict enough limits).
- Readiness gates support optional artifact freshness checks (`--max-preflight-age-seconds`, `--max-live-analysis-age-seconds`).
- Readiness gate can optionally run preflight inline before evaluation (`readiness-check --run-preflight`).
- Runtime config builder command is available (`build-runtime-config`) for reproducible hardware profile generation.
- One-command strict production runner is available (`run-production`) to chain readiness -> live -> analysis.
- Interactive observed-order capture command is available (`capture-observed-order`).
- Strict preflight mode is available (`--strict-preflight`, script `-StrictMode`).
- Preflight writes a structured conflict report artifact (`artifacts/preflight_report.json`) every run.

## Phase 3: Runtime Hardening

- Add reconnection logic and error recovery.
- Add performance metrics (capture time, map time, send time).
- Add profile/config loading (`fps`, smoothing, brightness cap, monitor selection).

Exit criteria:
- Stable long-run behavior without manual intervention.

## Phase 4: App UX

- Add system tray app or lightweight GUI.
- Add preset management and startup behavior.
- Build packaged Windows release.

Exit criteria:
- One-click launch and user-friendly control surface.
