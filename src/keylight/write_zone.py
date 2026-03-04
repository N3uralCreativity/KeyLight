from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from keylight.drivers.hid_raw import write_output_report
from keylight.drivers.msi_mystic_hid import MsiMysticHidConfig, MsiMysticHidDriver
from keylight.drivers.simulated import SimulatedKeyboardDriver
from keylight.models import RgbColor, ZoneColor


@dataclass(frozen=True, slots=True)
class WriteZoneConfig:
    backend: str
    zone_index: int
    zone_count: int
    color: RgbColor
    packet_template: str | None = None
    report_id: int = 0
    pad_to: int | None = None
    write_method: str = "output"
    hid_path: str | None = None
    vendor_id: int | None = None
    product_id: int | None = None

    def validate(self) -> None:
        if self.zone_count <= 0:
            raise ValueError("zone_count must be positive")
        if self.zone_index < 0 or self.zone_index >= self.zone_count:
            raise ValueError("zone_index must be in range 0..zone_count-1")
        if self.report_id < 0 or self.report_id > 255:
            raise ValueError("report_id must be in range 0..255")
        if self.write_method not in {"output", "feature"}:
            raise ValueError("write_method must be 'output' or 'feature'")
        if self.pad_to is not None and self.pad_to <= 0:
            raise ValueError("pad_to must be positive when provided")
        if self.backend not in {"simulated", "hid-raw", "msi-mystic-hid"}:
            raise ValueError(f"Unsupported backend '{self.backend}'")
        if self.backend == "hid-raw":
            if not self.packet_template:
                raise ValueError("packet_template is required for hid-raw backend")
            has_path = bool(self.hid_path)
            has_vid_pid = self.vendor_id is not None and self.product_id is not None
            if not has_path and not has_vid_pid:
                raise ValueError(
                    "hid-raw backend requires --hid-path or both --vendor-id and --product-id"
                )


