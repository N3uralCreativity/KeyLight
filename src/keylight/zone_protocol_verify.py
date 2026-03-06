from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import sleep
from typing import Protocol

from keylight.drivers.hid_raw import write_output_report
from keylight.models import RgbColor


class HidWriter(Protocol):
    def __call__(
        self,
        *,
        report_bytes: list[int],
        hid_path: str | None = None,
        vendor_id: int | None = None,
        product_id: int | None = None,
        write_method: str = "output",
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class ZoneProtocolVerifyConfig:
    hid_path: str | None
    vendor_id: int | None
    product_id: int | None
    zone_sequence: list[int]
    color_sequence: list[RgbColor]
    offsets: list[int]
    step_delay_ms: int = 1200
    repeat: int = 1
    max_steps: int | None = None
    pad_length: int = 64
    brightness: int = 0x64
    transition: int = 0x32
    profile_slot: int = 0x58
    effect_code: int = 0x08

    def validate(self) -> None:
        has_path = bool(self.hid_path)
        has_vid_pid = self.vendor_id is not None and self.product_id is not None
        if not has_path and not has_vid_pid:
            raise ValueError("Provide hid_path or vendor_id/product_id.")
        if not self.zone_sequence:
            raise ValueError("zone_sequence cannot be empty.")
        if any(zone < 0 or zone > 255 for zone in self.zone_sequence):
            raise ValueError("zone_sequence values must be in range 0..255.")
        if not self.color_sequence:
            raise ValueError("color_sequence cannot be empty.")
        if not self.offsets:
            raise ValueError("offsets cannot be empty.")
        if self.pad_length <= 0:
            raise ValueError("pad_length must be positive.")
        if any(offset < 0 or offset >= self.pad_length for offset in self.offsets):
            raise ValueError("offset values must be in range 0..pad_length-1.")
        if self.step_delay_ms < 0:
            raise ValueError("step_delay_ms cannot be negative.")
        if self.repeat <= 0:
            raise ValueError("repeat must be positive.")
        if self.max_steps is not None and self.max_steps <= 0:
            raise ValueError("max_steps must be positive when provided.")
        if self.brightness < 0 or self.brightness > 255:
            raise ValueError("brightness must be in range 0..255.")
        if self.transition < 0 or self.transition > 255:
            raise ValueError("transition must be in range 0..255.")
        if self.profile_slot < 0 or self.profile_slot > 255:
            raise ValueError("profile_slot must be in range 0..255.")
        if self.effect_code < 0 or self.effect_code > 255:
            raise ValueError("effect_code must be in range 0..255.")


@dataclass(frozen=True, slots=True)
class ZoneProtocolVerifyStep:
    step_index: int
    timestamp_utc: str
    offset: int
    zone_index: int
    color: RgbColor
    original_value: int
    injected_value: int
    success: bool
    prep_bytes_written: int
    color_bytes_written: int
    color_packet: list[int] | None
    error: str | None


@dataclass(frozen=True, slots=True)
class ZoneProtocolVerifyReport:
    started_at_utc: str
    finished_at_utc: str
    hid_path: str | None
    vendor_id: int | None
    product_id: int | None
    pad_length: int
    total_steps: int
    success_count: int
    offsets: list[int]
    steps: list[ZoneProtocolVerifyStep]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def default_zone_probe_offsets() -> list[int]:
    return [3, 4, 5, 6, 7, 8, 9, 10, 14, 18, 19, 20, 21, 22, 23, 24]


def run_zone_protocol_verify(
    config: ZoneProtocolVerifyConfig,
    *,
    writer: HidWriter = write_output_report,
    sleeper: Callable[[float], None] = sleep,
    on_step: Callable[[ZoneProtocolVerifyStep], None] | None = None,
) -> ZoneProtocolVerifyReport:
    config.validate()
    started_at_utc = _now_utc_iso()
    steps: list[ZoneProtocolVerifyStep] = []
    success_count = 0
    emitted_steps = 0

    for _ in range(config.repeat):
        for offset in config.offsets:
            if config.max_steps is not None and emitted_steps >= config.max_steps:
                break

            zone_index = config.zone_sequence[emitted_steps % len(config.zone_sequence)]
            color = config.color_sequence[emitted_steps % len(config.color_sequence)].clamped()
            step = _run_single_step(
                step_index=emitted_steps + 1,
                offset=offset,
                zone_index=zone_index,
                color=color,
                config=config,
                writer=writer,
            )
            steps.append(step)
            emitted_steps += 1

            if step.success:
                success_count += 1
            if on_step is not None:
                on_step(step)
            if config.step_delay_ms > 0:
                sleeper(config.step_delay_ms / 1000.0)

        if config.max_steps is not None and emitted_steps >= config.max_steps:
            break

    finished_at_utc = _now_utc_iso()
    return ZoneProtocolVerifyReport(
        started_at_utc=started_at_utc,
        finished_at_utc=finished_at_utc,
        hid_path=config.hid_path,
        vendor_id=config.vendor_id,
        product_id=config.product_id,
        pad_length=config.pad_length,
        total_steps=len(steps),
        success_count=success_count,
        offsets=list(config.offsets),
        steps=steps,
    )


def write_zone_protocol_verify_report(
    report: ZoneProtocolVerifyReport,
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return output_path


def _run_single_step(
    *,
    step_index: int,
    offset: int,
    zone_index: int,
    color: RgbColor,
    config: ZoneProtocolVerifyConfig,
    writer: HidWriter,
) -> ZoneProtocolVerifyStep:
    timestamp = _now_utc_iso()
    prep_packet = _build_prep_packet(pad_length=config.pad_length)
    color_packet = _build_color_packet(
        color=color,
        brightness=config.brightness,
        transition=config.transition,
        profile_slot=config.profile_slot,
        effect_code=config.effect_code,
        pad_length=config.pad_length,
    )
    original_value = color_packet[offset]
    color_packet[offset] = zone_index

    try:
        prep_written = writer(
            report_bytes=prep_packet,
            hid_path=config.hid_path,
            vendor_id=config.vendor_id,
            product_id=config.product_id,
            write_method="feature",
        )
        color_written = writer(
            report_bytes=color_packet,
            hid_path=config.hid_path,
            vendor_id=config.vendor_id,
            product_id=config.product_id,
            write_method="feature",
        )
    except (RuntimeError, OSError, ValueError) as error:
        return ZoneProtocolVerifyStep(
            step_index=step_index,
            timestamp_utc=timestamp,
            offset=offset,
            zone_index=zone_index,
            color=color,
            original_value=original_value,
            injected_value=zone_index,
            success=False,
            prep_bytes_written=0,
            color_bytes_written=0,
            color_packet=color_packet,
            error=str(error),
        )

    return ZoneProtocolVerifyStep(
        step_index=step_index,
        timestamp_utc=timestamp,
        offset=offset,
        zone_index=zone_index,
        color=color,
        original_value=original_value,
        injected_value=zone_index,
        success=prep_written > 0 and color_written > 0,
        prep_bytes_written=prep_written,
        color_bytes_written=color_written,
        color_packet=color_packet,
        error=None,
    )


def _build_prep_packet(*, pad_length: int) -> list[int]:
    packet = [0x02, 0x01] + [0xFF] * 32
    if len(packet) > pad_length:
        raise ValueError(f"prep packet length {len(packet)} exceeds pad_length {pad_length}")
    return packet + [0] * (pad_length - len(packet))


def _build_color_packet(
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
        raise ValueError(f"color packet length {len(packet)} exceeds pad_length {pad_length}")
    return packet + [0] * (pad_length - len(packet))


def _now_utc_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()

