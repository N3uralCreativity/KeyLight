import pytest

from keylight.drivers.msi_mystic_hid import MsiMysticHidConfig, MsiMysticHidDriver
from keylight.models import RgbColor, ZoneColor


def test_msi_driver_writes_expected_packet_legacy_protocol() -> None:
    calls: list[dict[str, object]] = []

    def fake_writer(
        *,
        report_bytes: list[int],
        hid_path: str | None = None,
        vendor_id: int | None = None,
        product_id: int | None = None,
        write_method: str = "output",
    ) -> int:
        calls.append(
            {
                "report_bytes": report_bytes,
                "hid_path": hid_path,
                "vendor_id": vendor_id,
                "product_id": product_id,
                "write_method": write_method,
            }
        )
        return len(report_bytes)

    driver = MsiMysticHidDriver(
        config=MsiMysticHidConfig(
            hid_path="test-path",
            report_id=1,
            pad_length=8,
            zone_count=24,
            protocol="legacy-zone",
        ),
        writer=fake_writer,
    )
    driver.apply_zone_colors([ZoneColor(zone_index=2, color=RgbColor(10, 20, 30))])

    assert len(calls) == 1
    assert calls[0]["report_bytes"] == [1, 2, 10, 20, 30, 0, 0, 0]


def test_msi_driver_skips_unchanged_zone_colors() -> None:
    call_count = 0

    def fake_writer(
        *,
        report_bytes: list[int],
        hid_path: str | None = None,
        vendor_id: int | None = None,
        product_id: int | None = None,
        write_method: str = "output",
    ) -> int:
        nonlocal call_count
        call_count += 1
        return len(report_bytes)

    driver = MsiMysticHidDriver(
        config=MsiMysticHidConfig(
            hid_path="test-path",
            pad_length=8,
            zone_count=24,
            protocol="legacy-zone",
        ),
        writer=fake_writer,
    )
    payload = [ZoneColor(zone_index=1, color=RgbColor(255, 0, 0))]
    driver.apply_zone_colors(payload)
    driver.apply_zone_colors(payload)

    assert call_count == 1


def test_msi_driver_rejects_zone_outside_configured_count() -> None:
    driver = MsiMysticHidDriver(
        config=MsiMysticHidConfig(
            hid_path="test-path",
            pad_length=8,
            zone_count=4,
            protocol="legacy-zone",
        ),
        writer=lambda **_: 8,
    )

    with pytest.raises(ValueError):
        driver.apply_zone_colors([ZoneColor(zone_index=5, color=RgbColor(1, 2, 3))])


def test_msi_driver_falls_back_to_vid_pid_on_hid_path_failure() -> None:
    hid_paths: list[str | None] = []

    def flaky_writer(
        *,
        report_bytes: list[int],
        hid_path: str | None = None,
        vendor_id: int | None = None,
        product_id: int | None = None,
        write_method: str = "output",
    ) -> int:
        hid_paths.append(hid_path)
        if hid_path == "bad-path":
            raise RuntimeError("open_path failed")
        return len(report_bytes)

    driver = MsiMysticHidDriver(
        config=MsiMysticHidConfig(
            hid_path="bad-path",
            vendor_id=0x1462,
            product_id=0x1603,
            pad_length=8,
            zone_count=24,
            protocol="legacy-zone",
        ),
        writer=flaky_writer,
    )

    driver.apply_zone_colors([ZoneColor(zone_index=0, color=RgbColor(1, 2, 3))])
    driver.apply_zone_colors([ZoneColor(zone_index=1, color=RgbColor(4, 5, 6))])

    assert hid_paths == ["bad-path", None, None]


def test_msi_driver_reconnect_refreshes_matching_hid_path() -> None:
    calls: list[str | None] = []

    class _Device:
        def __init__(self, path: str, vendor_id: int, product_id: int) -> None:
            self.path = path
            self.vendor_id = vendor_id
            self.product_id = product_id

    def fake_writer(
        *,
        report_bytes: list[int],
        hid_path: str | None = None,
        vendor_id: int | None = None,
        product_id: int | None = None,
        write_method: str = "output",
    ) -> int:
        calls.append(hid_path)
        return len(report_bytes)

    driver = MsiMysticHidDriver(
        config=MsiMysticHidConfig(
            hid_path="old-path",
            vendor_id=0x1462,
            product_id=0x1603,
            pad_length=8,
            zone_count=24,
            protocol="legacy-zone",
        ),
        writer=fake_writer,
        device_enumerator=lambda: [_Device("new-path", 0x1462, 0x1603)],
    )

    assert driver.reconnect() is True
    driver.apply_zone_colors([ZoneColor(zone_index=0, color=RgbColor(10, 20, 30))])

    assert calls == ["new-path"]


