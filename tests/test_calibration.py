import json
from pathlib import Path

import pytest

from keylight.calibration import (
    CalibratedDriver,
    CalibrationProfile,
    identity_profile,
    load_calibration_profile,
    profile_from_observed_order,
    remap_zones_to_hardware,
    write_calibration_profile,
)
from keylight.models import RgbColor, ZoneColor


def test_identity_profile_is_valid_permutation() -> None:
    profile = identity_profile(4)

    assert profile.zone_count == 4
    assert profile.logical_to_hardware == [0, 1, 2, 3]


def test_remap_zones_to_hardware_applies_mapping() -> None:
    profile = CalibrationProfile(zone_count=4, logical_to_hardware=[2, 0, 3, 1])
    profile.validate()
    zones = [
        ZoneColor(zone_index=0, color=RgbColor(255, 0, 0)),
        ZoneColor(zone_index=1, color=RgbColor(0, 255, 0)),
    ]

    remapped = remap_zones_to_hardware(zones, profile)

    assert [zone.zone_index for zone in remapped] == [2, 0]


def test_write_and_load_calibration_profile_roundtrip(tmp_path: Path) -> None:
    profile = CalibrationProfile(zone_count=4, logical_to_hardware=[1, 3, 0, 2])
    output_path = tmp_path / "profile.json"

    write_calibration_profile(profile, output_path)
    loaded = load_calibration_profile(output_path)

    assert loaded == profile


def test_profile_from_observed_order_validates_length() -> None:
    profile = profile_from_observed_order([1, 0, 3, 2], zone_count=4)

    assert profile.logical_to_hardware == [1, 0, 3, 2]


def test_profile_from_observed_order_sets_metadata() -> None:
    profile = profile_from_observed_order(
        [1, 0, 3, 2],
        zone_count=4,
        source_method="calibrate-zones",
        workflow_report_path="artifacts/calibrate_report_final.json",
    )

    assert profile.generated_at_utc is not None
    assert profile.provenance is not None
    assert profile.provenance.method == "calibrate-zones"
    assert profile.provenance.observed_order == [1, 0, 3, 2]
    assert profile.provenance.workflow_report_path == "artifacts/calibrate_report_final.json"


def test_load_calibration_profile_fails_on_provenance_mismatch(tmp_path: Path) -> None:
    profile_path = tmp_path / "calibration.json"
    profile_path.write_text(
        json.dumps(
            {
                "zone_count": 4,
                "logical_to_hardware": [1, 0, 3, 2],
                "generated_at_utc": "2026-03-04T00:00:00Z",
                "provenance": {
                    "method": "calibrate-zones",
                    "observed_order": [0, 1, 2, 3],
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="provenance\\.observed_order"):
        load_calibration_profile(profile_path)


def test_load_calibration_profile_accepts_utf8_bom(tmp_path: Path) -> None:
    profile_path = tmp_path / "calibration_bom.json"
    profile_path.write_text(
        json.dumps({"zone_count": 4, "logical_to_hardware": [1, 0, 3, 2]}),
        encoding="utf-8-sig",
    )

    loaded = load_calibration_profile(profile_path)

    assert loaded.zone_count == 4
    assert loaded.logical_to_hardware == [1, 0, 3, 2]


def test_calibrated_driver_remaps_before_apply() -> None:
    class _RecordingDriver:
        def __init__(self) -> None:
            self.received: list[ZoneColor] = []

        def apply_zone_colors(self, zones: list[ZoneColor]) -> None:
            self.received = zones

    base = _RecordingDriver()
    profile = CalibrationProfile(zone_count=4, logical_to_hardware=[3, 2, 1, 0])
    profile.validate()
    driver = CalibratedDriver(base_driver=base, profile=profile)

    driver.apply_zone_colors([ZoneColor(zone_index=1, color=RgbColor(10, 20, 30))])

    assert len(base.received) == 1
    assert base.received[0].zone_index == 2
