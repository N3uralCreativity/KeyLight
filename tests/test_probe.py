from pathlib import Path

import pytest

from keylight.drivers.probe import (
    DeviceInfo,
    ProbeReport,
    ProcessInfo,
    ServiceInfo,
    build_recommendations,
    infer_likely_control_paths,
    run_probe,
    write_probe_report,
)


def test_infer_likely_control_paths_uses_service_and_device_hints() -> None:
    services = [
        ServiceInfo(
            name="MSIService",
            display_name="MSI Service",
            state="Running",
            start_mode="Auto",
        )
    ]
    devices = [
        DeviceInfo(
            friendly_name="SteelSeries Keyboard",
            instance_id="HID\\ABC",
            device_class="Keyboard",
            status="OK",
        )
    ]

    paths = infer_likely_control_paths(services, devices)

    assert paths == [
        "SteelSeries GG/Engine integration path",
        "MSI Center service bridge path",
        "Direct HID vendor protocol path",
    ]


def test_build_recommendations_flags_conflicts_and_permissions() -> None:
    recommendations = build_recommendations(
        is_admin=False,
        conflict_processes=[ProcessInfo(process_name="LEDKeeper2", pid=123)],
        services=[],
        devices=[],
    )

    assert any("preflight.ps1" in item for item in recommendations)
    assert any("Administrator" in item for item in recommendations)
    assert any("No MSI/SteelSeries services found" in item for item in recommendations)
    assert any("No candidate keyboard/HID devices matched" in item for item in recommendations)


def test_write_probe_report_persists_json(tmp_path: Path) -> None:
    report = ProbeReport(
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
    output_path = tmp_path / "probe.json"

    returned_path = write_probe_report(report, output_path)

    assert returned_path == output_path
    content = output_path.read_text(encoding="utf-8")
    assert "Direct HID vendor protocol path" in content


def test_run_probe_non_windows_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("keylight.drivers.probe.platform.system", lambda: "Linux")
    monkeypatch.setattr("keylight.drivers.probe.platform.platform", lambda: "Linux-x64")

    report = run_probe()

    assert report.platform_name == "Linux-x64"
    assert report.likely_control_paths == ["Windows-only target hardware path required."]
