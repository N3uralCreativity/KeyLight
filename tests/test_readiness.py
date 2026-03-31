import json
import os
from pathlib import Path

import pytest

from keylight.readiness import ReadinessCheckConfig, run_readiness_check


def test_run_readiness_check_passes_with_skipped_optional_checks(tmp_path: Path) -> None:
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 2",
                "fps = 30",
                "iterations = 10",
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

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is True
    assert report.zone_count == 4


def test_run_readiness_check_uses_rows_columns_for_sound_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                "rows = 2",
                "columns = 12",
                "",
                "[mode]",
                'source = "sound"',
                "",
                "[mapping]",
                'backend = "calibrated"',
                "",
                "[driver]",
                'backend = "simulated"',
            ]
        ),
        encoding="utf-8",
    )

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is True
    assert report.zone_count == 24


def test_run_readiness_check_fails_on_calibration_zone_mismatch(tmp_path: Path) -> None:
    profile_path = tmp_path / "calibration.json"
    profile_path.write_text(
        json.dumps({"zone_count": 3, "logical_to_hardware": [0, 1, 2]}),
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

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert any("calibration_profile_zone_count_mismatch" in item for item in report.failed_checks)


def test_run_readiness_check_fails_when_calibration_profile_is_stale(tmp_path: Path) -> None:
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

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            max_calibration_profile_age_seconds=60,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert any(item.startswith("calibration_profile_too_old:") for item in report.failed_checks)


def test_run_readiness_check_requires_clean_preflight(tmp_path: Path) -> None:
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
        json.dumps({"unresolved_count": 2}),
        encoding="utf-8",
    )

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_preflight_clean=True,
            preflight_report_path=preflight_path,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert "preflight_unresolved_count=2" in report.failed_checks


def test_run_readiness_check_requires_preflight_admin(tmp_path: Path) -> None:
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

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_preflight_clean=True,
            require_preflight_admin=True,
            preflight_report_path=preflight_path,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert "preflight_is_not_admin" in report.failed_checks


def test_run_readiness_check_requires_preflight_strict_mode(tmp_path: Path) -> None:
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
        json.dumps({"unresolved_count": 0, "is_admin": True, "strict_mode": False}),
        encoding="utf-8",
    )

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_preflight_clean=True,
            require_preflight_strict_mode=True,
            preflight_report_path=preflight_path,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert "preflight_strict_mode=false" in report.failed_checks


def test_run_readiness_check_requires_preflight_access_denied_clear(tmp_path: Path) -> None:
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
                "is_admin": True,
                "strict_mode": True,
                "access_denied_count": 2,
            }
        ),
        encoding="utf-8",
    )

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_preflight_clean=True,
            require_preflight_access_denied_clear=True,
            preflight_report_path=preflight_path,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert "preflight_access_denied_count=2" in report.failed_checks


def test_run_readiness_check_requires_live_analysis_pass(tmp_path: Path) -> None:
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
        json.dumps({"passed": False}),
        encoding="utf-8",
    )

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_preflight_clean=False,
            require_live_analysis_pass=True,
            live_analysis_report_path=analysis_path,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert "live_analysis_passed=false" in report.failed_checks


def test_run_readiness_check_hid_presence_passes_with_path(
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
                'backend = "msi-mystic-hid"',
                'hid_path = "demo-hid"',
            ]
        ),
        encoding="utf-8",
    )

    class _Device:
        def __init__(self) -> None:
            self.path = "demo-hid"
            self.vendor_id = 0x1462
            self.product_id = 0x1603

    monkeypatch.setattr("keylight.readiness.list_hid_devices", lambda: [_Device()])
    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=True,
        )
    )

    assert report.passed is True
    assert "hid_path_present" in report.pass_checks


def test_run_readiness_check_require_hardware_backend_fails_for_simulated(
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

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_hardware_backend=True,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert "backend_is_not_hardware:simulated" in report.failed_checks


def test_run_readiness_check_require_calibrated_mapper_fails_for_grid(
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
                "[mapping]",
                'backend = "grid"',
                "",
                "[driver]",
                'backend = "simulated"',
            ]
        ),
        encoding="utf-8",
    )

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_calibrated_mapper=True,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert "mapper_is_not_calibrated:grid" in report.failed_checks


