# Hardware Notes: MSI Vector 16 HX AI A2XW (24-Zone RGB)

This file tracks facts verified on-device and should stay strictly evidence-based.

## Device Facts To Confirm

- Keyboard vendor path:
  - MSI-only API
  - SteelSeries API
  - Direct HID protocol
- Zone count and firmware zone index order.
- Minimum and maximum practical update rates.
- Persistence behavior (does lighting reset on sleep/restart/brightness keys?).

## Test Checklist

- Can we set one zone to red reliably?
- Can we sweep all 24 zones in sequence?
- Do written zone indexes align physically left-to-right and top-to-bottom?
- What happens if updates arrive faster than 30/60 FPS?

## Evidence Log Template

- Date:
- Tool/Method:
- Result:
- Confidence:
- Notes:

## Evidence Log

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli probe`
- Result: Candidate services detected (`MSI Foundation Service`, `MSI_Center_Service`, related MSI services). Candidate devices include `ACPI\\MSI0007\\...` keyboard path. Likely control paths: MSI service bridge, direct HID vendor protocol.
- Confidence: Medium
- Notes: SteelSeries path not observed in current probe output.

- Date: 2026-03-03
- Tool/Method: `powershell -ExecutionPolicy Bypass -File .\\scripts\\preflight.ps1`
- Result: `NVIDIA Overlay` processes closed successfully. `LEDKeeper2`, `logi_lamparray_service`, and `wallpaperservice32` failed to close due access denied.
- Confidence: High
- Notes: Run terminal as Administrator for forced closure of protected RGB services before hardware write tests.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli sweep --zone-count 24 --loops 1 --delay-ms 50`
- Result: Sweep command executed 24 zone steps and wrote `artifacts/sweep_report.json`. Preflight ran automatically and closed `NVIDIA Overlay` processes.
- Confidence: High
- Notes: Current sweep backend is simulated only; no physical keyboard write yet.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli write-zone --list-hid`
- Result: Enumerated HID devices and detected MSI candidate `VID=0x1462 PID=0x1603 Product='MysticLight MS-1603'`.
- Confidence: High
- Notes: Candidate path: `\\?\HID#VID_1462&PID_1603#6&a3fe5ce&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}`.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli write-zone --backend hid-raw ...` using MSI candidate HID path.
- Result: Device opens, but write fails with parameter errors for both output and feature methods (`WriteFile/HidD_SetFeature: 0x57`), including test with 65-byte padded packet.
- Confidence: High
- Notes: Control path seems reachable, but packet structure/length/report ID is still unknown.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli discover-hid --hid-path <MysticLight path> --report-ids "0,1,2,3" --pad-lengths "8,16,32,64,65" --delay-ms 0`
- Result: 160 attempts, 80 successful writes. Success pattern: output accepted report IDs 1 and 3; feature accepted report IDs 1 and 2. Success observed across all tested templates and pad lengths.
- Confidence: Medium
- Notes: Promising low-level acceptance signal; next step is verify which accepted packet actually changes keyboard zones.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli discover-effects --hid-path <MysticLight path> --max-steps 8 --step-delay-ms 300`
- Result: 8/8 accepted-combo steps wrote successfully and were logged with candidate name, zone, color, method, and report ID in `artifacts/effect_verify_report.json`.
- Confidence: Medium
- Notes: Physical visual confirmation per step is still required from operator observation.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli sweep --backend msi-mystic-hid --hid-path <MysticLight path> --zone-count 4 --loops 1 --delay-ms 150`
- Result: Sweep executed end-to-end with the new MSI HID driver and wrote report `artifacts/sweep_msi_report.json` (4 steps, no runtime errors).
- Confidence: Medium
- Notes: Confirms integrated backend stability; full 24-zone physical verification still required.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli sweep --backend msi-mystic-hid --hid-path <MysticLight path> --zone-count 24 --loops 1 --delay-ms 500`
- Result: Full 24-step sweep completed and wrote `artifacts/sweep_msi_24_report.json`.
- Confidence: Medium
- Notes: Preflight still unable to close `LEDKeeper2` and some RGB services without admin elevation.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli init-calibration --zone-count 24 --output config/calibration/default.json`
- Result: Identity logical->hardware calibration profile created.
- Confidence: High
- Notes: This is a placeholder profile; real mapping should be updated after physical observation.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli sweep --backend msi-mystic-hid --calibration-profile config/calibration/default.json --zone-count 24 --loops 1 --delay-ms 50`
- Result: Calibrated sweep path executed successfully and wrote `artifacts/sweep_msi_calibrated_report.json`.
- Confidence: Medium
- Notes: Confirms profile loading/remap path works with hardware backend.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli build-calibration --zone-count 24 --order "...24 values..." --output config/calibration/observed.json`
- Result: Observed-order calibration profile generation command executed successfully.
- Confidence: High
- Notes: Enables direct conversion from sweep observation sequence into logical->hardware mapping profile.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli list-monitors`
- Result: `windows-mss` capture backend enumerated monitor index `1` at `2560x1600`.
- Confidence: High
- Notes: Confirms capture dependency (`mss`) and monitor discovery path work in current environment.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli live --config config/default.toml --capturer windows-mss --backend simulated --iterations 3 --no-preflight`
- Result: Live runtime completed 3/3 frames with zero errors; average total frame time ~85.98 ms.
- Confidence: High
- Notes: Validates end-to-end live path (capture -> map -> process -> send) with real desktop capture and simulated driver.

- Date: 2026-03-03
- Tool/Method: `scripts/preflight.ps1` (normal and `-AggressiveMsiClose`)
- Result: Conflicting RGB/overlay/MSI processes were detected, but close attempts failed due access-denied protections.
- Confidence: High
- Notes: For reliable hardware writes, run elevated PowerShell as Administrator before preflight/live sessions.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli live --capturer mock --mapper calibrated --zone-profile config/mapping/msi_vector16_2x12.json --backend simulated --iterations 5 --no-preflight`
- Result: Calibrated mapper path executed 5/5 frames with zero runtime errors.
- Confidence: High
- Notes: Confirms profile loader + calibrated zone mapping integration in live runtime. Report written to `artifacts/live_report_calibrated.json`.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli live --capturer windows-mss --backend simulated --iterations 3 --output artifacts/live_report_mss.json --no-preflight`
- Result: Live runtime completed 3/3 frames with zero runtime errors; average total frame time ~77.65 ms.
- Confidence: High
- Notes: Confirms structured live report output path and real desktop capture integration (`artifacts/live_report_mss.json`).

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli build-zone-profile --rows 2 --columns 12 --output config/mapping/generated.json`
- Result: Zone profile builder command generated valid calibrated mapping JSON.
- Confidence: High
- Notes: Enables fast geometry iteration without manual JSON authoring.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli calibrate-zones --backend simulated --zone-count 4 --delay-ms 0 --no-preflight`
- Result: Sweep executed and workflow generated observed-order template + workflow report (`artifacts/observed_order_template_sim.txt`, `artifacts/calibrate_report_sim.json`).
- Confidence: High
- Notes: Confirms guided calibration workflow path before hardware-specific run.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli calibrate-zones --backend simulated --zone-count 4 --observed-order "2,0,3,1" --delay-ms 0 --no-preflight`
- Result: Calibration profile generated with workflow report (`config/calibration/final_sim.json`, `artifacts/calibrate_report_sim_profile.json`).
- Confidence: High
- Notes: Confirms sweep + observed-order -> profile generation in a single command.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli calibrate-zones --backend simulated --zone-count 4 --observed-order "2,0,3,1" --verify --verify-delay-ms 0 --no-preflight`
- Result: Calibration workflow completed with verify sweep (`artifacts/calibrate_verify_sim.json`) and report (`artifacts/calibrate_report_verify_sim.json`).
- Confidence: High
- Notes: Confirms post-profile verification sweep path and verify metrics in workflow report.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli calibrate-zones --backend simulated --zone-count 4 --no-sweep --verify --profile-output config/calibration/final_verify_sim.json --verify-delay-ms 0 --no-preflight`
- Result: Existing calibration profile loaded and verified without rerunning initial sweep (`artifacts/calibrate_verify_existing_sim.json`).
- Confidence: High
- Notes: Confirms no-sweep verification mode for already-generated profiles.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli calibrate-zones --backend simulated --zone-count 4 --observed-order "2,0,3,1" --verify-live --live-capturer mock --live-rows 2 --live-columns 2 --live-fps 120 --live-iterations 3 --no-preflight`
- Result: Calibration workflow generated profile and completed short live verification runtime (`artifacts/calibrate_live_verify_sim.json`).
- Confidence: High
- Notes: Confirms end-to-end calibration profile application in live runtime path.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli calibrate-zones --backend simulated --zone-count 4 --no-sweep --verify-live --profile-output config/calibration/final_live_verify_sim.json --live-capturer mock --live-rows 2 --live-columns 2 --live-fps 120 --live-iterations 2 --no-preflight`
- Result: Existing profile loaded and verified via short live runtime without rerunning initial sweep (`artifacts/calibrate_live_verify_existing_sim.json`).
- Confidence: High
- Notes: Confirms no-sweep live verification mode for already-generated profiles.