def test_msi_driver_writes_expected_packets_msi_center_protocol() -> None:
    calls: list[dict[str, object]] = []

    def fake_writer(
        *,
        report_bytes: list[int],
        hid_path: str | None = None,
        vendor_id: int | None = None,
        product_id: int | None = None,
        write_method: str = "output",
    ) -> int:
        calls.append(
            {
                "report_bytes": report_bytes,
                "hid_path": hid_path,
                "vendor_id": vendor_id,
                "product_id": product_id,
                "write_method": write_method,
            }
        )
        return len(report_bytes)

    driver = MsiMysticHidDriver(
        config=MsiMysticHidConfig(
            hid_path="test-path",
            zone_count=24,
            pad_length=64,
            protocol="msi-center-feature-global",
        ),
        writer=fake_writer,
    )
    driver.apply_zone_colors([ZoneColor(zone_index=2, color=RgbColor(10, 20, 30))])

    assert len(calls) == 2
    assert calls[0]["write_method"] == "feature"
    assert calls[1]["write_method"] == "feature"
    prep_bytes = calls[0]["report_bytes"]
    color_bytes = calls[1]["report_bytes"]
    assert isinstance(prep_bytes, list)
    assert isinstance(color_bytes, list)
    assert prep_bytes[:34] == [0x02, 0x01] + ([0xFF] * 32)
    assert all(value == 0 for value in prep_bytes[34:])
    assert color_bytes[:18] == [
        0x02,
        0x02,
        0x01,
        0x58,
        0x02,
        0x00,
        0x32,
        0x08,
        0x01,
        0x01,
        0x00,
        10,
        20,
        30,
        0x64,
        10,
        20,
        30,
    ]
    assert all(value == 0 for value in color_bytes[18:])


def test_msi_driver_skips_unchanged_global_color_msi_center_protocol() -> None:
    call_count = 0

    def fake_writer(
        *,
        report_bytes: list[int],
        hid_path: str | None = None,
        vendor_id: int | None = None,
        product_id: int | None = None,
        write_method: str = "output",
    ) -> int:
        nonlocal call_count
        call_count += 1
        return len(report_bytes)

    driver = MsiMysticHidDriver(
        config=MsiMysticHidConfig(
            hid_path="test-path",
            pad_length=64,
            zone_count=24,
            protocol="msi-center-feature-global",
        ),
        writer=fake_writer,
    )
    payload = [ZoneColor(zone_index=1, color=RgbColor(255, 0, 0))]
    driver.apply_zone_colors(payload)
    driver.apply_zone_colors(payload)

    assert call_count == 2


def test_msi_driver_writes_expected_zone_mask_packets_msi_center_protocol() -> None:
    packets: list[list[int]] = []
    methods: list[str] = []

    def fake_writer(
        *,
        report_bytes: list[int],
        hid_path: str | None = None,
        vendor_id: int | None = None,
        product_id: int | None = None,
        write_method: str = "output",
    ) -> int:
        packets.append(report_bytes)
        methods.append(write_method)
        return len(report_bytes)

    driver = MsiMysticHidDriver(
        config=MsiMysticHidConfig(
            hid_path="test-path",
            zone_count=24,
            pad_length=64,
            protocol="msi-center-feature-zones",
        ),
        writer=fake_writer,
    )
    driver.apply_zone_colors(
        [
            ZoneColor(zone_index=0, color=RgbColor(255, 0, 0)),
            ZoneColor(zone_index=9, color=RgbColor(0, 255, 0)),
        ]
    )

    assert len(packets) == 4
    assert all(method == "feature" for method in methods)
    assert packets[0][:6] == [0x02, 0x01, 0x01, 0x00, 0x00, 0x00]
    assert packets[1][11:14] == [255, 0, 0]
    assert packets[2][:6] == [0x02, 0x01, 0x00, 0x02, 0x00, 0x00]
    assert packets[3][11:14] == [0, 255, 0]


def test_msi_driver_skips_unchanged_zone_color_msi_center_zone_protocol() -> None:
    call_count = 0

    def fake_writer(
        *,
        report_bytes: list[int],
        hid_path: str | None = None,
        vendor_id: int | None = None,
        product_id: int | None = None,
        write_method: str = "output",
    ) -> int:
        nonlocal call_count
        call_count += 1
        return len(report_bytes)

    driver = MsiMysticHidDriver(
        config=MsiMysticHidConfig(
            hid_path="test-path",
            pad_length=64,
            zone_count=24,
            protocol="msi-center-feature-zones",
        ),
        writer=fake_writer,
    )
    payload = [ZoneColor(zone_index=2, color=RgbColor(10, 20, 30))]
    driver.apply_zone_colors(payload)
    driver.apply_zone_colors(payload)

    assert call_count == 2
