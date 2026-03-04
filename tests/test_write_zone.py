import pytest

from keylight.models import RgbColor
from keylight.write_zone import (
    WriteZoneConfig,
    build_report_bytes_from_template,
    execute_write_zone,
)


def test_build_report_bytes_from_template_replaces_tokens() -> None:
    report = build_report_bytes_from_template(
        template="{report_id} AA {zone} {r} {g} {b}",
        zone_index=5,
        color=RgbColor(10, 20, 30),
        report_id=2,
    )

    assert report == [2, 0xAA, 5, 10, 20, 30]


def test_build_report_bytes_from_template_rejects_invalid_tokens() -> None:
    with pytest.raises(ValueError):
        build_report_bytes_from_template(
            template="GG {zone}",
            zone_index=0,
            color=RgbColor(1, 2, 3),
            report_id=0,
        )


def test_execute_write_zone_simulated_backend_succeeds() -> None:
    result = execute_write_zone(
        WriteZoneConfig(
            backend="simulated",
            zone_index=3,
            zone_count=24,
            color=RgbColor(255, 0, 0),
        )
    )

    assert result.success is True
    assert result.backend == "simulated"
    assert result.error is None


def test_execute_write_zone_hid_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_write_output_report(
        *,
        report_bytes: list[int],
        hid_path: str | None = None,
        vendor_id: int | None = None,
        product_id: int | None = None,
        write_method: str = "output",
    ) -> int:
        raise RuntimeError("hid missing")

    monkeypatch.setattr("keylight.write_zone.write_output_report", fake_write_output_report)
    result = execute_write_zone(
        WriteZoneConfig(
            backend="hid-raw",
            zone_index=0,
            zone_count=24,
            color=RgbColor(1, 2, 3),
            packet_template="{report_id} {zone} {r} {g} {b}",
            report_id=1,
            hid_path="test-path",
        )
    )

    assert result.success is False
    assert result.error == "hid missing"


def test_execute_write_zone_hid_pad_and_method(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_write_output_report(
        *,
        report_bytes: list[int],
        hid_path: str | None = None,
        vendor_id: int | None = None,
        product_id: int | None = None,
        write_method: str = "output",
    ) -> int:
        captured["report_bytes"] = report_bytes
        captured["write_method"] = write_method
        return len(report_bytes)

    monkeypatch.setattr("keylight.write_zone.write_output_report", fake_write_output_report)
    result = execute_write_zone(
        WriteZoneConfig(
            backend="hid-raw",
            zone_index=2,
            zone_count=24,
            color=RgbColor(10, 20, 30),
            packet_template="{report_id} {zone} {r} {g} {b}",
            report_id=1,
            pad_to=8,
            write_method="feature",
            hid_path="test-path",
        )
    )

    assert result.success is True
    assert result.bytes_written == 8
    assert result.report_bytes == [1, 2, 10, 20, 30, 0, 0, 0]
    assert captured["report_bytes"] == [1, 2, 10, 20, 30, 0, 0, 0]
    assert captured["write_method"] == "feature"


def test_execute_write_zone_hid_pad_too_small_fails() -> None:
    result = execute_write_zone(
        WriteZoneConfig(
            backend="hid-raw",
            zone_index=0,
            zone_count=24,
            color=RgbColor(1, 2, 3),
            packet_template="{report_id} {zone} {r} {g} {b}",
            report_id=0,
            pad_to=3,
            hid_path="test-path",
        )
    )

    assert result.success is False
    assert "exceeds pad_to" in (result.error or "")


def test_execute_write_zone_msi_backend_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeDriver:
        def __init__(self, config: object) -> None:
            self._config = config

        def apply_zone_colors(self, zones: list[object]) -> None:
            assert len(zones) == 24

    monkeypatch.setattr("keylight.write_zone.MsiMysticHidDriver", _FakeDriver)
    result = execute_write_zone(
        WriteZoneConfig(
            backend="msi-mystic-hid",
            zone_index=4,
            zone_count=24,
            color=RgbColor(9, 8, 7),
            hid_path="test-path",
        )
    )

    assert result.success is True
    assert result.backend == "msi-mystic-hid"