- Date: 2026-03-03
- Tool/Method: `python -m keylight.cli live --capturer mock --backend simulated --rows 2 --columns 2 --iterations 3 --watchdog-interval 1 --watchdog-output artifacts/live_watchdog_smoke.json --no-preflight`
- Result: Live runtime completed and wrote watchdog snapshots every iteration (`artifacts/live_watchdog_smoke.json`).
- Confidence: High
- Notes: Confirms watchdog heartbeat artifact path for long-run health monitoring.

- Date: 2026-03-03
- Tool/Method: `scripts/preflight.ps1 -StrictMode` and `python -m keylight.cli live ... --strict-preflight`
- Result: Strict preflight failed when unresolved conflict processes remained active.
- Confidence: High
- Notes: Confirms fail-fast startup policy for protected/conflicting RGB services.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli live --capturer mock --backend simulated --rows 2 --columns 2 --fps 120 --iterations 3 --reconnect-on-error --reconnect-attempts 2 --no-preflight --output artifacts/live_report_recovery_smoke.json`
- Result: Live runtime completed and emitted recovery metrics in report (`recovery_attempts`, `recovery_successes`).
- Confidence: High
- Notes: Confirms runtime recovery instrumentation path and CLI flags are wired end-to-end.

- Date: 2026-03-03
- Tool/Method: `powershell -ExecutionPolicy Bypass -File .\\scripts\\preflight.ps1`
- Result: Preflight generated structured report `artifacts/preflight_report.json` with detected process list, closure outcomes, and unresolved count.
- Confidence: High
- Notes: Confirms deterministic preflight artifact output for startup conflict auditing.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli live --capturer mock --backend simulated --rows 2 --columns 2 --fps 120 --iterations 4 --event-log-interval 1 --event-log-output artifacts/live_events_smoke.jsonl --no-preflight --output artifacts/live_report_eventlog_smoke.json`
- Result: Live runtime completed with `event_log_emits=4` and appended per-iteration JSONL entries to `artifacts/live_events_smoke.jsonl`.
- Confidence: High
- Notes: Confirms persistent runtime event logging for long-run validation traces.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli live --capturer mock --backend simulated --rows 2 --columns 2 --fps 10 --duration-seconds 1.2 --no-preflight --output artifacts/live_report_duration_smoke.json`
- Result: Live runtime computed and executed 12 iterations from duration mode (`duration-seconds * fps`).
- Confidence: High
- Notes: Confirms fixed-duration long-run workflow without manual iteration calculation.

- Date: 2026-03-03
- Tool/Method: `powershell -ExecutionPolicy Bypass -File .\\scripts\\longrun.ps1 -DurationHours 0.0004 -NoPreflight -UseMock -WatchdogInterval 1 -EventLogInterval 1`
- Result: Long-run helper executed end-to-end and generated timestamped live report, watchdog snapshot, and event-log artifacts.
- Confidence: High
- Notes: Confirms one-command long-run harness flow for extended validation sessions.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli analyze-live --report artifacts/live_report_eventlog_smoke.json --event-log artifacts/live_events_smoke.jsonl --output artifacts/live_analysis_smoke.json`
- Result: Analysis command completed with pass/fail metrics and wrote threshold-evaluation report.
- Confidence: High
- Notes: Confirms post-run quality gate workflow for automated validation.

