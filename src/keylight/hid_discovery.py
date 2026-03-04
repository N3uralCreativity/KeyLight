from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import sleep
from typing import Protocol

from keylight.drivers.hid_raw import write_output_report
from keylight.models import RgbColor
from keylight.write_zone import build_report_bytes_from_template


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
class DiscoveryTemplate:
    name: str
    template: str


@dataclass(frozen=True, slots=True)
class HidDiscoveryConfig:
    hid_path: str | None
    vendor_id: int | None
    product_id: int | None
    zone_index: int
    color: RgbColor
    write_methods: list[str]
    report_ids: list[int]
    pad_lengths: list[int]
    templates: list[DiscoveryTemplate]
    delay_ms: int = 20
    stop_on_first_success: bool = False

    def validate(self) -> None:
        has_path = bool(self.hid_path)
        has_vid_pid = self.vendor_id is not None and self.product_id is not None
        if not has_path and not has_vid_pid:
            raise ValueError("Provide hid_path or vendor_id/product_id.")
        if self.zone_index < 0:
            raise ValueError("zone_index cannot be negative.")
        if not self.write_methods:
            raise ValueError("write_methods cannot be empty.")
        if not self.report_ids:
            raise ValueError("report_ids cannot be empty.")
        if not self.pad_lengths:
            raise ValueError("pad_lengths cannot be empty.")
        if not self.templates:
            raise ValueError("templates cannot be empty.")
        if any(method not in {"output", "feature"} for method in self.write_methods):
            raise ValueError("write_methods can only include 'output' and 'feature'.")
        if any(report_id < 0 or report_id > 255 for report_id in self.report_ids):
            raise ValueError("report_ids values must be in range 0..255.")
        if any(pad_length <= 0 for pad_length in self.pad_lengths):
            raise ValueError("pad_lengths values must be positive.")
        if self.delay_ms < 0:
            raise ValueError("delay_ms cannot be negative.")


@dataclass(frozen=True, slots=True)
class HidDiscoveryAttempt:
    index: int
    timestamp_utc: str
    template_name: str
    write_method: str
    report_id: int
    pad_length: int
    success: bool
    bytes_written: int
    report_bytes: list[int] | None
    error: str | None


@dataclass(frozen=True, slots=True)
class HidDiscoveryReport:
    started_at_utc: str
    finished_at_utc: str
    hid_path: str | None
    vendor_id: int | None
    product_id: int | None
    zone_index: int
    color: RgbColor
    total_attempts: int
    success_count: int
    attempts: list[HidDiscoveryAttempt]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def run_hid_discovery(
    config: HidDiscoveryConfig,
    writer: HidWriter = write_output_report,
) -> HidDiscoveryReport:
    config.validate()
    started_at_utc = _now_utc_iso()
    attempts: list[HidDiscoveryAttempt] = []
    attempt_index = 0
    success_count = 0
    should_stop = False

    for template in config.templates:
        for write_method in config.write_methods:
            for report_id in config.report_ids:
                for pad_length in config.pad_lengths:
                    attempt_index += 1
                    attempt = _run_single_attempt(
                        index=attempt_index,
                        template=template,
                        write_method=write_method,
                        report_id=report_id,
                        pad_length=pad_length,
                        config=config,
                        writer=writer,
                    )
                    attempts.append(attempt)
                    if attempt.success:
                        success_count += 1
                        if config.stop_on_first_success:
                            should_stop = True
                    if should_stop:
                        break
                    if config.delay_ms > 0:
                        sleep(config.delay_ms / 1000.0)
                if should_stop:
                    break
            if should_stop:
                break
        if should_stop:
            break

    finished_at_utc = _now_utc_iso()
    return HidDiscoveryReport(
        started_at_utc=started_at_utc,
        finished_at_utc=finished_at_utc,
        hid_path=config.hid_path,
        vendor_id=config.vendor_id,
        product_id=config.product_id,
        zone_index=config.zone_index,
        color=config.color.clamped(),
        total_attempts=len(attempts),
        success_count=success_count,
        attempts=attempts,
    )


def write_hid_discovery_report(report: HidDiscoveryReport, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return output_path


def _run_single_attempt(
    *,
    index: int,
    template: DiscoveryTemplate,
    write_method: str,
    report_id: int,
    pad_length: int,
    config: HidDiscoveryConfig,
    writer: HidWriter,
) -> HidDiscoveryAttempt:
    timestamp = _now_utc_iso()
    clamped_color = config.color.clamped()

    try:
        report_bytes = build_report_bytes_from_template(
            template=template.template,
            zone_index=config.zone_index,
            color=clamped_color,
            report_id=report_id,
        )
    except ValueError as error:
        return HidDiscoveryAttempt(
            index=index,
            timestamp_utc=timestamp,
            template_name=template.name,
            write_method=write_method,
            report_id=report_id,
            pad_length=pad_length,
            success=False,
            bytes_written=0,
            report_bytes=None,
            error=f"Template parse error: {error}",
        )

    if len(report_bytes) > pad_length:
        return HidDiscoveryAttempt(
            index=index,
            timestamp_utc=timestamp,
            template_name=template.name,
            write_method=write_method,
            report_id=report_id,
            pad_length=pad_length,
            success=False,
            bytes_written=0,
            report_bytes=report_bytes,
            error=f"Template bytes length {len(report_bytes)} exceeds pad length {pad_length}.",
        )

    padded = report_bytes + [0] * (pad_length - len(report_bytes))
    try:
        bytes_written = writer(
            report_bytes=padded,
            hid_path=config.hid_path,
            vendor_id=config.vendor_id,
            product_id=config.product_id,
            write_method=write_method,
        )
    except (RuntimeError, OSError, ValueError) as error:
        return HidDiscoveryAttempt(
            index=index,
            timestamp_utc=timestamp,
            template_name=template.name,
            write_method=write_method,
            report_id=report_id,
            pad_length=pad_length,
            success=False,
            bytes_written=0,
            report_bytes=padded,
            error=str(error),
        )

    return HidDiscoveryAttempt(
        index=index,
        timestamp_utc=timestamp,
        template_name=template.name,
        write_method=write_method,
        report_id=report_id,
        pad_length=pad_length,
        success=True,
        bytes_written=bytes_written,
        report_bytes=padded,
        error=None,
    )


def _now_utc_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()

