from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HidDeviceInfo:
    path: str
    vendor_id: int
    product_id: int
    manufacturer_string: str
    product_string: str
    serial_number: str
    usage_page: int
    usage: int
    interface_number: int


def list_hid_devices() -> list[HidDeviceInfo]:
    hid_module = _load_hid_module()
    raw_devices: list[dict[str, Any]] = hid_module.enumerate()
    devices: list[HidDeviceInfo] = []
    for device in raw_devices:
        devices.append(
            HidDeviceInfo(
                path=_coerce_path(device.get("path")),
                vendor_id=_to_int(device.get("vendor_id")),
                product_id=_to_int(device.get("product_id")),
                manufacturer_string=str(device.get("manufacturer_string") or ""),
                product_string=str(device.get("product_string") or ""),
                serial_number=str(device.get("serial_number") or ""),
                usage_page=_to_int(device.get("usage_page")),
                usage=_to_int(device.get("usage")),
                interface_number=_to_int(device.get("interface_number")),
            )
        )
    return devices


def write_output_report(
    *,
    report_bytes: list[int],
    hid_path: str | None = None,
    vendor_id: int | None = None,
    product_id: int | None = None,
    write_method: str = "output",
) -> int:
    hid_module = _load_hid_module()
    hid_device = hid_module.device()
    try:
        if hid_path:
            hid_device.open_path(hid_path.encode("utf-8"))
        elif vendor_id is not None and product_id is not None:
            hid_device.open(vendor_id, product_id)
        else:
            raise ValueError(
                "hid_path or vendor_id/product_id must be provided for hid-raw backend."
            )
        if write_method == "output":
            bytes_written = int(hid_device.write(report_bytes))
        elif write_method == "feature":
            bytes_written = int(hid_device.send_feature_report(report_bytes))
        else:
            raise ValueError(f"Unsupported HID write method '{write_method}'")
        if bytes_written < 0:
            raise RuntimeError(_build_hid_error_message(hid_device))
        return bytes_written
    finally:
        hid_device.close()


def _load_hid_module() -> Any:
    try:
        import hid  # type: ignore[import-not-found]
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "HID backend requires Python package 'hidapi'. Install with: pip install hidapi"
        ) from error
    return hid


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_path(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None:
        return ""
    return str(value)


def _build_hid_error_message(hid_device: Any) -> str:
    try:
        raw_error = hid_device.error()
    except Exception:
        raw_error = ""
    error_text = str(raw_error or "").strip()
    if error_text:
        return f"HID write failed: {error_text}"
    return "HID write failed: unknown device error."
