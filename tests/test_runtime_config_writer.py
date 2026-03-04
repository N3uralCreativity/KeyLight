from dataclasses import replace
from pathlib import Path

from keylight.runtime_config import LiveCommandDefaults, load_live_command_defaults
from keylight.runtime_config_writer import write_live_defaults_toml


def test_write_live_defaults_toml_round_trip(tmp_path: Path) -> None:
    defaults = replace(
        LiveCommandDefaults(),
        backend="msi-mystic-hid",
        mapper="calibrated",
        capturer="windows-mss",
        zone_profile=(tmp_path / "mapping" / "zones.json").resolve(),
        calibration_profile=(tmp_path / "calibration" / "final.json").resolve(),
        hid_path="\\\\?\\HID#VID_1462&PID_1603#demo",
        vendor_id="0x1462",
        product_id="0x1603",
        strict_preflight=True,
        watchdog_interval_iterations=30,
        watchdog_output=(tmp_path / "artifacts" / "watchdog.json").resolve(),
        event_log_interval_iterations=15,
        event_log_output=(tmp_path / "artifacts" / "events.jsonl").resolve(),
        restore_on_exit=True,
        restore_color="1,2,3",
    )
    output = tmp_path / "runtime.toml"
    output_path = write_live_defaults_toml(defaults, output)

    loaded = load_live_command_defaults(output_path, must_exist=True)

    assert loaded.backend == "msi-mystic-hid"
    assert loaded.mapper == "calibrated"
    assert loaded.zone_profile == (tmp_path / "mapping" / "zones.json").resolve()
    assert loaded.calibration_profile == (tmp_path / "calibration" / "final.json").resolve()
    assert loaded.hid_path == "\\\\?\\HID#VID_1462&PID_1603#demo"
    assert loaded.strict_preflight is True
    assert loaded.watchdog_interval_iterations == 30
    assert loaded.event_log_interval_iterations == 15
    assert loaded.restore_on_exit is True
    assert loaded.restore_color == "1,2,3"