- Date: 2026-03-03
- Tool/Method: `powershell -ExecutionPolicy Bypass -File .\\scripts\\longrun.ps1 -DurationHours 0.0003 -NoPreflight -UseMock -WatchdogInterval 1 -EventLogInterval 1`
- Result: Long-run helper executed runtime plus automatic `analyze-live` post-check and produced timestamped analysis artifact.
- Confidence: High
- Notes: Confirms end-to-end unattended long-run + quality gate loop.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli live --capturer mock --backend simulated --rows 2 --columns 2 --fps 120 --iterations 2 --restore-on-exit --restore-color 0,0,0 --no-preflight --output artifacts/live_report_restore_smoke.json`
- Result: Live runtime completed and report recorded `restore_requested=true` and `restore_applied=true`.
- Confidence: High
- Notes: Confirms optional shutdown restore behavior for deterministic keyboard exit state.

- Date: 2026-03-03
- Tool/Method: `powershell -ExecutionPolicy Bypass -File .\\scripts\\longrun.ps1 -DurationHours 0.0002 -NoPreflight -UseMock -WatchdogInterval 1 -EventLogInterval 1 -RestoreOnExit -RestoreColor 0,0,0`
- Result: Long-run helper executed runtime, restore-on-exit, and post-run analysis; timestamped artifacts were generated successfully.
- Confidence: High
- Notes: Confirms unattended long-run flow with deterministic restore state on exit.

- Date: 2026-03-03
- Tool/Method: `powershell -ExecutionPolicy Bypass -File .\\scripts\\finalize-hardware.ps1 -Backend simulated -ZoneCount 4 -DelayMs 0 -TemplateOnly -NoPreflight`
- Result: Finalize script template mode executed sweep and produced observed-order template artifact.
- Confidence: High
- Notes: Confirms guided hardware-finalization phase-1 workflow command path.

- Date: 2026-03-03
- Tool/Method: `powershell -ExecutionPolicy Bypass -File .\\scripts\\finalize-hardware.ps1 -Backend simulated -ZoneCount 4 -DelayMs 0 -ObservedOrderFile artifacts/observed_order_template_sim_filled.txt -NoPreflight -SkipVerifyLive`
- Result: Finalize script phase-2 built profile and executed verification sweep using provided observed-order file.
- Confidence: High
- Notes: Confirms guided hardware-finalization phase-2 workflow command path.

- Date: 2026-03-03
- Tool/Method: `powershell -ExecutionPolicy Bypass -File .\\scripts\\finalize-hardware.ps1 -Backend msi-mystic-hid -HidPath "\\\\?\\HID#VID_1462&PID_1603#6&a3fe5ce&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}" -ZoneCount 24 -DelayMs 1000 -TemplateOnly -NoPreflight`
- Result: Real hardware template sweep executed 24 steps and wrote `artifacts/observed_order_template_hardware_round2.txt`.
- Confidence: Medium
- Notes: Next operator action is to fill `observed_order` from physical observation and rerun finalize script phase-2.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config config/default.toml --require-hardware-backend --require-preflight-clean --require-live-analysis-pass --live-analysis-report artifacts/live_analysis_20260303_223726.json --output artifacts/readiness_report_hardware_gate_smoke.json`
- Result: Readiness gate failed as expected (`backend_is_not_hardware:simulated`, `preflight_unresolved_count=9`).
- Confidence: High
- Notes: Confirms fail-fast guardrails before real hardware validation runs.

