import json
import os
from pathlib import Path

import pytest

from keylight.calibration import CalibrationProfile
from keylight.capture.windows_mss import MonitorInfo
from keylight.cli import _parse_optional_observed_order, _run_preflight, main
from keylight.drivers.probe import ProbeReport
from keylight.drivers.simulated import SimulatedKeyboardDriver
from keylight.effect_verify import EffectVerificationReport, EffectVerificationStep
from keylight.hid_discovery import HidDiscoveryAttempt, HidDiscoveryReport
from keylight.models import RgbColor, ZoneColor
from keylight.runtime_config import load_live_command_defaults
from keylight.write_zone import WriteZoneConfig, WriteZoneReport
from keylight.zone_protocol_verify import ZoneProtocolVerifyReport, ZoneProtocolVerifyStep


def _sample_probe_report() -> ProbeReport:
    return ProbeReport(
        generated_at_utc="2026-03-03T00:00:00+00:00",
        platform_name="Windows",
        python_version="3.14.0",
        is_admin=False,
        conflict_processes=[],
        candidate_services=[],
        candidate_devices=[],
        likely_control_paths=["Direct HID vendor protocol path"],
        recommendations=["Next step"],
    )


def test_main_probe_command_routes_to_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = _sample_probe_report()
    captured: dict[str, Path] = {}

    def fake_run_probe() -> ProbeReport:
        return report

    def fake_write_probe_report(report_data: ProbeReport, output_path: Path) -> Path:
        assert report_data == report
        captured["path"] = output_path
        return output_path

    monkeypatch.setattr("keylight.cli.run_probe", fake_run_probe)
    monkeypatch.setattr("keylight.cli.write_probe_report", fake_write_probe_report)
    output_path = tmp_path / "probe.json"

    exit_code = main(["probe", "--output", str(output_path)])

    assert exit_code == 0
    assert captured["path"] == output_path


def test_main_run_command_executes_pipeline(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--iterations", "1", "--fps", "120"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Completed 1 iterations at 120 FPS" in captured.out


def test_main_sweep_command_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)

    exit_code = main(["sweep", "--zone-count", "4", "--loops", "1", "--delay-ms", "0"])

    assert exit_code == 0


def test_main_sweep_command_executes_msi_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        "keylight.cli._build_keyboard_driver",
        lambda **_: SimulatedKeyboardDriver(),
    )

    exit_code = main(
        [
            "sweep",
            "--backend",
            "msi-mystic-hid",
            "--zone-count",
            "4",
            "--loops",
            "1",
            "--delay-ms",
            "0",
            "--report-id",
            "1",
        ]
    )

    assert exit_code == 0