@dataclass(frozen=True, slots=True)
class WriteZoneReport:
    timestamp_utc: str
    backend: str
    zone_index: int
    zone_count: int
    color: RgbColor
    success: bool
    bytes_written: int
    report_bytes: list[int] | None
    write_method: str
    pad_to: int | None
    hid_path: str | None
    vendor_id: int | None
    product_id: int | None
    error: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def execute_write_zone(config: WriteZoneConfig) -> WriteZoneReport:
    config.validate()
    color = config.color.clamped()
    timestamp = _now_utc_iso()

    if config.backend == "simulated":
        payload = build_single_zone_payload(
            zone_count=config.zone_count,
            zone_index=config.zone_index,
            color=color,
        )
        simulated_driver = SimulatedKeyboardDriver()
        simulated_driver.apply_zone_colors(payload)
        return WriteZoneReport(
            timestamp_utc=timestamp,
            backend=config.backend,
            zone_index=config.zone_index,
            zone_count=config.zone_count,
            color=color,
            success=True,
            bytes_written=0,
            report_bytes=None,
            write_method="none",
            pad_to=None,
            hid_path=None,
            vendor_id=None,
            product_id=None,
            error=None,
        )

    if config.backend == "msi-mystic-hid":
        msi_driver = MsiMysticHidDriver(
            config=MsiMysticHidConfig(
                hid_path=config.hid_path,
                vendor_id=config.vendor_id if config.vendor_id is not None else 0x1462,
                product_id=config.product_id if config.product_id is not None else 0x1603,
                packet_template=config.packet_template or "{report_id} {zone} {r} {g} {b}",
                report_id=config.report_id,
                write_method=config.write_method,
                pad_length=config.pad_to if config.pad_to is not None else 64,
                zone_count=config.zone_count,
            )
        )
        payload = build_single_zone_payload(
            zone_count=config.zone_count,
            zone_index=config.zone_index,
            color=color,
        )
        try:
            msi_driver.apply_zone_colors(payload)
        except (RuntimeError, OSError, ValueError) as error:
            return WriteZoneReport(
                timestamp_utc=timestamp,
                backend=config.backend,
                zone_index=config.zone_index,
                zone_count=config.zone_count,
                color=color,
                success=False,
                bytes_written=0,
                report_bytes=None,
                write_method=config.write_method,
                pad_to=config.pad_to,
                hid_path=config.hid_path,
                vendor_id=config.vendor_id,
                product_id=config.product_id,
                error=str(error),
            )
        return WriteZoneReport(
            timestamp_utc=timestamp,
            backend=config.backend,
            zone_index=config.zone_index,
            zone_count=config.zone_count,
            color=color,
            success=True,
            bytes_written=0,
            report_bytes=None,
            write_method=config.write_method,
            pad_to=config.pad_to,
            hid_path=config.hid_path,
            vendor_id=config.vendor_id,
            product_id=config.product_id,
            error=None,
        )

    report_bytes = build_report_bytes_from_template(
        template=config.packet_template or "",
        zone_index=config.zone_index,
        color=color,
        report_id=config.report_id,
    )
    if config.pad_to is not None:
        if len(report_bytes) > config.pad_to:
            return WriteZoneReport(
                timestamp_utc=timestamp,
                backend=config.backend,
                zone_index=config.zone_index,
                zone_count=config.zone_count,
                color=color,
                success=False,
                bytes_written=0,
                report_bytes=report_bytes,
                write_method=config.write_method,
                pad_to=config.pad_to,
                hid_path=config.hid_path,
                vendor_id=config.vendor_id,
                product_id=config.product_id,
                error=f"Packet length {len(report_bytes)} exceeds pad_to {config.pad_to}.",
            )
        report_bytes = report_bytes + [0] * (config.pad_to - len(report_bytes))
    try:
        bytes_written = write_output_report(
            report_bytes=report_bytes,
            hid_path=config.hid_path,
            vendor_id=config.vendor_id,
            product_id=config.product_id,
            write_method=config.write_method,
        )
    except (RuntimeError, OSError, ValueError) as error:
        return WriteZoneReport(
            timestamp_utc=timestamp,
            backend=config.backend,
            zone_index=config.zone_index,
            zone_count=config.zone_count,
            color=color,
            success=False,
            bytes_written=0,
            report_bytes=report_bytes,
            write_method=config.write_method,
            pad_to=config.pad_to,
            hid_path=config.hid_path,
            vendor_id=config.vendor_id,
            product_id=config.product_id,
            error=str(error),
        )

    return WriteZoneReport(
        timestamp_utc=timestamp,
        backend=config.backend,
        zone_index=config.zone_index,
        zone_count=config.zone_count,
        color=color,
        success=True,
        bytes_written=bytes_written,
        report_bytes=report_bytes,
        write_method=config.write_method,
        pad_to=config.pad_to,
        hid_path=config.hid_path,
        vendor_id=config.vendor_id,
        product_id=config.product_id,
        error=None,
    )


def build_single_zone_payload(
    *,
    zone_count: int,
    zone_index: int,
    color: RgbColor,
) -> list[ZoneColor]:
    clamped_color = color.clamped()
    payload: list[ZoneColor] = []
    for index in range(zone_count):
        zone_color = clamped_color if index == zone_index else RgbColor.black()
        payload.append(ZoneColor(zone_index=index, color=zone_color))
    return payload


def build_report_bytes_from_template(
    *,
    template: str,
    zone_index: int,
    color: RgbColor,
    report_id: int,
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
            raise ValueError(f"Token '{raw_token}' resolved to byte out of range: {value}")
        values.append(value)
    return values


def write_write_zone_report(report: WriteZoneReport, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return output_path


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
        f"Unrecognized token '{token}'. Use decimal, hex, or placeholders "
        "{zone},{r},{g},{b},{report_id}."
    )


def _now_utc_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()