- Date: 2026-03-03
- Tool/Method: `powershell -ExecutionPolicy Bypass -File .\\scripts\\longrun.ps1 -DurationHours 0.0001 -NoPreflight -UseMock -WatchdogInterval 1 -EventLogInterval 1 -RunReadinessCheck`
- Result: Long-run helper executed readiness check, runtime, and analysis successfully with readiness artifact.
- Confidence: High
- Notes: Confirms unattended long-run flow with pre-run readiness gate support.

- Date: 2026-03-03
- Tool/Method: `powershell -ExecutionPolicy Bypass -File .\\scripts\\longrun.ps1 -DurationHours 0.0001 -NoPreflight -UseMock -WatchdogInterval 1 -EventLogInterval 1 -RunReadinessCheck -RequireHardwareBackend`
- Result: Long-run helper aborted before runtime because readiness gate failed on non-hardware backend.
- Confidence: High
- Notes: Confirms strict hardware-backend gate behavior blocks incorrect launch configs.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config config/default.toml --require-hardware-backend --require-calibrated-mapper --require-calibration-profile --forbid-identity-calibration --require-preflight-clean --output artifacts/readiness_report_strict_hardware_profile_gate_smoke.json`
- Result: Readiness gate failed with explicit reasons (`backend_is_not_hardware`, `mapper_is_not_calibrated`, `calibration_profile_missing`, `preflight_unresolved_count`).
- Confidence: High
- Notes: Confirms stronger production launch preconditions before long real-device sessions.

- Date: 2026-03-03
- Tool/Method: `powershell -ExecutionPolicy Bypass -File .\\scripts\\longrun.ps1 -DurationHours 0.0001 -NoPreflight -UseMock -WatchdogInterval 1 -EventLogInterval 1 -RunReadinessCheck -RequireHardwareBackend -RequireCalibratedMapper -RequireCalibrationProfile -ForbidIdentityCalibration`
- Result: Long-run helper aborted before runtime because strict readiness preconditions were not met.
- Confidence: High
- Notes: Confirms pre-run block path when calibration/hardware requirements are missing.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli build-runtime-config --base config/default.toml --output config/hardware-generated.toml --set-hardware-mode --set-longrun-mode --hid-path "<HID_PATH>" --zone-profile config/mapping/msi_vector16_2x12.json --calibration-profile config/calibration/observed.json`
- Result: Hardware-oriented runtime config generated with calibrated mapper, MSI backend, strict preflight, watchdog, event-log, and restore settings.
- Confidence: High
- Notes: Confirms reproducible runtime profile generation command for deployment/validation.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config config/hardware-generated.toml --require-hardware-backend --require-calibrated-mapper --require-calibration-profile --forbid-identity-calibration --no-require-preflight-clean`
- Result: Strict readiness failed on `calibration_profile_is_identity`.
- Confidence: High
- Notes: Confirms identity calibration is now explicitly blocked by strict readiness gate.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config config/hardware-generated.toml --require-hardware-backend --require-calibrated-mapper --require-calibration-profile --no-forbid-identity-calibration --no-require-preflight-clean`
- Result: Relaxed readiness passed for generated hardware config.
- Confidence: High
- Notes: Confirms strict-vs-relaxed readiness policy behavior is functioning.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli capture-observed-order --backend simulated --zone-count 4 --profile-output config/calibration/interactive_smoke.json --observed-output artifacts/observed_order_interactive_smoke.txt --no-preflight`
- Result: Interactive observed-order command captured responses and wrote both observed-order text and calibration profile outputs.
- Confidence: High
- Notes: Confirms direct interactive mapping workflow as an alternative to manual template editing.

- Date: 2026-03-03
- Tool/Method: `powershell -ExecutionPolicy Bypass -File .\\scripts\\preflight.ps1 -AggressiveMsiClose -ReportPath artifacts/preflight_report.json`
- Result: Preflight detected 9 known conflict processes and attempted closure, but all close attempts failed with `Access is denied`; report timestamp refreshed.
- Confidence: High
- Notes: Confirms conflict detection/closure path works, but Administrator elevation remains required for protected MSI/overlay services.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config config/hardware-generated.toml --require-hardware-backend --require-calibrated-mapper --require-calibration-profile --forbid-identity-calibration --require-preflight-clean --max-preflight-age-seconds 900 --output artifacts/readiness_report_generated_config_strict.json`
- Result: Strict readiness failed on `calibration_profile_is_identity` and `preflight_unresolved_count=9`; preflight freshness gate passed.
- Confidence: High
- Notes: Confirms new artifact-age gating behavior and precise remaining production blockers.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config config/hardware-generated.toml --require-hardware-backend --require-calibrated-mapper --require-calibration-profile --forbid-identity-calibration --no-require-preflight-clean --max-preflight-age-seconds 900 --output artifacts/readiness_report_generated_config_relaxed.json`
- Result: Relaxed preflight gate still failed on `calibration_profile_is_identity`.
- Confidence: High
- Notes: Confirms final hard blocker is the real non-identity 24-zone calibration mapping.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config config/hardware-generated.toml --run-preflight --preflight-aggressive-msi-close --no-preflight-strict-mode --require-hardware-backend --require-calibrated-mapper --require-calibration-profile --forbid-identity-calibration --require-preflight-clean --max-preflight-age-seconds 900 --output artifacts/readiness_report_generated_config_inline_preflight.json`
- Result: Inline preflight executed before readiness evaluation; readiness still failed on `calibration_profile_is_identity` and `preflight_unresolved_count=9`.
- Confidence: High
- Notes: Confirms unattended preflight+readiness chaining now works and reports accurate blockers in one command.

