from pathlib import Path

from keylight.hid_discovery import (
    DiscoveryTemplate,
    HidDiscoveryConfig,
    run_hid_discovery,
    write_hid_discovery_report,
)
from keylight.models import RgbColor


def test_run_hid_discovery_matrix_counts_and_success() -> None:
    def fake_writer(
        *,
        report_bytes: list[int],
        hid_path: str | None = None,
        vendor_id: int | None = None,
        product_id: int | None = None,
        write_method: str = "output",
    ) -> int:
        if write_method == "feature" and report_bytes[0] == 1:
            return len(report_bytes)
        raise RuntimeError("fail")

    config = HidDiscoveryConfig(
        hid_path="test-path",
        vendor_id=None,
        product_id=None,
        zone_index=0,
        color=RgbColor(255, 0, 0),
        write_methods=["output", "feature"],
        report_ids=[0, 1],
        pad_lengths=[8],
        templates=[DiscoveryTemplate(name="base", template="{report_id} {zone} {r} {g} {b}")],
        delay_ms=0,
    )
    report = run_hid_discovery(config, writer=fake_writer)

    assert report.total_attempts == 4
    assert report.success_count == 1
    assert any(attempt.success for attempt in report.attempts)


def test_run_hid_discovery_stop_on_first_success() -> None:
    def fake_writer(
        *,
        report_bytes: list[int],
        hid_path: str | None = None,
        vendor_id: int | None = None,
        product_id: int | None = None,
        write_method: str = "output",
    ) -> int:
        return len(report_bytes)

    config = HidDiscoveryConfig(
        hid_path="test-path",
        vendor_id=None,
        product_id=None,
        zone_index=0,
        color=RgbColor(255, 0, 0),
        write_methods=["output", "feature"],
        report_ids=[0, 1],
        pad_lengths=[8, 16],
        templates=[DiscoveryTemplate(name="base", template="{report_id} {zone} {r} {g} {b}")],
        delay_ms=0,
        stop_on_first_success=True,
    )
    report = run_hid_discovery(config, writer=fake_writer)

    assert report.total_attempts == 1
    assert report.success_count == 1


def test_write_hid_discovery_report(tmp_path: Path) -> None:
    config = HidDiscoveryConfig(
        hid_path="test-path",
        vendor_id=None,
        product_id=None,
        zone_index=0,
        color=RgbColor(255, 0, 0),
        write_methods=["output"],
        report_ids=[0],
        pad_lengths=[8],
        templates=[DiscoveryTemplate(name="base", template="{report_id} {zone} {r} {g} {b}")],
        delay_ms=0,
    )
    report = run_hid_discovery(config, writer=lambda **_: 8)
    output_path = tmp_path / "hid_report.json"

    returned = write_hid_discovery_report(report, output_path)

    assert returned == output_path
    content = output_path.read_text(encoding="utf-8")
    assert "success_count" in content