def test_main_write_zone_command_executes_simulated(tmp_path: Path) -> None:
    output_path = tmp_path / "write_zone_report.json"
    exit_code = main(
        [
            "write-zone",
            "--backend",
            "simulated",
            "--zone-index",
            "1",
            "--no-preflight",
            "--color",
            "255,0,0",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0


def test_main_list_hid_uses_cli_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("keylight.cli.list_hid_devices", lambda: [])

    exit_code = main(["write-zone", "--list-hid"])

    assert exit_code == 0


def test_main_init_calibration_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output_path = tmp_path / "calibration.json"
    monkeypatch.setattr(
        "keylight.cli.write_calibration_profile",
        lambda profile, path: path,
    )

    exit_code = main(["init-calibration", "--zone-count", "24", "--output", str(output_path)])

    assert exit_code == 0


def test_main_build_calibration_command_writes_profile(tmp_path: Path) -> None:
    output_path = tmp_path / "observed.json"

    exit_code = main(
        [
            "build-calibration",
            "--zone-count",
            "4",
            "--order",
            "2,0,3,1",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    content = output_path.read_text(encoding="utf-8")
    assert '"logical_to_hardware": [' in content
    assert "2" in content


def test_main_calibrate_zones_writes_observed_order_template(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    template_path = tmp_path / "observed_template.txt"
    sweep_output = tmp_path / "calibrate_sweep.json"
    workflow_output = tmp_path / "calibrate_report.json"

    exit_code = main(
        [
            "calibrate-zones",
            "--backend",
            "simulated",
            "--zone-count",
            "4",
            "--loops",
            "1",
            "--delay-ms",
            "0",
            "--template-output",
            str(template_path),
            "--sweep-output",
            str(sweep_output),
            "--output",
            str(workflow_output),
            "--no-preflight",
        ]
    )

    assert exit_code == 0
    assert template_path.exists()
    assert "observed_order=" in template_path.read_text(encoding="utf-8")
    assert sweep_output.exists()
    report_content = workflow_output.read_text(encoding="utf-8")
    assert '"profile_built": false' in report_content


def test_main_calibrate_zones_builds_profile_from_observed_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    profile_output = tmp_path / "final_profile.json"
    workflow_output = tmp_path / "calibrate_report.json"

    exit_code = main(
        [
            "calibrate-zones",
            "--backend",
            "simulated",
            "--zone-count",
            "4",
            "--loops",
            "1",
            "--delay-ms",
            "0",
            "--observed-order",
            "2,0,3,1",
            "--profile-output",
            str(profile_output),
            "--output",
            str(workflow_output),
            "--no-preflight",
        ]
    )

    assert exit_code == 0
    profile_content = profile_output.read_text(encoding="utf-8")
    assert '"logical_to_hardware": [' in profile_content
    assert "2" in profile_content
    report_content = workflow_output.read_text(encoding="utf-8")
    assert '"profile_built": true' in report_content


def test_main_calibrate_zones_runs_verification_sweep(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    profile_output = tmp_path / "final_profile.json"
    verify_output = tmp_path / "verify_sweep.json"
    workflow_output = tmp_path / "calibrate_report.json"

    exit_code = main(
        [
            "calibrate-zones",
            "--backend",
            "simulated",
            "--zone-count",
            "4",
            "--loops",
            "1",
            "--delay-ms",
            "0",
            "--observed-order",
            "2,0,3,1",
            "--verify",
            "--verify-delay-ms",
            "0",
            "--profile-output",
            str(profile_output),
            "--verify-output",
            str(verify_output),
            "--output",
            str(workflow_output),
            "--no-preflight",
        ]
    )

    assert exit_code == 0
    assert verify_output.exists()
    report_content = workflow_output.read_text(encoding="utf-8")
    assert '"verify_requested": true' in report_content
    assert '"verify_executed": true' in report_content


def test_main_calibrate_zones_verify_uses_existing_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    profile_output = tmp_path / "final_profile.json"
    profile_output.write_text(
        json.dumps(
            {
                "zone_count": 4,
                "logical_to_hardware": [2, 0, 3, 1],
            }
        ),
        encoding="utf-8",
    )
    verify_output = tmp_path / "verify_sweep.json"
    workflow_output = tmp_path / "calibrate_report.json"

    exit_code = main(
        [
            "calibrate-zones",
            "--backend",
            "simulated",
            "--zone-count",
            "4",
            "--no-sweep",
            "--verify",
            "--verify-delay-ms",
            "0",
            "--profile-output",
            str(profile_output),
            "--verify-output",
            str(verify_output),
            "--output",
            str(workflow_output),
            "--no-preflight",
        ]
    )

    assert exit_code == 0
    assert verify_output.exists()
    report_content = workflow_output.read_text(encoding="utf-8")
    assert '"profile_built": false' in report_content
    assert '"verify_executed": true' in report_content


def test_main_calibrate_zones_verify_without_profile_skips(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    workflow_output = tmp_path / "calibrate_report.json"

    exit_code = main(
        [
            "calibrate-zones",
            "--backend",
            "simulated",
            "--zone-count",
            "4",
            "--no-sweep",
            "--verify",
            "--profile-output",
            str(tmp_path / "missing_profile.json"),
            "--template-output",
            str(tmp_path / "observed_template.txt"),
            "--output",
            str(workflow_output),
            "--no-preflight",
        ]
    )

    assert exit_code == 0
    report_content = workflow_output.read_text(encoding="utf-8")
    assert '"verify_requested": true' in report_content
    assert '"verify_executed": false' in report_content


def test_main_calibrate_zones_runs_live_verification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    profile_output = tmp_path / "final_profile.json"
    live_output = tmp_path / "live_verify_report.json"
    workflow_output = tmp_path / "calibrate_report.json"

    exit_code = main(
        [
            "calibrate-zones",
            "--backend",
            "simulated",
            "--zone-count",
            "4",
            "--loops",
            "1",
            "--delay-ms",
            "0",
            "--observed-order",
            "2,0,3,1",
            "--verify-live",
            "--live-capturer",
            "mock",
            "--live-rows",
            "2",
            "--live-columns",
            "2",
            "--live-fps",
            "120",
            "--live-iterations",
            "2",
            "--profile-output",
            str(profile_output),
            "--live-output",
            str(live_output),
            "--output",
            str(workflow_output),
            "--no-preflight",
        ]
    )

    assert exit_code == 0
    assert live_output.exists()
    report_content = workflow_output.read_text(encoding="utf-8")
    assert '"live_verify_requested": true' in report_content
    assert '"live_verify_executed": true' in report_content


def test_main_calibrate_zones_live_verification_without_profile_skips(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    workflow_output = tmp_path / "calibrate_report.json"

    exit_code = main(
        [
            "calibrate-zones",
            "--backend",
            "simulated",
            "--zone-count",
            "4",
            "--no-sweep",
            "--verify-live",
            "--profile-output",
            str(tmp_path / "missing_profile.json"),
            "--template-output",
            str(tmp_path / "observed_template.txt"),
            "--output",
            str(workflow_output),
            "--no-preflight",
        ]
    )

    assert exit_code == 0
    report_content = workflow_output.read_text(encoding="utf-8")
    assert '"live_verify_requested": true' in report_content
    assert '"live_verify_executed": false' in report_content


def test_main_calibrate_zones_live_verification_uses_existing_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    profile_output = tmp_path / "final_profile.json"
    profile_output.write_text(
        json.dumps(
            {
                "zone_count": 4,
                "logical_to_hardware": [2, 0, 3, 1],
            }
        ),
        encoding="utf-8",
    )
    live_output = tmp_path / "live_verify_report.json"
    workflow_output = tmp_path / "calibrate_report.json"

    exit_code = main(
        [
            "calibrate-zones",
            "--backend",
            "simulated",
            "--zone-count",
            "4",
            "--no-sweep",
            "--verify-live",
            "--live-capturer",
            "mock",
            "--live-rows",
            "2",
            "--live-columns",
            "2",
            "--live-fps",
            "120",
            "--live-iterations",
            "2",
            "--profile-output",
            str(profile_output),
            "--live-output",
            str(live_output),
            "--output",
            str(workflow_output),
            "--no-preflight",
        ]
    )

    assert exit_code == 0
    assert live_output.exists()
    report_content = workflow_output.read_text(encoding="utf-8")
    assert '"live_verify_requested": true' in report_content
    assert '"live_verify_executed": true' in report_content


def test_main_build_zone_profile_command_writes_profile(tmp_path: Path) -> None:
    output_path = tmp_path / "zone_profile.json"

    exit_code = main(
        [
            "build-zone-profile",
            "--rows",
            "2",
            "--columns",
            "3",
            "--column-weights",
            "1,2,1",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    content = output_path.read_text(encoding="utf-8")
    assert '"version": 1' in content
    assert '"zone_index": 5' in content


def test_parse_optional_observed_order_supports_template_line(tmp_path: Path) -> None:
    template_path = tmp_path / "observed_template.txt"
    template_path.write_text(
        "\n".join(
            [
                "# comments",
                "# logical_indexes=0,1,2,3",
                "observed_order=2,0,3,1",
            ]
        ),
        encoding="utf-8",
    )

    parsed = _parse_optional_observed_order(order=None, order_file=template_path)

    assert parsed == [2, 0, 3, 1]


def test_run_preflight_passes_aggressive_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    class _Result:
        returncode = 0

    def fake_run(command: list[str], *, check: bool) -> _Result:
        assert check is False
        captured["command"] = command
        return _Result()

    monkeypatch.setattr("keylight.cli.subprocess.run", fake_run)

    exit_code = _run_preflight(aggressive_msi_close=True)

    assert exit_code == 0
    assert "-AggressiveMsiClose" in captured["command"]
    assert "-ReportPath" in captured["command"]
    assert any(
        item.endswith("artifacts\\preflight_report.json")
        or item.endswith("artifacts/preflight_report.json")
        for item in captured["command"]
    )
    assert "true" not in captured["command"]


def test_run_preflight_passes_strict_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    class _Result:
        returncode = 0

    def fake_run(command: list[str], *, check: bool) -> _Result:
        assert check is False
        captured["command"] = command
        return _Result()

    monkeypatch.setattr("keylight.cli.subprocess.run", fake_run)

    exit_code = _run_preflight(aggressive_msi_close=False, strict_mode=True)

    assert exit_code == 0
    assert "-StrictMode" in captured["command"]
    assert "-ReportPath" in captured["command"]


def test_run_preflight_passes_custom_report_path(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    class _Result:
        returncode = 0

    def fake_run(command: list[str], *, check: bool) -> _Result:
        assert check is False
        captured["command"] = command
        return _Result()

    monkeypatch.setattr("keylight.cli.subprocess.run", fake_run)

    report_path = Path("artifacts/custom_preflight.json")
    exit_code = _run_preflight(aggressive_msi_close=False, report_path=report_path)

    assert exit_code == 0
    assert "-ReportPath" in captured["command"]
    assert str(report_path) in captured["command"]


def test_main_live_command_executes_with_mock_capturer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    output_path = tmp_path / "live_report.json"

    exit_code = main(
        [
            "live",
            "--capturer",
            "mock",
            "--backend",
            "simulated",
            "--rows",
            "2",
            "--columns",
            "2",
            "--fps",
            "120",
            "--iterations",
            "2",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0


def test_main_live_command_duration_seconds_overrides_iterations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    output_path = tmp_path / "live_report.json"

    exit_code = main(
        [
            "live",
            "--capturer",
            "mock",
            "--backend",
            "simulated",
            "--rows",
            "2",
            "--columns",
            "2",
            "--fps",
            "5",
            "--iterations",
            "99",
            "--duration-seconds",
            "1",
            "--output",
            str(output_path),
            "--no-preflight",
        ]
    )

    assert exit_code == 0
    content = json.loads(output_path.read_text(encoding="utf-8"))
    assert content["iterations"] == 5
    assert content["attempted_iterations"] == 5


def test_main_live_command_restore_on_exit_updates_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)

    class _TrackingDriver:
        def __init__(self) -> None:
            self.calls = 0
            self.last_len = 0

        def apply_zone_colors(self, zones):  # type: ignore[no-untyped-def]
            self.calls += 1
            self.last_len = len(zones)

    driver = _TrackingDriver()
    monkeypatch.setattr("keylight.cli._build_keyboard_driver", lambda **_: driver)

    output_path = tmp_path / "live_report.json"
    exit_code = main(
        [
            "live",
            "--capturer",
            "mock",
            "--backend",
            "simulated",
            "--rows",
            "2",
            "--columns",
            "2",
            "--fps",
            "120",
            "--iterations",
            "1",
            "--restore-on-exit",
            "--restore-color",
            "0,0,0",
            "--output",
            str(output_path),
            "--no-preflight",
        ]
    )

    assert exit_code == 0
    assert driver.calls == 2
    assert driver.last_len == 4
    content = json.loads(output_path.read_text(encoding="utf-8"))
    assert content["restore_requested"] is True
    assert content["restore_applied"] is True
    assert content["restore_error"] is None


def test_main_live_command_restore_on_exit_failure_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)

    class _FailOnRestoreDriver:
        def __init__(self) -> None:
            self.calls = 0

        def apply_zone_colors(self, zones):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls >= 2:
                raise RuntimeError("restore failed")

    monkeypatch.setattr("keylight.cli._build_keyboard_driver", lambda **_: _FailOnRestoreDriver())
    output_path = tmp_path / "live_report.json"

    exit_code = main(
        [
            "live",
            "--capturer",
            "mock",
            "--backend",
            "simulated",
            "--rows",
            "2",
            "--columns",
            "2",
            "--fps",
            "120",
            "--iterations",
            "1",
            "--restore-on-exit",
            "--output",
            str(output_path),
            "--no-preflight",
        ]
    )

    assert exit_code == 1
    content = json.loads(output_path.read_text(encoding="utf-8"))
    assert content["restore_requested"] is True
    assert content["restore_applied"] is False
    assert content["restore_error"] == "restore failed"


def test_main_live_command_rejects_non_positive_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)

    exit_code = main(
        [
            "live",
            "--capturer",
            "mock",
            "--backend",
            "simulated",
            "--rows",
            "2",
            "--columns",
            "2",
            "--fps",
            "5",
            "--duration-seconds",
            "0",
            "--no-preflight",
        ]
    )

    assert exit_code == 2


def test_main_live_command_writes_watchdog_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    output_path = tmp_path / "live_report.json"
    watchdog_output = tmp_path / "live_watchdog.json"

    exit_code = main(
        [
            "live",
            "--capturer",
            "mock",
            "--backend",
            "simulated",
            "--rows",
            "2",
            "--columns",
            "2",
            "--fps",
            "120",
            "--iterations",
            "3",
            "--watchdog-interval",
            "1",
            "--watchdog-output",
            str(watchdog_output),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert watchdog_output.exists()


def test_main_live_command_writes_event_log(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    output_path = tmp_path / "live_report.json"
    event_log_output = tmp_path / "events.jsonl"

    exit_code = main(
        [
            "live",
            "--capturer",
            "mock",
            "--backend",
            "simulated",
            "--rows",
            "2",
            "--columns",
            "2",
            "--fps",
            "120",
            "--iterations",
            "3",
            "--event-log-interval",
            "1",
            "--event-log-output",
            str(event_log_output),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert event_log_output.exists()


def test_main_live_command_reads_defaults_from_config_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    config_path = tmp_path / "live.toml"
    watchdog_path = tmp_path / "watchdog.json"
    event_log_path = tmp_path / "events.jsonl"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 2",
                "fps = 120",
                "iterations = 2",
                "",
                "[capture]",
                'backend = "mock"',
                "width = 4",
                "height = 2",
                "",
                "[driver]",
                'backend = "simulated"',
                "",
                "[smoothing]",
                "enabled = false",
                "alpha = 0.25",
                "",
                "[brightness]",
                "max_percent = 100",
                "",
                "[runtime]",
                "max_consecutive_errors = 3",
                "error_backoff_ms = 0",
                "stop_on_error = false",
                "reconnect_on_error = true",
                "reconnect_attempts = 2",
                "watchdog_interval_iterations = 1",
                'watchdog_output = "watchdog.json"',
                "event_log_interval_iterations = 1",
                'event_log_output = "events.jsonl"',
                "restore_on_exit = true",
                'restore_color = "1,2,3"',
            ]
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "live_report.json"
    exit_code = main(
        [
            "live",
            "--config",
            str(config_path),
            "--output",
            str(output_path),
            "--no-preflight",
        ]
    )

    assert exit_code == 0
    assert watchdog_path.exists()
    assert event_log_path.exists()
    content = json.loads(output_path.read_text(encoding="utf-8"))
    assert content["restore_requested"] is True
    assert content["restore_applied"] is True


def test_main_live_command_executes_sound_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)

    class _FakeAudioReader:
        def __init__(self) -> None:
            self.resolved_device_info = type(
                "DeviceInfo",
                (),
                {"id": "speaker:Desk Speakers"},
            )()

        def read_input(self):  # type: ignore[no-untyped-def]
            return object()

        def close(self) -> None:
            return None

    class _FakeRenderer:
        zone_count = 4

        def render(self, _payload):  # type: ignore[no-untyped-def]
            return [
                ZoneColor(zone_index=0, color=RgbColor(255, 0, 0)),
                ZoneColor(zone_index=1, color=RgbColor(0, 255, 0)),
                ZoneColor(zone_index=2, color=RgbColor(0, 0, 255)),
                ZoneColor(zone_index=3, color=RgbColor(255, 255, 0)),
            ]

    monkeypatch.setattr("keylight.cli._build_audio_reader", lambda **_: _FakeAudioReader())
    monkeypatch.setattr("keylight.cli._build_sound_renderer", lambda **_: _FakeRenderer())
    output_path = tmp_path / "live_sound.json"

    exit_code = main(
        [
            "live",
            "--mode",
            "sound",
            "--backend",
            "simulated",
            "--rows",
            "2",
            "--columns",
            "2",
            "--fps",
            "120",
            "--iterations",
            "2",
            "--output",
            str(output_path),
            "--no-preflight",
        ]
    )

    assert exit_code == 0
    content = json.loads(output_path.read_text(encoding="utf-8"))
    assert content["mode"] == "sound"
    assert content["audio_input_kind"] == "output-loopback"
    assert content["sound_effect"] == "spectrum"
    assert content["audio_device_id"] == "speaker:Desk Speakers"


def test_main_live_command_uses_calibrated_mapper_from_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    profile_path = tmp_path / "zones.json"
    profile_path.write_text(
        json.dumps(
            {
                "version": 1,
                "zones": [
                    {"zone_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 1.0},
                    {"zone_index": 1, "x0": 0.5, "y0": 0.0, "x1": 1.0, "y1": 1.0},
                    {"zone_index": 2, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 0.5},
                    {"zone_index": 3, "x0": 0.0, "y0": 0.5, "x1": 1.0, "y1": 1.0},
                ],
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "live.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 2",
                "fps = 120",
                "iterations = 2",
                "",
                "[capture]",
                'backend = "mock"',
                "width = 4",
                "height = 2",
                "",
                "[mapping]",
                'backend = "calibrated"',
                'zone_profile = "zones.json"',
                "",
                "[driver]",
                'backend = "simulated"',
                "",
                "[smoothing]",
                "enabled = false",
                "alpha = 0.25",
                "",
                "[brightness]",
                "max_percent = 100",
                "",
                "[runtime]",
                "max_consecutive_errors = 3",
                "error_backoff_ms = 0",
                "stop_on_error = false",
            ]
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "live_report.json"
    exit_code = main(
        [
            "live",
            "--config",
            str(config_path),
            "--output",
            str(output_path),
            "--no-preflight",
        ]
    )

    assert exit_code == 0


def test_main_analyze_live_command_writes_report(tmp_path: Path) -> None:
    live_report = tmp_path / "live_report.json"
    live_report.write_text(
        json.dumps(
            {
                "started_at_utc": "2026-03-03T00:00:00+00:00",
                "finished_at_utc": "2026-03-03T00:00:01+00:00",
                "iterations": 3,
                "attempted_iterations": 3,
                "completed_iterations": 3,
                "error_count": 0,
                "max_consecutive_errors": 0,
                "aborted": False,
                "last_error": None,
                "recovery_attempts": 0,
                "recovery_successes": 0,
                "avg_capture_ms": 1.0,
                "avg_map_ms": 1.0,
                "avg_process_ms": 1.0,
                "avg_send_ms": 1.0,
                "avg_total_ms": 2.0,
                "watchdog_emits": 0,
                "event_log_emits": 0,
            }
        ),
        encoding="utf-8",
    )
    event_log = tmp_path / "live_events.jsonl"
    event_log.write_text(
        "\n".join(
            [
                json.dumps({"status": "ok", "total_ms": 1.0}),
                json.dumps({"status": "ok", "total_ms": 2.0}),
                json.dumps({"status": "ok", "total_ms": 3.0}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "analysis.json"

    exit_code = main(
        [
            "analyze-live",
            "--report",
            str(live_report),
            "--event-log",
            str(event_log),
            "--output",
            str(output_path),
            "--max-avg-total-ms",
            "80",
            "--max-p95-total-ms",
            "10",
            "--max-error-rate-percent",
            "1",
            "--min-effective-fps",
            "20",
            "--max-overrun-percent",
            "50",
        ]
    )

    assert exit_code == 0
    content = output_path.read_text(encoding="utf-8")
    assert '"passed": true' in content


def test_main_analyze_live_command_returns_nonzero_for_failed_checks(tmp_path: Path) -> None:
    live_report = tmp_path / "live_report.json"
    live_report.write_text(
        json.dumps(
            {
                "started_at_utc": "2026-03-03T00:00:00+00:00",
                "finished_at_utc": "2026-03-03T00:00:01+00:00",
                "iterations": 3,
                "attempted_iterations": 3,
                "completed_iterations": 1,
                "error_count": 2,
                "max_consecutive_errors": 2,
                "aborted": True,
                "last_error": "capture failed",
                "recovery_attempts": 0,
                "recovery_successes": 0,
                "avg_capture_ms": 1.0,
                "avg_map_ms": 1.0,
                "avg_process_ms": 1.0,
                "avg_send_ms": 1.0,
                "avg_total_ms": 200.0,
                "watchdog_emits": 0,
                "event_log_emits": 0,
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "analysis.json"

    exit_code = main(
        [
            "analyze-live",
            "--report",
            str(live_report),
            "--output",
            str(output_path),
            "--max-avg-total-ms",
            "80",
            "--max-error-rate-percent",
            "1",
        ]
    )

    assert exit_code == 1
    content = output_path.read_text(encoding="utf-8")
    assert '"passed": false' in content


def test_main_readiness_check_command_writes_report(tmp_path: Path) -> None:
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 2",
                "",
                "[capture]",
                'backend = "mock"',
                "width = 4",
                "height = 2",
                "",
                "[driver]",
                'backend = "simulated"',
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "readiness.json"

    exit_code = main(
        [
            "readiness-check",
            "--config",
            str(config_path),
            "--no-require-preflight-clean",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    content = output_path.read_text(encoding="utf-8")
    assert '"passed": true' in content


def test_main_readiness_check_command_runs_preflight_when_requested(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 2",
                "",
                "[capture]",
                'backend = "mock"',
                "width = 4",
                "height = 2",
                "",
                "[driver]",
                'backend = "simulated"',
            ]
        ),
        encoding="utf-8",
    )
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(json.dumps({"unresolved_count": 0}), encoding="utf-8")
    output_path = tmp_path / "readiness.json"

    captured: dict[str, object] = {}

    def fake_run_preflight(
        aggressive_msi_close: bool,
        strict_mode: bool = False,
        report_path: Path | None = None,
    ) -> int:
        captured["aggressive_msi_close"] = aggressive_msi_close
        captured["strict_mode"] = strict_mode
        captured["report_path"] = report_path
        return 0

    monkeypatch.setattr("keylight.cli._run_preflight", fake_run_preflight)

    exit_code = main(
        [
            "readiness-check",
            "--config",
            str(config_path),
            "--run-preflight",
            "--preflight-aggressive-msi-close",
            "--preflight-strict-mode",
            "--preflight-report",
            str(preflight_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert captured["aggressive_msi_close"] is True
    assert captured["strict_mode"] is True
    assert captured["report_path"] == preflight_path
    content = output_path.read_text(encoding="utf-8")
    assert '"passed": true' in content


def test_main_readiness_check_command_returns_nonzero_when_failed(tmp_path: Path) -> None:
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 2",
                "",
                "[capture]",
                'backend = "mock"',
                "width = 4",
                "height = 2",
                "",
                "[driver]",
                'backend = "simulated"',
            ]
        ),
        encoding="utf-8",
    )
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(json.dumps({"unresolved_count": 1}), encoding="utf-8")
    output_path = tmp_path / "readiness.json"

    exit_code = main(
        [
            "readiness-check",
            "--config",
            str(config_path),
            "--preflight-report",
            str(preflight_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 1
    content = output_path.read_text(encoding="utf-8")
    assert '"passed": false' in content


def test_main_readiness_check_command_requires_hardware_backend(tmp_path: Path) -> None:
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 2",
                "",
                "[capture]",
                'backend = "mock"',
                "width = 4",
                "height = 2",
                "",
                "[driver]",
                'backend = "simulated"',
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "readiness.json"

    exit_code = main(
        [
            "readiness-check",
            "--config",
            str(config_path),
            "--require-hardware-backend",
            "--no-require-preflight-clean",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 1
    content = output_path.read_text(encoding="utf-8")
    assert '"passed": false' in content


def test_main_readiness_check_command_requires_calibrated_mapper(tmp_path: Path) -> None:
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 2",
                "",
                "[capture]",
                'backend = "mock"',
                "width = 4",
                "height = 2",
                "",
                "[mapping]",
                'backend = "grid"',
                "",
                "[driver]",
                'backend = "simulated"',
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "readiness.json"

    exit_code = main(
        [
            "readiness-check",
            "--config",
            str(config_path),
            "--require-calibrated-mapper",
            "--no-require-preflight-clean",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 1
    content = output_path.read_text(encoding="utf-8")
    assert '"passed": false' in content


def test_main_readiness_check_command_requires_preflight_admin(tmp_path: Path) -> None:
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 2",
                "",
                "[capture]",
                'backend = "mock"',
                "width = 4",
                "height = 2",
                "",
                "[driver]",
                'backend = "simulated"',
            ]
        ),
        encoding="utf-8",
    )
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(
        json.dumps({"unresolved_count": 0, "is_admin": False}),
        encoding="utf-8",
    )
    output_path = tmp_path / "readiness.json"

    exit_code = main(
        [
            "readiness-check",
            "--config",
            str(config_path),
            "--preflight-report",
            str(preflight_path),
            "--require-preflight-admin",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 1
    content = output_path.read_text(encoding="utf-8")
    assert '"passed": false' in content


def test_main_readiness_check_command_fails_live_analysis_threshold_policy(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 2",
                "",
                "[capture]",
                'backend = "mock"',
                "width = 4",
                "height = 2",
                "",
                "[driver]",
                'backend = "simulated"',
            ]
        ),
        encoding="utf-8",
    )
    analysis_path = tmp_path / "analysis.json"
    analysis_path.write_text(
        json.dumps(
            {
                "passed": True,
                "generated_at_utc": "2026-03-04T00:00:00Z",
                "thresholds": {
                    "max_error_rate_percent": 10.0,
                    "max_avg_total_ms": 200.0,
                    "max_p95_total_ms": 250.0,
                    "min_effective_fps": 5.0,
                    "max_overrun_percent": 90.0,
                },
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "readiness.json"

    exit_code = main(
        [
            "readiness-check",
            "--config",
            str(config_path),
            "--live-analysis-report",
            str(analysis_path),
            "--max-live-analysis-threshold-max-error-rate-percent",
            "1",
            "--max-live-analysis-threshold-max-avg-total-ms",
            "80",
            "--max-live-analysis-threshold-max-p95-total-ms",
            "120",
            "--min-live-analysis-threshold-min-effective-fps",
            "20",
            "--max-live-analysis-threshold-max-overrun-percent",
            "25",
            "--no-require-preflight-clean",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 1
    content = output_path.read_text(encoding="utf-8")
    assert '"passed": false' in content


def test_main_readiness_check_command_fails_on_stale_preflight_report(tmp_path: Path) -> None:
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 2",
                "",
                "[capture]",
                'backend = "mock"',
                "width = 4",
                "height = 2",
                "",
                "[driver]",
                'backend = "simulated"',
            ]
        ),
        encoding="utf-8",
    )
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(
        json.dumps(
            {
                "unresolved_count": 0,
                "generated_at_utc": "2000-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "readiness.json"

    exit_code = main(
        [
            "readiness-check",
            "--config",
            str(config_path),
            "--preflight-report",
            str(preflight_path),
            "--max-preflight-age-seconds",
            "60",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 1
    content = output_path.read_text(encoding="utf-8")
    assert '"passed": false' in content


def test_main_readiness_check_command_requires_calibration_workflow(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 2",
                "",
                "[capture]",
                'backend = "mock"',
                "width = 4",
                "height = 2",
                "",
                "[driver]",
                'backend = "simulated"',
            ]
        ),
        encoding="utf-8",
    )
    workflow_path = tmp_path / "calibrate_report_final.json"
    workflow_path.write_text(
        json.dumps(
            {
                "finished_at_utc": "2026-03-04T00:00:00Z",
                "zone_count": 4,
                "profile_built": False,
                "observed_order": [0, 1, 2, 3],
                "profile_output_path": "config/calibration/final.json",
                "verify_executed": False,
                "verify_steps_executed": 0,
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "readiness.json"

    exit_code = main(
        [
            "readiness-check",
            "--config",
            str(config_path),
            "--require-calibration-workflow",
            "--calibration-workflow-report",
            str(workflow_path),
            "--no-require-preflight-clean",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 1
    content = output_path.read_text(encoding="utf-8")
    assert '"passed": false' in content


def test_main_readiness_check_command_fails_stale_calibration_profile(
    tmp_path: Path,
) -> None:
    profile_path = tmp_path / "calibration.json"
    profile_path.write_text(
        json.dumps({"zone_count": 4, "logical_to_hardware": [1, 0, 3, 2]}),
        encoding="utf-8",
    )
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 2",
                "",
                "[capture]",
                'backend = "mock"',
                "width = 4",
                "height = 2",
                "",
                "[driver]",
                'backend = "simulated"',
                'calibration_profile = "calibration.json"',
            ]
        ),
        encoding="utf-8",
    )
    old_timestamp = 946684800  # 2000-01-01T00:00:00Z
    os.utime(profile_path, (old_timestamp, old_timestamp))
    output_path = tmp_path / "readiness.json"

    exit_code = main(
        [
            "readiness-check",
            "--config",
            str(config_path),
            "--max-calibration-profile-age-seconds",
            "60",
            "--no-require-preflight-clean",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 1
    content = output_path.read_text(encoding="utf-8")
    assert '"passed": false' in content


def test_main_readiness_check_command_requires_calibration_profile_provenance(
    tmp_path: Path,
) -> None:
    profile_path = tmp_path / "calibration.json"
    profile_path.write_text(
        json.dumps(
            {
                "zone_count": 4,
                "logical_to_hardware": [1, 0, 3, 2],
                "generated_at_utc": "2026-03-04T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 2",
                "",
                "[capture]",
                'backend = "mock"',
                "width = 4",
                "height = 2",
                "",
                "[driver]",
                'backend = "simulated"',
                'calibration_profile = "calibration.json"',
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "readiness.json"

    exit_code = main(
        [
            "readiness-check",
            "--config",
            str(config_path),
            "--require-calibration-profile-provenance",
            "--no-require-preflight-clean",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 1
    content = output_path.read_text(encoding="utf-8")
    assert '"passed": false' in content


def test_main_readiness_check_command_requires_calibration_profile_provenance_workflow_match(
    tmp_path: Path,
) -> None:
    workflow_path = tmp_path / "calibrate_report_final.json"
    workflow_path.write_text(
        json.dumps({"finished_at_utc": "2026-03-04T00:00:00Z"}),
        encoding="utf-8",
    )
    profile_path = tmp_path / "calibration.json"
    profile_path.write_text(
        json.dumps(
            {
                "zone_count": 4,
                "logical_to_hardware": [1, 0, 3, 2],
                "generated_at_utc": "2026-03-04T00:00:00Z",
                "provenance": {
                    "method": "calibrate-zones",
                    "observed_order": [1, 0, 3, 2],
                    "workflow_report_path": "wrong_report.json",
                },
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 2",
                "",
                "[capture]",
                'backend = "mock"',
                "width = 4",
                "height = 2",
                "",
                "[driver]",
                'backend = "simulated"',
                'calibration_profile = "calibration.json"',
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "readiness.json"

    exit_code = main(
        [
            "readiness-check",
            "--config",
            str(config_path),
            "--calibration-workflow-report",
            str(workflow_path),
            "--require-calibration-profile-provenance-workflow-match",
            "--no-require-preflight-clean",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 1
    content = output_path.read_text(encoding="utf-8")
    assert '"passed": false' in content


def test_main_readiness_check_command_requires_calibration_live_verify_success(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 2",
                "",
                "[capture]",
                'backend = "mock"',
                "width = 4",
                "height = 2",
                "",
                "[driver]",
                'backend = "simulated"',
            ]
        ),
        encoding="utf-8",
    )
    workflow_path = tmp_path / "calibrate_report_final.json"
    workflow_path.write_text(
        json.dumps(
            {
                "finished_at_utc": "2026-03-04T00:00:00Z",
                "zone_count": 4,
                "profile_built": True,
                "observed_order": [0, 1, 2, 3],
                "profile_output_path": "config/calibration/final.json",
                "verify_executed": True,
                "verify_steps_executed": 4,
                "live_verify_executed": True,
                "live_verify_error": "runtime failed",
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "readiness.json"

    exit_code = main(
        [
            "readiness-check",
            "--config",
            str(config_path),
            "--require-calibration-live-verify-success",
            "--calibration-workflow-report",
            str(workflow_path),
            "--no-require-preflight-clean",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 1
    content = output_path.read_text(encoding="utf-8")
    assert '"passed": false' in content


def test_main_run_production_command_runs_all_stages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "hardware.toml"
    config_path.write_text("# demo config\n", encoding="utf-8")
    output_dir = tmp_path / "out"

    captured: dict[str, list[str]] = {}

    def fake_readiness(argv: list[str]) -> int:
        captured["readiness"] = argv
        return 0

    def fake_live(argv: list[str]) -> int:
        captured["live"] = argv
        return 0

    def fake_analyze(argv: list[str]) -> int:
        captured["analyze"] = argv
        return 0

    monkeypatch.setattr("keylight.cli._readiness_check_command", fake_readiness)
    monkeypatch.setattr("keylight.cli._live_command", fake_live)
    monkeypatch.setattr("keylight.cli._analyze_live_command", fake_analyze)

    exit_code = main(
        [
            "run-production",
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--tag",
            "smoke",
        ]
    )

    assert exit_code == 0
    assert "--require-hardware-backend" in captured["readiness"]
    assert "--require-calibration-profile-provenance" in captured["readiness"]
    assert str(output_dir / "readiness_smoke.json") in captured["readiness"]
    assert "--no-preflight" in captured["live"]
    assert str(output_dir / "live_smoke.json") in captured["live"]
    assert "--event-log" in captured["analyze"]
    assert str(output_dir / "live_analysis_smoke.json") in captured["analyze"]


def test_main_run_production_command_stops_when_readiness_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "hardware.toml"
    config_path.write_text("# demo config\n", encoding="utf-8")

    calls: dict[str, int] = {"live": 0, "analyze": 0}

    monkeypatch.setattr("keylight.cli._readiness_check_command", lambda _: 1)

    def fake_live(_: list[str]) -> int:
        calls["live"] += 1
        return 0

    def fake_analyze(_: list[str]) -> int:
        calls["analyze"] += 1
        return 0

    monkeypatch.setattr("keylight.cli._live_command", fake_live)
    monkeypatch.setattr("keylight.cli._analyze_live_command", fake_analyze)

    exit_code = main(
        [
            "run-production",
            "--config",
            str(config_path),
            "--tag",
            "smoke",
        ]
    )

    assert exit_code == 1
    assert calls["live"] == 0
    assert calls["analyze"] == 0


def test_main_run_production_command_fails_when_config_missing(tmp_path: Path) -> None:
    missing_config = tmp_path / "missing.toml"

    exit_code = main(
        [
            "run-production",
            "--config",
            str(missing_config),
        ]
    )

    assert exit_code == 2


def test_main_build_runtime_config_command_writes_hardware_profile(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "base.toml"
    base_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 12",
                "fps = 30",
                "iterations = 300",
                "",
                "[capture]",
                'backend = "windows-mss"',
                "monitor_index = 1",
                "width = 120",
                "height = 20",
                "",
                "[mapping]",
                'backend = "calibrated"',
                'zone_profile = "mapping.json"',
                "",
                "[driver]",
                'backend = "simulated"',
                'calibration_profile = "calibration.json"',
                "",
                "[runtime]",
                "strict_preflight = false",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "mapping.json").write_text(
        json.dumps(
            {
                "version": 1,
                "zones": [
                    {"zone_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 1.0},
                    {"zone_index": 1, "x0": 0.5, "y0": 0.0, "x1": 1.0, "y1": 1.0},
                    {"zone_index": 2, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 0.5},
                    {"zone_index": 3, "x0": 0.0, "y0": 0.5, "x1": 1.0, "y1": 1.0},
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "calibration.json").write_text(
        json.dumps(
            {
                "zone_count": 4,
                "logical_to_hardware": [0, 1, 2, 3],
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "hardware.toml"

    exit_code = main(
        [
            "build-runtime-config",
            "--base",
            str(base_path),
            "--output",
            str(output_path),
            "--set-hardware-mode",
            "--set-longrun-mode",
            "--backend",
            "msi-mystic-hid",
            "--hid-path",
            "test-path",
        ]
    )

    assert exit_code == 0
    loaded = load_live_command_defaults(output_path, must_exist=True)
    assert loaded.backend == "msi-mystic-hid"
    assert loaded.hid_path == "test-path"
    assert loaded.mapper == "calibrated"
    assert loaded.write_method == "feature"
    assert loaded.pad_length == 64
    assert loaded.strict_preflight is True
    assert loaded.watchdog_interval_iterations == 300
    assert loaded.event_log_interval_iterations == 30
    assert loaded.restore_on_exit is True


def test_main_build_runtime_config_command_writes_sound_profile(tmp_path: Path) -> None:
    base_path = tmp_path / "base.toml"
    base_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 12",
                "fps = 30",
                "iterations = 300",
                "",
                "[driver]",
                'backend = "simulated"',
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "sound.toml"

    exit_code = main(
        [
            "build-runtime-config",
            "--base",
            str(base_path),
            "--output",
            str(output_path),
            "--mode",
            "sound",
            "--audio-input-kind",
            "microphone",
            "--audio-device-id",
            "microphone:Room Mic",
            "--sound-effect",
            "waveform",
            "--audio-zone-layout",
            "center-out",
            "--audio-palette",
            "0,0,255;255,0,0",
        ]
    )

    assert exit_code == 0
    loaded = load_live_command_defaults(output_path, must_exist=True)
    assert loaded.mode_source == "sound"
    assert loaded.audio_input_kind == "microphone"
    assert loaded.audio_device_id == "microphone:Room Mic"
    assert loaded.sound_effect == "waveform"
    assert loaded.audio_zone_layout == "center-out"
    assert loaded.audio_palette == ("0,0,255", "255,0,0")


def test_main_capture_observed_order_command_writes_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    responses = iter(["2", "0", "3", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    profile_output = tmp_path / "final.json"
    observed_output = tmp_path / "observed.txt"

    exit_code = main(
        [
            "capture-observed-order",
            "--backend",
            "simulated",
            "--zone-count",
            "4",
            "--active-color",
            "255,0,0",
            "--inactive-color",
            "0,0,0",
            "--profile-output",
            str(profile_output),
            "--observed-output",
            str(observed_output),
            "--no-preflight",
        ]
    )

    assert exit_code == 0
    profile_content = profile_output.read_text(encoding="utf-8")
    assert '"zone_count": 4' in profile_content
    assert "2" in profile_content
    observed_content = observed_output.read_text(encoding="utf-8")
    assert "observed_order=2,0,3,1" in observed_content


def test_main_list_monitors_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "keylight.cli.list_monitors",
        lambda: [
            MonitorInfo(index=0, width=1920, height=1080, left=0, top=0),
            MonitorInfo(index=1, width=1920, height=1080, left=0, top=0),
        ],
    )

    exit_code = main(["list-monitors"])

    assert exit_code == 0


def test_main_list_audio_devices_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "keylight.cli.list_audio_devices",
        lambda: [
            type(
                "AudioDeviceInfo",
                (),
                {
                    "id": "speaker:Desk Speakers",
                    "name": "Desk Speakers",
                    "kind": "output-loopback",
                    "is_default": True,
                },
            )()
        ],
    )

    exit_code = main(["list-audio-devices"])

    assert exit_code == 0


def test_main_write_zone_uses_calibration_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_zone_indexes: list[int] = []

    def fake_load_calibration_profile(_: Path) -> CalibrationProfile:
        return CalibrationProfile(zone_count=4, logical_to_hardware=[2, 0, 3, 1])

    def fake_execute_write_zone(config: WriteZoneConfig) -> WriteZoneReport:
        zone_index = config.zone_index
        captured_zone_indexes.append(zone_index)

        return WriteZoneReport(
            timestamp_utc="2026-03-03T00:00:00+00:00",
            backend="simulated",
            zone_index=zone_index,
            zone_count=4,
            color=RgbColor(255, 0, 0),
            success=True,
            bytes_written=0,
            report_bytes=None,
            write_method="none",
            pad_to=None,
            hid_path=None,
            vendor_id=None,
            product_id=None,
            error=None,
        )

    monkeypatch.setattr("keylight.cli.load_calibration_profile", fake_load_calibration_profile)
    monkeypatch.setattr("keylight.cli.execute_write_zone", fake_execute_write_zone)

    exit_code = main(
        [
            "write-zone",
            "--backend",
            "simulated",
            "--zone-index",
            "1",
            "--zone-count",
            "4",
            "--color",
            "255,0,0",
            "--calibration-profile",
            "config/calibration/default.json",
            "--no-preflight",
        ]
    )

    assert exit_code == 0
    assert captured_zone_indexes == [0]


def test_main_discover_hid_routes_and_writes_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = HidDiscoveryReport(
        started_at_utc="2026-03-03T00:00:00+00:00",
        finished_at_utc="2026-03-03T00:00:01+00:00",
        hid_path="test-path",
        vendor_id=None,
        product_id=None,
        zone_index=0,
        color=RgbColor(255, 0, 0),
        total_attempts=1,
        success_count=1,
        attempts=[
            HidDiscoveryAttempt(
                index=1,
                timestamp_utc="2026-03-03T00:00:00+00:00",
                template_name="base",
                write_method="output",
                report_id=0,
                pad_length=8,
                success=True,
                bytes_written=8,
                report_bytes=[0, 0, 255, 0, 0, 0, 0, 0],
                error=None,
            )
        ],
    )
    captured: dict[str, Path] = {}

    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr("keylight.cli.run_hid_discovery", lambda _: report)

    def fake_write_hid_discovery_report(
        report_data: HidDiscoveryReport,
        output_path: Path,
    ) -> Path:
        assert report_data == report
        captured["path"] = output_path
        return output_path

    monkeypatch.setattr("keylight.cli.write_hid_discovery_report", fake_write_hid_discovery_report)
    output_path = tmp_path / "hid_discovery.json"

    exit_code = main(
        [
            "discover-hid",
            "--hid-path",
            "test-path",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert captured["path"] == output_path


def test_main_discover_effects_routes_and_writes_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = EffectVerificationReport(
        started_at_utc="2026-03-03T00:00:00+00:00",
        finished_at_utc="2026-03-03T00:00:05+00:00",
        hid_path="test-path",
        vendor_id=None,
        product_id=None,
        total_steps=1,
        success_count=1,
        steps=[
            EffectVerificationStep(
                step_index=1,
                timestamp_utc="2026-03-03T00:00:00+00:00",
                candidate_name="base-out-rid1",
                write_method="output",
                report_id=1,
                pad_length=64,
                zone_index=0,
                color=RgbColor(255, 0, 0),
                success=True,
                bytes_written=64,
                report_bytes=[1, 0, 255, 0, 0, 0, 0, 0],
                error=None,
            )
        ],
    )
    captured: dict[str, Path] = {}

    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr("keylight.cli.run_effect_verification", lambda *_, **__: report)

    def fake_write_effect_verification_report(
        report_data: EffectVerificationReport,
        output_path: Path,
    ) -> Path:
        assert report_data == report
        captured["path"] = output_path
        return output_path

    monkeypatch.setattr(
        "keylight.cli.write_effect_verification_report",
        fake_write_effect_verification_report,
    )
    output_path = tmp_path / "effect_verify.json"

    exit_code = main(
        [
            "discover-effects",
            "--hid-path",
            "test-path",
            "--output",
            str(output_path),
            "--step-delay-ms",
            "0",
            "--max-steps",
            "1",
        ]
    )

    assert exit_code == 0
    assert captured["path"] == output_path


def test_main_discover_zone_protocol_routes_and_writes_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = ZoneProtocolVerifyReport(
        started_at_utc="2026-03-06T00:00:00+00:00",
        finished_at_utc="2026-03-06T00:00:01+00:00",
        hid_path="test-path",
        vendor_id=None,
        product_id=None,
        pad_length=64,
        total_steps=1,
        success_count=1,
        offsets=[3],
        steps=[
            ZoneProtocolVerifyStep(
                step_index=1,
                timestamp_utc="2026-03-06T00:00:00+00:00",
                offset=3,
                zone_index=0,
                color=RgbColor(255, 0, 0),
                original_value=88,
                injected_value=0,
                success=True,
                prep_bytes_written=64,
                color_bytes_written=64,
                color_packet=[0] * 64,
                error=None,
            )
        ],
    )
    captured: dict[str, Path] = {}

    monkeypatch.setattr("keylight.cli._run_preflight", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr("keylight.cli.run_zone_protocol_verify", lambda *_, **__: report)

    def fake_write_zone_protocol_verify_report(
        report_data: ZoneProtocolVerifyReport,
        output_path: Path,
    ) -> Path:
        assert report_data == report
        captured["path"] = output_path
        return output_path

    monkeypatch.setattr(
        "keylight.cli.write_zone_protocol_verify_report",
        fake_write_zone_protocol_verify_report,
    )
    output_path = tmp_path / "zone_protocol_verify.json"

    exit_code = main(
        [
            "discover-zone-protocol",
            "--hid-path",
            "test-path",
            "--output",
            str(output_path),
            "--step-delay-ms",
            "0",
            "--max-steps",
            "1",
        ]
    )

    assert exit_code == 0
    assert captured["path"] == output_path