- Date: 2026-03-03
- Tool/Method: `powershell -ExecutionPolicy Bypass -File .\\scripts\\longrun.ps1 -DurationHours 0.0001 -UseMock -NoPreflight -RunReadinessCheck -RunPreflightBeforeReadiness -PreflightAggressiveMsiCloseForReadiness -WatchdogInterval 1 -EventLogInterval 1`
- Result: Long-run helper executed inline preflight-before-readiness, readiness gate, runtime, and analysis in one unattended flow.
- Confidence: High
- Notes: Confirms new long-run readiness preflight integration path works end-to-end.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli live --capturer mock --backend simulated --rows 2 --columns 2 --fps 120 --iterations 20 --no-preflight --output artifacts/live_report_pacing_smoke.json`
- Result: Runtime report now includes frame pacing metrics (`effective_fps`, `overrun_iterations`, `avg_overrun_ms`).
- Confidence: High
- Notes: Confirms pacing metrics are emitted in structured live report and console summary.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli analyze-live --report artifacts/live_report_pacing_smoke.json --min-effective-fps 60 --max-overrun-percent 25 --output artifacts/live_analysis_pacing_smoke.json`
- Result: Analysis passed with pacing thresholds (`effective_fps=686.811`, `overrun_percent=0.000`).
- Confidence: High
- Notes: Confirms new pacing gates in `analyze-live` pass path.