def test_run_readiness_check_require_calibration_profile_fails_when_missing(
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

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_calibration_profile=True,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert "calibration_profile_missing" in report.failed_checks


def test_run_readiness_check_forbid_identity_calibration_fails(tmp_path: Path) -> None:
    profile_path = tmp_path / "calibration.json"
    profile_path.write_text(
        json.dumps({"zone_count": 4, "logical_to_hardware": [0, 1, 2, 3]}),
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

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            forbid_identity_calibration=True,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert "calibration_profile_is_identity" in report.failed_checks


def test_run_readiness_check_fails_when_preflight_report_is_stale(tmp_path: Path) -> None:
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

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_preflight_clean=True,
            preflight_report_path=preflight_path,
            max_preflight_age_seconds=60,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert any(item.startswith("preflight_report_too_old:") for item in report.failed_checks)


def test_run_readiness_check_fails_when_live_analysis_report_is_stale(tmp_path: Path) -> None:
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
                "generated_at_utc": "2000-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_preflight_clean=False,
            require_live_analysis_pass=True,
            live_analysis_report_path=analysis_path,
            max_live_analysis_age_seconds=60,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert any(item.startswith("live_analysis_report_too_old:") for item in report.failed_checks)


def test_run_readiness_check_validates_live_analysis_threshold_policy(
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
                    "max_error_rate_percent": 5.0,
                    "max_avg_total_ms": 120.0,
                    "max_p95_total_ms": 150.0,
                    "min_effective_fps": 10.0,
                    "max_overrun_percent": 60.0,
                },
            }
        ),
        encoding="utf-8",
    )

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            live_analysis_report_path=analysis_path,
            max_live_analysis_threshold_max_error_rate_percent=1.0,
            max_live_analysis_threshold_max_avg_total_ms=80.0,
            max_live_analysis_threshold_max_p95_total_ms=120.0,
            min_live_analysis_threshold_min_effective_fps=20.0,
            max_live_analysis_threshold_max_overrun_percent=25.0,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert any(
        item.startswith("live_analysis_threshold_max_error_rate_percent_too_weak:")
        for item in report.failed_checks
    )
    assert any(
        item.startswith("live_analysis_threshold_min_effective_fps_too_weak:")
        for item in report.failed_checks
    )


def test_run_readiness_check_live_analysis_threshold_policy_passes(tmp_path: Path) -> None:
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
                    "max_error_rate_percent": 1.0,
                    "max_avg_total_ms": 80.0,
                    "max_p95_total_ms": 120.0,
                    "min_effective_fps": 20.0,
                    "max_overrun_percent": 25.0,
                },
            }
        ),
        encoding="utf-8",
    )

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            live_analysis_report_path=analysis_path,
            max_live_analysis_threshold_max_error_rate_percent=1.0,
            max_live_analysis_threshold_max_avg_total_ms=80.0,
            max_live_analysis_threshold_max_p95_total_ms=120.0,
            min_live_analysis_threshold_min_effective_fps=20.0,
            max_live_analysis_threshold_max_overrun_percent=25.0,
            require_hid_present=False,
        )
    )

    assert report.passed is True
    assert any(
        item.startswith("live_analysis_threshold_max_error_rate_percent<=")
        for item in report.pass_checks
    )


def test_run_readiness_check_rejects_negative_age_threshold(tmp_path: Path) -> None:
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

    with pytest.raises(ValueError):
        run_readiness_check(
            ReadinessCheckConfig(
                config_path=config_path,
                max_preflight_age_seconds=-1,
                require_preflight_clean=False,
                require_live_analysis_pass=False,
                require_hid_present=False,
            )
        )


def test_run_readiness_check_rejects_invalid_overrun_policy_percent(tmp_path: Path) -> None:
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

    with pytest.raises(ValueError):
        run_readiness_check(
            ReadinessCheckConfig(
                config_path=config_path,
                max_live_analysis_threshold_max_overrun_percent=120.0,
                require_preflight_clean=False,
                require_live_analysis_pass=False,
                require_hid_present=False,
            )
        )


