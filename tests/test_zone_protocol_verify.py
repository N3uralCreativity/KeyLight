from pathlib import Path

from keylight.models import RgbColor
from keylight.zone_protocol_verify import (
    ZoneProtocolVerifyConfig,
    default_zone_probe_offsets,
    run_zone_protocol_verify,
    write_zone_protocol_verify_report,
)


def test_default_zone_probe_offsets_values() -> None:
    offsets = default_zone_probe_offsets()

    assert offsets
    assert 3 in offsets
    assert 24 in offsets


def test_run_zone_protocol_verify_writes_prep_and_color_packets() -> None:
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

    config = ZoneProtocolVerifyConfig(
        hid_path="test-path",
        vendor_id=None,
        product_id=None,
        zone_sequence=[7, 9],
        color_sequence=[RgbColor(255, 0, 0)],
        offsets=[3, 4],
        step_delay_ms=0,
        repeat=1,
        pad_length=64,
    )

    report = run_zone_protocol_verify(config, writer=fake_writer)

    assert report.total_steps == 2
    assert report.success_count == 2
    assert len(packets) == 4
    assert all(method == "feature" for method in methods)
    assert packets[0][:2] == [0x02, 0x01]
    assert packets[1][3] == 7
    assert packets[3][4] == 9


def test_write_zone_protocol_verify_report(tmp_path: Path) -> None:
    config = ZoneProtocolVerifyConfig(
        hid_path="test-path",
        vendor_id=None,
        product_id=None,
        zone_sequence=[0],
        color_sequence=[RgbColor(255, 0, 0)],
        offsets=[3],
        step_delay_ms=0,
        repeat=1,
        pad_length=64,
    )
    report = run_zone_protocol_verify(config, writer=lambda **_: 64)
    output_path = tmp_path / "zone_protocol_verify.json"

    returned = write_zone_protocol_verify_report(report, output_path)

    assert returned == output_path
    content = output_path.read_text(encoding="utf-8")
    assert "success_count" in content
