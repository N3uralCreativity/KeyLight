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
    protocol: str = "msi-center-feature-zones"
    global_color_strategy: str = "max-brightness"
    msi_center_brightness: int = 0x64
    msi_center_transition: int = 0x32
    msi_center_profile_slot: int = 0x58
    msi_center_effect_code: int = 0x08

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
        if self.protocol not in {
            "legacy-zone",
            "msi-center-feature-global",
            "msi-center-feature-zones",
        }:
            raise ValueError(
                "protocol must be 'legacy-zone', 'msi-center-feature-global', "
                "or 'msi-center-feature-zones'"
            )
        if self.global_color_strategy not in {"max-brightness", "average"}:
            raise ValueError("global_color_strategy must be 'max-brightness' or 'average'")
        if self.msi_center_brightness < 0 or self.msi_center_brightness > 255:
            raise ValueError("msi_center_brightness must be in range 0..255")
        if self.msi_center_transition < 0 or self.msi_center_transition > 255:
            raise ValueError("msi_center_transition must be in range 0..255")
        if self.msi_center_profile_slot < 0 or self.msi_center_profile_slot > 255:
            raise ValueError("msi_center_profile_slot must be in range 0..255")
        if self.msi_center_effect_code < 0 or self.msi_center_effect_code > 255:
            raise ValueError("msi_center_effect_code must be in range 0..255")


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
        self._last_global_color: RgbColor | None = None

    def apply_zone_colors(self, zones: list[ZoneColor]) -> None:
        for zone in zones:
            zone_index = zone.zone_index
            if zone_index < 0 or zone_index >= self._config.zone_count:
                raise ValueError(
                    f"zone_index {zone_index} is outside configured zone_count "
                    f"{self._config.zone_count}"
                )

        if self._config.protocol == "legacy-zone":
            self._apply_legacy_zone_packets(zones)
            return

        if self._config.protocol == "msi-center-feature-global":
            self._apply_msi_center_global(zones)
            return

        self._apply_msi_center_zone_packets(zones)

    def _apply_legacy_zone_packets(self, zones: list[ZoneColor]) -> None:
        for zone in sorted(zones, key=lambda item: item.zone_index):
            zone_index = zone.zone_index

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
                written = self._write_packet(
                    packet=packet,
                    hid_path=self._active_hid_path,
                    write_method=self._config.write_method,
                )
            except (RuntimeError, OSError) as original_error:
                if self._active_hid_path is None:
                    raise
                try:
                    written = self._write_packet(
                        packet=packet,
                        hid_path=None,
                        write_method=self._config.write_method,
                    )
                except (RuntimeError, OSError):
                    raise original_error from None
                self._active_hid_path = None
            if written <= 0:
                raise RuntimeError(
                    f"MSI HID write returned non-positive byte count ({written}) "
                    f"for zone {zone_index}."
                )
            self._last_zone_colors[zone_index] = clamped_color

    def _apply_msi_center_global(self, zones: list[ZoneColor]) -> None:
        selected = _select_global_color(
            zones=zones,
            strategy=self._config.global_color_strategy,
        )
        if self._last_global_color == selected:
            return

        prep_packet = _build_msi_center_prep_packet(pad_length=self._config.pad_length)
        color_packet = _build_msi_center_color_packet(
            color=selected,
            brightness=self._config.msi_center_brightness,
            transition=self._config.msi_center_transition,
            profile_slot=self._config.msi_center_profile_slot,
            effect_code=self._config.msi_center_effect_code,
            pad_length=self._config.pad_length,
        )
        try:
            self._write_packet(
                packet=prep_packet,
                hid_path=self._active_hid_path,
                write_method="feature",
            )
            written = self._write_packet(
                packet=color_packet,
                hid_path=self._active_hid_path,
                write_method="feature",
            )
        except (RuntimeError, OSError) as original_error:
            if self._active_hid_path is None:
                raise
            try:
                self._write_packet(
                    packet=prep_packet,
                    hid_path=None,
                    write_method="feature",
                )
                written = self._write_packet(
                    packet=color_packet,
                    hid_path=None,
                    write_method="feature",
                )
            except (RuntimeError, OSError):
                raise original_error from None
            self._active_hid_path = None
        if written <= 0:
            raise RuntimeError(
                f"MSI HID write returned non-positive byte count ({written}) for global color."
            )
        self._last_global_color = selected

    def _apply_msi_center_zone_packets(self, zones: list[ZoneColor]) -> None:
        for zone in sorted(zones, key=lambda item: item.zone_index):
            zone_index = zone.zone_index
            clamped_color = zone.color.clamped()
            previous = self._last_zone_colors.get(zone_index)
            if previous == clamped_color:
                continue

            mask_packet = _build_msi_center_zone_mask_packet(
                zone_index=zone_index,
                pad_length=self._config.pad_length,
            )
            color_packet = _build_msi_center_color_packet(
                color=clamped_color,
                brightness=self._config.msi_center_brightness,
                transition=self._config.msi_center_transition,
                profile_slot=self._config.msi_center_profile_slot,
                effect_code=self._config.msi_center_effect_code,
                pad_length=self._config.pad_length,
            )
            try:
                mask_written = self._write_packet(
                    packet=mask_packet,
                    hid_path=self._active_hid_path,
                    write_method="feature",
                )
                color_written = self._write_packet(
                    packet=color_packet,
                    hid_path=self._active_hid_path,
                    write_method="feature",
                )
            except (RuntimeError, OSError) as original_error:
                if self._active_hid_path is None:
                    raise
                try:
                    mask_written = self._write_packet(
                        packet=mask_packet,
                        hid_path=None,
                        write_method="feature",
                    )
                    color_written = self._write_packet(
                        packet=color_packet,
                        hid_path=None,
                        write_method="feature",
                    )
                except (RuntimeError, OSError):
                    raise original_error from None
                self._active_hid_path = None
            if mask_written <= 0 or color_written <= 0:
                raise RuntimeError(
                    "MSI HID write returned non-positive byte count for zone packet pair "
                    f"(zone={zone_index}, mask={mask_written}, color={color_written})."
                )
            self._last_zone_colors[zone_index] = clamped_color

    def reset_cache(self) -> None:
        self._last_zone_colors.clear()
        self._last_global_color = None

    def reconnect(self) -> bool:
        self.reset_cache()
        self._active_hid_path = self._resolve_best_hid_path()
        return True

    def _write_packet(
        self,
        *,
        packet: list[int],
        hid_path: str | None,
        write_method: str,
    ) -> int:
        return self._writer(
            report_bytes=packet,
            hid_path=hid_path,
            vendor_id=self._config.vendor_id,
            product_id=self._config.product_id,
            write_method=write_method,
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


def _build_msi_center_prep_packet(*, pad_length: int) -> list[int]:
    packet = [0x02, 0x01] + [0xFF] * 32
    if len(packet) > pad_length:
        raise ValueError(
            f"msi-center prep packet length {len(packet)} exceeds pad_length {pad_length}"
        )
    return packet + [0] * (pad_length - len(packet))


def _build_msi_center_zone_mask_packet(*, zone_index: int, pad_length: int) -> list[int]:
    if zone_index < 0 or zone_index > 31:
        raise ValueError("msi-center zone mask supports zone_index in range 0..31")
    mask_value = 1 << zone_index
    packet = [
        0x02,
        0x01,
        mask_value & 0xFF,
        (mask_value >> 8) & 0xFF,
        (mask_value >> 16) & 0xFF,
        (mask_value >> 24) & 0xFF,
    ]
    if len(packet) > pad_length:
        raise ValueError(
            f"msi-center zone-mask packet length {len(packet)} exceeds pad_length {pad_length}"
        )
    return packet + [0] * (pad_length - len(packet))


def _build_msi_center_color_packet(
    *,
    color: RgbColor,
    brightness: int,
    transition: int,
    profile_slot: int,
    effect_code: int,
    pad_length: int,
) -> list[int]:
    clamped = color.clamped()
    packet = [
        0x02,
        0x02,
        0x01,
        profile_slot,
        0x02,
        0x00,
        transition,
        effect_code,
        0x01,
        0x01,
        0x00,
        clamped.r,
        clamped.g,
        clamped.b,
        brightness,
        clamped.r,
        clamped.g,
        clamped.b,
    ]
    if len(packet) > pad_length:
        raise ValueError(
            f"msi-center color packet length {len(packet)} exceeds pad_length {pad_length}"
        )
    return packet + [0] * (pad_length - len(packet))


def _select_global_color(*, zones: list[ZoneColor], strategy: str) -> RgbColor:
    if not zones:
        return RgbColor.black()
    clamped_colors = [zone.color.clamped() for zone in zones]
    if strategy == "average":
        return RgbColor.average(clamped_colors)
    return max(clamped_colors, key=lambda color: (color.r + color.g + color.b))


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