def test_run_readiness_check_requires_calibration_workflow_and_verify(
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
    workflow_path = tmp_path / "calibrate_report_final.json"
    workflow_path.write_text(
        json.dumps(
            {
                "started_at_utc": "2026-03-04T00:00:00Z",
                "finished_at_utc": "2026-03-04T00:00:10Z",
                "zone_count": 4,
                "steps_executed": 4,
                "sweep_report_path": None,
                "template_output_path": None,
                "profile_output_path": "calibration.json",
                "observed_order": [1, 0, 3, 2],
                "profile_built": True,
                "verify_requested": True,
                "verify_executed": True,
                "verify_steps_executed": 4,
                "live_verify_requested": True,
                "live_verify_executed": True,
                "live_verify_error": None,
            }
        ),
        encoding="utf-8",
    )

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_calibration_workflow=True,
            calibration_workflow_report_path=workflow_path,
            require_calibration_verify_executed=True,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is True
    assert "calibration_workflow_profile_built" in report.pass_checks
    assert "calibration_workflow_verify_executed" in report.pass_checks


def test_run_readiness_check_fails_when_workflow_order_mismatches_profile(
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
    workflow_path = tmp_path / "calibrate_report_final.json"
    workflow_path.write_text(
        json.dumps(
            {
                "finished_at_utc": "2026-03-04T00:00:10Z",
                "zone_count": 4,
                "profile_built": True,
                "observed_order": [0, 1, 2, 3],
                "profile_output_path": "calibration.json",
                "verify_executed": True,
                "verify_steps_executed": 4,
            }
        ),
        encoding="utf-8",
    )

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_calibration_workflow=True,
            calibration_workflow_report_path=workflow_path,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert "calibration_workflow_observed_order_mismatch_profile" in report.failed_checks


def test_run_readiness_check_requires_calibration_live_verify_success(
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
    workflow_path = tmp_path / "calibrate_report_final.json"
    workflow_path.write_text(
        json.dumps(
            {
                "finished_at_utc": "2026-03-04T00:00:10Z",
                "zone_count": 4,
                "profile_built": True,
                "observed_order": [1, 0, 3, 2],
                "profile_output_path": "calibration.json",
                "verify_executed": True,
                "verify_steps_executed": 4,
                "live_verify_executed": True,
                "live_verify_error": None,
            }
        ),
        encoding="utf-8",
    )

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_calibration_workflow=True,
            require_calibration_verify_executed=True,
            require_calibration_live_verify_executed=True,
            require_calibration_live_verify_success=True,
            calibration_workflow_report_path=workflow_path,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is True
    assert "calibration_workflow_live_verify_executed" in report.pass_checks
    assert "calibration_workflow_live_verify_success" in report.pass_checks


def test_run_readiness_check_fails_when_calibration_live_verify_failed(
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
                "finished_at_utc": "2026-03-04T00:00:10Z",
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

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_calibration_live_verify_success=True,
            calibration_workflow_report_path=workflow_path,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert any(
        item.startswith("calibration_workflow_live_verify_failed:")
        for item in report.failed_checks
    )


def test_run_readiness_check_fails_when_calibration_workflow_is_stale(
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
                "finished_at_utc": "2000-01-01T00:00:00Z",
                "zone_count": 4,
                "profile_built": True,
                "observed_order": [0, 1, 2, 3],
                "profile_output_path": "config/calibration/final.json",
                "verify_executed": True,
                "verify_steps_executed": 4,
            }
        ),
        encoding="utf-8",
    )

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_calibration_workflow=False,
            calibration_workflow_report_path=workflow_path,
            max_calibration_workflow_age_seconds=60,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert any(item.startswith("calibration_workflow_too_old:") for item in report.failed_checks)


def test_run_readiness_check_requires_calibration_profile_generated_timestamp(
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

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_calibration_profile_generated_timestamp=True,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert any(
        item.startswith("calibration_profile_generated_timestamp_error=")
        for item in report.failed_checks
    )


def test_run_readiness_check_requires_calibration_profile_provenance(
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

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_calibration_profile_provenance=True,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert any(
        item.startswith("calibration_profile_provenance_error=")
        for item in report.failed_checks
    )


def test_run_readiness_check_passes_calibration_profile_provenance_workflow_match(
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
                    "workflow_report_path": "calibrate_report_final.json",
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

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_calibration_profile_provenance=True,
            require_calibration_profile_provenance_workflow_match=True,
            calibration_workflow_report_path=workflow_path,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is True
    assert "calibration_profile_provenance_valid" in report.pass_checks
    assert "calibration_profile_provenance_workflow_matches_config" in report.pass_checks


def test_run_readiness_check_fails_calibration_profile_provenance_workflow_mismatch(
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

    report = run_readiness_check(
        ReadinessCheckConfig(
            config_path=config_path,
            require_calibration_profile_provenance_workflow_match=True,
            calibration_workflow_report_path=workflow_path,
            require_preflight_clean=False,
            require_live_analysis_pass=False,
            require_hid_present=False,
        )
    )

    assert report.passed is False
    assert any(
        item.startswith("calibration_profile_provenance_workflow_mismatch:")
        for item in report.failed_checks
    )
