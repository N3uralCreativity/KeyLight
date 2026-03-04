from pathlib import Path

from keylight.calibrate_zones import (
    CalibrateZonesReport,
    build_observed_order_template,
    write_calibrate_zones_report,
    write_observed_order_template,
)


def test_build_observed_order_template_contains_zone_count() -> None:
    template = build_observed_order_template(4)

    assert "zone_count=4" in template
    assert "observed_order=" in template


def test_write_observed_order_template_writes_file(tmp_path: Path) -> None:
    output_path = write_observed_order_template(4, tmp_path / "observed.txt")

    content = output_path.read_text(encoding="utf-8")
    assert "logical_indexes=0, 1, 2, 3" in content


def test_write_calibrate_zones_report_writes_json(tmp_path: Path) -> None:
    report = CalibrateZonesReport(
        started_at_utc="2026-03-03T00:00:00+00:00",
        finished_at_utc="2026-03-03T00:00:01+00:00",
        zone_count=24,
        steps_executed=24,
        sweep_report_path="artifacts/calibrate_sweep_report.json",
        template_output_path=None,
        profile_output_path="config/calibration/final.json",
        observed_order=list(range(24)),
        profile_built=True,
        verify_requested=True,
        verify_executed=True,
        verify_steps_executed=24,
        verify_report_path="artifacts/calibrate_verify_sweep_report.json",
        live_verify_requested=True,
        live_verify_executed=True,
        live_verify_report_path="artifacts/calibrate_verify_live_report.json",
        live_verify_error=None,
    )
    output_path = write_calibrate_zones_report(report, tmp_path / "calibrate_report.json")

    content = output_path.read_text(encoding="utf-8")
    assert '"profile_built": true' in content
    assert '"steps_executed": 24' in content
    assert '"verify_executed": true' in content
    assert '"live_verify_executed": true' in content
