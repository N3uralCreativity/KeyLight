from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from keylight.drivers.hid_raw import list_hid_devices, write_output_report
from keylight.models import RgbColor, ZoneColor


@dataclass(frozen=True, slots=True)
class MsiMysticHidConfig:
    hid_path: str | None = None
    vendor_id: int = 0x1462
    product_id: int = 0x1603
    packet_template: str = "{report_id} {zone} {r} {g} {b}"
    report_id: int = 1
    write_method: str = "output"
    pad_length: int = 64
    zone_count: int = 24

    def validate(self) -> None:
        if self.vendor_id < 0 or self.vendor_id > 0xFFFF:
            raise ValueError("vendor_id must be in range 0..65535")
        if self.product_id < 0 or self.product_id > 0xFFFF:
            raise ValueError("product_id must be in range 0..65535")
        if self.report_id < 0 or self.report_id > 255:
            raise ValueError("report_id must be in range 0..255")
        if self.write_method not in {"output", "feature"}:
            raise ValueError("write_method must be 'output' or 'feature'")
        if self.pad_length <= 0:
            raise ValueError("pad_length must be positive")
        if self.zone_count <= 0:
            raise ValueError("zone_count must be positive")


class MsiMysticHidDriver:
    """MSI MysticLight HID keyboard driver with per-zone packet writes."""

    def __init__(
        self,
        config: MsiMysticHidConfig,
        writer: Callable[..., int] = write_output_report,
        device_enumerator: Callable[[], object] = list_hid_devices,
    ) -> None:
        config.validate()
        self._config = config
        self._writer = writer
        self._device_enumerator = device_enumerator
        self._active_hid_path: str | None = config.hid_path
        self._last_zone_colors: dict[int, RgbColor] = {}

    def apply_zone_colors(self, zones: list[ZoneColor]) -> None:
        for zone in sorted(zones, key=lambda item: item.zone_index):
            zone_index = zone.zone_index
            if zone_index < 0 or zone_index >= self._config.zone_count:
                raise ValueError(
                    f"zone_index {zone_index} is outside configured zone_count "
                    f"{self._config.zone_count}"
                )

            clamped_color = zone.color.clamped()
            previous = self._last_zone_colors.get(zone_index)
            if previous == clamped_color:
                continue

            packet = _build_packet(
                template=self._config.packet_template,
                zone_index=zone_index,
                color=clamped_color,
                report_id=self._config.report_id,
                pad_length=self._config.pad_length,
            )
            try:
                written = self._write_packet(packet=packet, hid_path=self._active_hid_path)
            except (RuntimeError, OSError) as original_error:
                if self._active_hid_path is None:
                    raise
                try:
                    written = self._write_packet(packet=packet, hid_path=None)
                except (RuntimeError, OSError):
                    raise original_error from None
                self._active_hid_path = None
            if written <= 0:
                raise RuntimeError(
                    f"MSI HID write returned non-positive byte count ({written}) "
                    f"for zone {zone_index}."
                )
            self._last_zone_colors[zone_index] = clamped_color

    def reset_cache(self) -> None:
        self._last_zone_colors.clear()

    def reconnect(self) -> bool:
        self.reset_cache()
        self._active_hid_path = self._resolve_best_hid_path()
        return True

    def _write_packet(self, *, packet: list[int], hid_path: str | None) -> int:
        return self._writer(
            report_bytes=packet,
            hid_path=hid_path,
            vendor_id=self._config.vendor_id,
            product_id=self._config.product_id,
            write_method=self._config.write_method,
        )

    def _resolve_best_hid_path(self) -> str | None:
        if self._config.hid_path is None:
            return None
        try:
            raw_devices = self._device_enumerator()
        except Exception:
            return self._active_hid_path or self._config.hid_path

        if not isinstance(raw_devices, list):
            return self._active_hid_path or self._config.hid_path

        matching_paths: list[str] = []
        for device in raw_devices:
            path = str(getattr(device, "path", "")).strip()
            vendor_id = int(getattr(device, "vendor_id", -1))
            product_id = int(getattr(device, "product_id", -1))
            if (
                path
                and vendor_id == self._config.vendor_id
                and product_id == self._config.product_id
            ):
                matching_paths.append(path)

        if not matching_paths:
            return None
        if self._config.hid_path in matching_paths:
            return self._config.hid_path
        return matching_paths[0]


def _build_packet(
    *,
    template: str,
    zone_index: int,
    color: RgbColor,
    report_id: int,
    pad_length: int,
) -> list[int]:
    replacements = {
        "{zone}": zone_index,
        "{r}": color.r,
        "{g}": color.g,
        "{b}": color.b,
        "{report_id}": report_id,
    }
    tokens = _tokenize_template(template)
    if not tokens:
        raise ValueError("packet template produced no bytes")

    values: list[int] = []
    for raw_token in tokens:
        token = raw_token.lower()
        if token in replacements:
            value = replacements[token]
        else:
            value = _parse_byte_token(raw_token)
        if value < 0 or value > 255:
            raise ValueError(f"token '{raw_token}' resolved to byte out of range: {value}")
        values.append(value)

    if len(values) > pad_length:
        raise ValueError(
            f"template byte length {len(values)} exceeds configured pad_length {pad_length}"
        )
    return values + [0] * (pad_length - len(values))


def _tokenize_template(template: str) -> list[str]:
    normalized = template.replace(",", " ")
    return [token for token in normalized.split() if token]


def _parse_byte_token(token: str) -> int:
    if re.fullmatch(r"0x[0-9a-fA-F]{1,2}", token):
        return int(token, 16)
    if re.fullmatch(r"[0-9]{1,3}", token):
        return int(token, 10)
    if re.fullmatch(r"[0-9a-fA-F]{2}", token):
        return int(token, 16)
    raise ValueError(
        f"unrecognized token '{token}'. Use decimal, hex, or placeholders "
        "{zone},{r},{g},{b},{report_id}."
    )