- Date: 2026-03-03
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli analyze-live --report artifacts/live_report_pacing_smoke.json --min-effective-fps 1000 --max-overrun-percent 0 --output artifacts/live_analysis_pacing_fail_smoke.json`
- Result: Analysis failed with `effective_fps<1000.000: 686.811`.
- Confidence: High
- Notes: Confirms fail-fast behavior for under-target effective FPS thresholds.

- Date: 2026-03-04
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli calibrate-zones --backend simulated --zone-count 4 --observed-order "1,0,3,2" --delay-ms 0 --verify --verify-delay-ms 0 --verify-output artifacts/calibrate_verify_readiness_workflow_smoke.json --profile-output config/calibration/final_workflow_smoke.json --output artifacts/calibrate_report_readiness_workflow_smoke.json --no-preflight`
- Result: Simulated calibration workflow produced profile + verify artifacts suitable for readiness workflow-gate testing.
- Confidence: High
- Notes: Establishes reproducible smoke artifact for workflow evidence checks.

- Date: 2026-03-04
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config artifacts/runtime_workflow_smoke.toml --require-calibration-profile --forbid-identity-calibration --require-calibration-workflow --require-calibration-verify-executed --calibration-workflow-report artifacts/calibrate_report_readiness_workflow_smoke.json --max-calibration-workflow-age-seconds 900 --no-require-preflight-clean --output artifacts/readiness_report_workflow_smoke.json`
- Result: Readiness passed with calibration workflow gates enabled.
- Confidence: High
- Notes: Confirms workflow evidence + verify execution + freshness gating pass path.

- Date: 2026-03-04
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config artifacts/runtime_workflow_smoke.toml --require-calibration-profile --forbid-identity-calibration --require-calibration-workflow --require-calibration-verify-executed --calibration-workflow-report artifacts/calibrate_report_readiness_workflow_fail_smoke.json --max-calibration-workflow-age-seconds 900 --no-require-preflight-clean --output artifacts/readiness_report_workflow_fail_smoke.json`
- Result: Readiness failed with explicit workflow reasons (`calibration_workflow_profile_not_built`, verify not executed).
- Confidence: High
- Notes: Confirms fail-fast behavior for incomplete/invalid calibration workflow evidence.

