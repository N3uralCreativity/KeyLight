from pathlib import Path

import pytest

from keylight.app import AppLiveRunConfig, build_live_command, select_preferred_msi_hid_path
from keylight.drivers.hid_raw import HidDeviceInfo


def _hid(
    *,
    path: str,
    vendor_id: int,
    product_id: int,
    usage_page: int,
    usage: int,
) -> HidDeviceInfo:
    return HidDeviceInfo(
        path=path,
        vendor_id=vendor_id,
        product_id=product_id,
        manufacturer_string="",
        product_string="",
        serial_number="",
        usage_page=usage_page,
        usage=usage,
        interface_number=0,
    )


def test_select_preferred_msi_hid_path_prefers_vendor_usage_interface() -> None:
    devices = [
        _hid(
            path="other",
            vendor_id=0x1234,
            product_id=0x5678,
            usage_page=0x00FF,
            usage=0x0001,
        ),
        _hid(
            path="fallback-msi",
            vendor_id=0x1462,
            product_id=0x1603,
            usage_page=0x0001,
            usage=0x0006,
        ),
        _hid(
            path="preferred-msi",
            vendor_id=0x1462,
            product_id=0x1603,
            usage_page=0x00FF,
            usage=0x0001,
        ),
    ]

    selected = select_preferred_msi_hid_path(devices)

    assert selected == "preferred-msi"


def test_build_live_command_uses_config_driven_launch(tmp_path: Path) -> None:
    config = AppLiveRunConfig(
        config_path=tmp_path / "default.toml",
        output_path=tmp_path / "live_report.json",
    )

    command = build_live_command(python_executable="python", config=config)

    assert command == [
        "python",
        "-m",
        "keylight.cli",
        "live",
        "--config",
        str(tmp_path / "default.toml"),
        "--output",
        str(tmp_path / "live_report.json"),
    ]


def test_build_live_command_rejects_blank_config_path(tmp_path: Path) -> None:
    config = AppLiveRunConfig(
        config_path=Path(""),
        output_path=tmp_path / "live_report.json",
    )

    with pytest.raises(ValueError, match="Config path is required"):
        build_live_command(python_executable="python", config=config)


def test_app_main_parser_supports_no_autostart() -> None:
    from keylight.app import _build_parser

    args = _build_parser().parse_args(["--no-autostart", "--no-tray", "--no-start-hidden"])

    assert args.autostart is False
    assert args.tray is False
    assert args.start_hidden is False
