from pathlib import Path

import pytest

from keylight.runtime_config import LiveCommandDefaults, load_live_command_defaults


def test_load_live_defaults_returns_builtins_for_missing_file(tmp_path: Path) -> None:
    defaults = load_live_command_defaults(tmp_path / "missing.toml")

    assert defaults == LiveCommandDefaults()


def test_load_live_command_defaults_raises_for_missing_explicit_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="config file not found"):
        load_live_command_defaults(tmp_path / "missing.toml", must_exist=True)


def test_load_live_defaults_requires_profile_for_calibrated_mapper(tmp_path: Path) -> None:
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[mapping]",
                'backend = "calibrated"',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="mapping.zone_profile"):
        load_live_command_defaults(config_path, must_exist=True)


def test_load_live_command_defaults_reads_toml_values(tmp_path: Path) -> None:
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 3",
                "columns = 8",
                "fps = 45",
                "iterations = 900",
                "",
                "[capture]",
                'backend = "mock"',
                "monitor_index = 2",
                "width = 96",
                "height = 12",
                "",
                "[mapping]",
                'backend = "calibrated"',
                'zone_profile = "profiles/zone_rects.json"',
                "",
                "[driver]",
                'backend = "msi-mystic-hid"',
                'hid_path = "\\\\\\\\?\\\\HID#VID_1462&PID_1603#demo"',
                'vendor_id = "0x1462"',
                "product_id = 5635",
                "report_id = 3",
                'write_method = "feature"',
                "pad_length = 65",
                'packet_template = "{report_id} 0xAA {zone} {r} {g} {b}"',
                'calibration_profile = "profiles/final.json"',
                "",
                "[smoothing]",
                "enabled = true",
                "alpha = 0.4",
                "",
                "[brightness]",
                "max_percent = 80",
                "",
                "[runtime]",
                "max_consecutive_errors = 7",
                "error_backoff_ms = 500",
                "stop_on_error = true",
                "strict_preflight = true",
                "reconnect_on_error = false",
                "reconnect_attempts = 4",
                "watchdog_interval_iterations = 15",
                'watchdog_output = "artifacts/live_watchdog.json"',
                "event_log_interval_iterations = 5",
                'event_log_output = "artifacts/live_events.jsonl"',
                "restore_on_exit = true",
                'restore_color = "1,2,3"',
            ]
        ),
        encoding="utf-8",
    )

    defaults = load_live_command_defaults(config_path, must_exist=True)

    assert defaults.rows == 3
    assert defaults.columns == 8
    assert defaults.fps == 45
    assert defaults.iterations == 900
    assert defaults.capturer == "mock"
    assert defaults.monitor_index == 2
    assert defaults.capture_width == 96
    assert defaults.capture_height == 12
    assert defaults.mapper == "calibrated"
    assert defaults.zone_profile == (config_path.parent / "profiles/zone_rects.json").resolve()
    assert defaults.backend == "msi-mystic-hid"
    assert defaults.hid_path is not None
    assert "VID_1462" in defaults.hid_path
    assert defaults.vendor_id == "0x1462"
    assert defaults.product_id == "5635"
    assert defaults.report_id == 3
    assert defaults.write_method == "feature"
    assert defaults.pad_length == 65
    assert defaults.packet_template == "{report_id} 0xAA {zone} {r} {g} {b}"
    assert defaults.calibration_profile == (config_path.parent / "profiles/final.json").resolve()
    assert defaults.smoothing_enabled is True
    assert defaults.smoothing_alpha == 0.4
    assert defaults.brightness_max_percent == 80
    assert defaults.max_consecutive_errors == 7
    assert defaults.error_backoff_ms == 500
    assert defaults.stop_on_error is True
    assert defaults.strict_preflight is True
    assert defaults.reconnect_on_error is False
    assert defaults.reconnect_attempts == 4
    assert defaults.watchdog_interval_iterations == 15
    assert defaults.watchdog_output == (
        config_path.parent / "artifacts/live_watchdog.json"
    ).resolve()
    assert defaults.event_log_interval_iterations == 5
    assert defaults.event_log_output == (
        config_path.parent / "artifacts/live_events.jsonl"
    ).resolve()
    assert defaults.restore_on_exit is True
    assert defaults.restore_color == "1,2,3"


def test_load_live_defaults_rejects_invalid_restore_color(tmp_path: Path) -> None:
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[runtime]",
                "restore_on_exit = true",
                'restore_color = "999,0,0"',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="runtime.restore_color"):
        load_live_command_defaults(config_path, must_exist=True)