- Date: 2026-03-04
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config config/hardware-generated.toml --run-preflight --preflight-aggressive-msi-close --preflight-strict-mode --require-hardware-backend --require-calibrated-mapper --require-calibration-profile --forbid-identity-calibration --require-preflight-clean --require-preflight-admin --require-preflight-strict-mode --require-preflight-access-denied-clear --max-preflight-age-seconds 900 --output artifacts/readiness_report_preflight_quality_strict.json`
- Result: Strict readiness failed with explicit preflight-quality reasons (`preflight_is_not_admin`, `preflight_access_denied_count=9`) plus existing calibration blocker.
- Confidence: High
- Notes: Confirms new preflight-quality gates surface permission/closure deficiencies deterministically.

- Date: 2026-03-04
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config config/default.toml --live-analysis-report artifacts/live_analysis_policy_weak_smoke.json --max-live-analysis-threshold-max-error-rate-percent 1 --max-live-analysis-threshold-max-avg-total-ms 80 --max-live-analysis-threshold-max-p95-total-ms 120 --min-live-analysis-threshold-min-effective-fps 20 --max-live-analysis-threshold-max-overrun-percent 25 --no-require-preflight-clean --output artifacts/readiness_report_live_analysis_policy_fail_smoke.json`
- Result: Readiness failed with explicit analysis-threshold policy failures (all five threshold policy checks too weak).
- Confidence: High
- Notes: Confirms readiness can now enforce strictness of the analysis thresholds used, not just analysis pass/fail.

- Date: 2026-03-04
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config config/default.toml --live-analysis-report artifacts/live_analysis_pacing_smoke.json --max-live-analysis-threshold-max-error-rate-percent 1 --max-live-analysis-threshold-max-avg-total-ms 80 --max-live-analysis-threshold-max-p95-total-ms 120 --min-live-analysis-threshold-min-effective-fps 20 --max-live-analysis-threshold-max-overrun-percent 25 --no-require-preflight-clean --output artifacts/readiness_report_live_analysis_policy_pass_smoke.json`
- Result: Readiness passed with analysis-threshold policy gates enabled.
- Confidence: High
- Notes: Confirms strict analysis policy pass-path behavior.

- Date: 2026-03-04
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config artifacts/runtime_workflow_smoke.toml --require-calibration-live-verify-success --calibration-workflow-report artifacts/calibrate_report_live_verify_fail_smoke.json --no-require-preflight-clean --output artifacts/readiness_report_live_verify_fail_smoke.json`
- Result: Readiness failed with explicit live-verify workflow reason (`calibration_workflow_live_verify_failed`).
- Confidence: High
- Notes: Confirms new live-verify success gate behavior.

- Date: 2026-03-04
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config artifacts/runtime_workflow_smoke.toml --require-calibration-live-verify-executed --require-calibration-live-verify-success --calibration-workflow-report artifacts/calibrate_report_live_verify_pass_smoke.json --no-require-preflight-clean --output artifacts/readiness_report_live_verify_pass_smoke.json`
- Result: Readiness passed with live-verify execution and success gates enabled.
- Confidence: High
- Notes: Confirms pass-path behavior for calibration live-verify evidence checks.

- Date: 2026-03-04
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config artifacts/runtime_profile_stale_smoke.toml --max-calibration-profile-age-seconds 60 --no-require-preflight-clean --output artifacts/readiness_report_profile_age_fail_smoke.json`
- Result: Readiness failed with explicit stale-profile reason (`calibration_profile_too_old`).
- Confidence: High
- Notes: Confirms calibration profile freshness gate behavior.

- Date: 2026-03-04
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config artifacts/runtime_workflow_smoke.toml --require-calibration-workflow --calibration-workflow-report artifacts/calibrate_report_order_mismatch_smoke.json --no-require-preflight-clean --output artifacts/readiness_report_order_mismatch_fail_smoke.json`
- Result: Readiness failed on `calibration_workflow_observed_order_mismatch_profile`.
- Confidence: High
- Notes: Confirms workflow observed-order must match the active calibration profile mapping.

- Date: 2026-03-04
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli readiness-check --config artifacts/runtime_provenance_smoke.toml --calibration-workflow-report artifacts/calibrate_report_provenance_smoke.json --require-calibration-profile-generated-timestamp --require-calibration-profile-provenance --require-calibration-profile-provenance-workflow-match --no-require-preflight-clean --no-require-live-analysis-pass --no-require-hid-present --output artifacts/readiness_report_provenance_pass_smoke.json`
- Result: Readiness passed with strict calibration profile metadata and provenance-workflow linkage gates enabled.
- Confidence: High
- Notes: Confirms deterministic provenance policy pass-path. Also validated BOM-safe calibration loader on Windows-authored JSON artifacts.

- Date: 2026-03-04
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli run-production --config config/default.toml --no-run-readiness --duration-seconds 0.2 --watchdog-interval 1 --event-log-interval 1 --output-dir artifacts/production_smoke --tag smoke_relaxed --min-effective-fps 5 --max-overrun-percent 100 --max-p95-total-ms 400`
- Result: New one-command production workflow executed end-to-end (live runtime + analysis) and wrote tagged artifacts under `artifacts/production_smoke/`.
- Confidence: High
- Notes: Confirms orchestration path is stable and usable; strict thresholds remain intentionally configurable for real hardware runs.

- Date: 2026-03-04
- Tool/Method: `.venv\\Scripts\\python.exe -m keylight.cli run-production --config config/hardware-generated.toml --duration-seconds 1 --output-dir artifacts/production_smoke --tag strict_fail_smoke3`
- Result: Strict production workflow failed fast in readiness with explicit blockers (`calibration_profile_is_identity`, missing calibration workflow artifact, preflight not admin, unresolved access-denied conflicts).
- Confidence: High
- Notes: Confirms production command correctly blocks unsafe startup and surfaces remaining hardware/operator prerequisites clearly.
