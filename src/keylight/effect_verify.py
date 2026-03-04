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
class EffectCandidate:
    name: str
    template: str
    write_method: str
    report_id: int
    pad_length: int


@dataclass(frozen=True, slots=True)
class EffectVerificationConfig:
    hid_path: str | None
    vendor_id: int | None
    product_id: int | None
    zone_sequence: list[int]
    color_sequence: list[RgbColor]
    candidates: list[EffectCandidate]
    step_delay_ms: int = 1200
    repeat: int = 1
    max_steps: int | None = None

    def validate(self) -> None:
        has_path = bool(self.hid_path)
        has_vid_pid = self.vendor_id is not None and self.product_id is not None
        if not has_path and not has_vid_pid:
            raise ValueError("Provide hid_path or vendor_id/product_id.")
        if not self.zone_sequence:
            raise ValueError("zone_sequence cannot be empty.")
        if any(zone < 0 for zone in self.zone_sequence):
            raise ValueError("zone_sequence values must be >= 0.")
        if not self.color_sequence:
            raise ValueError("color_sequence cannot be empty.")
        if not self.candidates:
            raise ValueError("candidates cannot be empty.")
        if self.step_delay_ms < 0:
            raise ValueError("step_delay_ms cannot be negative.")
        if self.repeat <= 0:
            raise ValueError("repeat must be positive.")
        if self.max_steps is not None and self.max_steps <= 0:
            raise ValueError("max_steps must be positive when provided.")
        for candidate in self.candidates:
            if candidate.write_method not in {"output", "feature"}:
                raise ValueError(
                    "candidate "
                    f"'{candidate.name}' has invalid write_method '{candidate.write_method}'"
                )
            if candidate.report_id < 0 or candidate.report_id > 255:
                raise ValueError(f"candidate '{candidate.name}' report_id must be in range 0..255.")
            if candidate.pad_length <= 0:
                raise ValueError(f"candidate '{candidate.name}' pad_length must be positive.")


@dataclass(frozen=True, slots=True)
class EffectVerificationStep:
    step_index: int
    timestamp_utc: str
    candidate_name: str
    write_method: str
    report_id: int
    pad_length: int
    zone_index: int
    color: RgbColor
    success: bool
    bytes_written: int
    report_bytes: list[int] | None
    error: str | None


@dataclass(frozen=True, slots=True)
class EffectVerificationReport:
    started_at_utc: str
    finished_at_utc: str
    hid_path: str | None
    vendor_id: int | None
    product_id: int | None
    total_steps: int
    success_count: int
    steps: list[EffectVerificationStep]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def default_accepted_candidates(pad_length: int = 64) -> list[EffectCandidate]:
    templates = [
        ("base", "{report_id} {zone} {r} {g} {b}"),
        ("aa-prefix", "{report_id} 0xAA {zone} {r} {g} {b}"),
        ("51-prefix", "{report_id} 0x51 {zone} {r} {g} {b}"),
        ("1b-prefix", "{report_id} 0x1B {zone} {r} {g} {b}"),
    ]
    candidates: list[EffectCandidate] = []
    for template_name, template_value in templates:
        candidates.extend(
            [
                EffectCandidate(
                    name=f"{template_name}-out-rid1",
                    template=template_value,
                    write_method="output",
                    report_id=1,
                    pad_length=pad_length,
                ),
                EffectCandidate(
                    name=f"{template_name}-out-rid3",
                    template=template_value,
                    write_method="output",
                    report_id=3,
                    pad_length=pad_length,
                ),
                EffectCandidate(
                    name=f"{template_name}-feat-rid1",
                    template=template_value,
                    write_method="feature",
                    report_id=1,
                    pad_length=pad_length,
                ),
                EffectCandidate(
                    name=f"{template_name}-feat-rid2",
                    template=template_value,
                    write_method="feature",
                    report_id=2,
                    pad_length=pad_length,
                ),
            ]
        )
    return candidates


def run_effect_verification(
    config: EffectVerificationConfig,
    *,
    writer: HidWriter = write_output_report,
    sleeper: Callable[[float], None] = sleep,
    on_step: Callable[[EffectVerificationStep], None] | None = None,
) -> EffectVerificationReport:
    config.validate()
    started_at_utc = _now_utc_iso()
    steps: list[EffectVerificationStep] = []
    success_count = 0
    emitted_steps = 0

    for _ in range(config.repeat):
        for candidate in config.candidates:
            if config.max_steps is not None and emitted_steps >= config.max_steps:
                break

            zone_index = config.zone_sequence[emitted_steps % len(config.zone_sequence)]
            color = config.color_sequence[emitted_steps % len(config.color_sequence)].clamped()
            step = _run_single_step(
                step_index=emitted_steps + 1,
                candidate=candidate,
                zone_index=zone_index,
                color=color,
                hid_path=config.hid_path,
                vendor_id=config.vendor_id,
                product_id=config.product_id,
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
    return EffectVerificationReport(
        started_at_utc=started_at_utc,
        finished_at_utc=finished_at_utc,
        hid_path=config.hid_path,
        vendor_id=config.vendor_id,
        product_id=config.product_id,
        total_steps=len(steps),
        success_count=success_count,
        steps=steps,
    )


def write_effect_verification_report(
    report: EffectVerificationReport,
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return output_path


def default_color_sequence() -> list[RgbColor]:
    return [
        RgbColor(255, 0, 0),
        RgbColor(0, 255, 0),
        RgbColor(0, 0, 255),
        RgbColor(255, 255, 0),
        RgbColor(255, 0, 255),
        RgbColor(0, 255, 255),
        RgbColor(255, 255, 255),
        RgbColor(255, 128, 0),
    ]


def _run_single_step(
    *,
    step_index: int,
    candidate: EffectCandidate,
    zone_index: int,
    color: RgbColor,
    hid_path: str | None,
    vendor_id: int | None,
    product_id: int | None,
    writer: HidWriter,
) -> EffectVerificationStep:
    timestamp = _now_utc_iso()
    try:
        packet = build_report_bytes_from_template(
            template=candidate.template,
            zone_index=zone_index,
            color=color,
            report_id=candidate.report_id,
        )
    except ValueError as error:
        return EffectVerificationStep(
            step_index=step_index,
            timestamp_utc=timestamp,
            candidate_name=candidate.name,
            write_method=candidate.write_method,
            report_id=candidate.report_id,
            pad_length=candidate.pad_length,
            zone_index=zone_index,
            color=color,
            success=False,
            bytes_written=0,
            report_bytes=None,
            error=f"Template parse error: {error}",
        )

    if len(packet) > candidate.pad_length:
        return EffectVerificationStep(
            step_index=step_index,
            timestamp_utc=timestamp,
            candidate_name=candidate.name,
            write_method=candidate.write_method,
            report_id=candidate.report_id,
            pad_length=candidate.pad_length,
            zone_index=zone_index,
            color=color,
            success=False,
            bytes_written=0,
            report_bytes=packet,
            error=f"Template length {len(packet)} exceeds pad_length {candidate.pad_length}.",
        )

    padded_packet = packet + [0] * (candidate.pad_length - len(packet))
    try:
        bytes_written = writer(
            report_bytes=padded_packet,
            hid_path=hid_path,
            vendor_id=vendor_id,
            product_id=product_id,
            write_method=candidate.write_method,
        )
    except (RuntimeError, OSError, ValueError) as error:
        return EffectVerificationStep(
            step_index=step_index,
            timestamp_utc=timestamp,
            candidate_name=candidate.name,
            write_method=candidate.write_method,
            report_id=candidate.report_id,
            pad_length=candidate.pad_length,
            zone_index=zone_index,
            color=color,
            success=False,
            bytes_written=0,
            report_bytes=padded_packet,
            error=str(error),
        )

    return EffectVerificationStep(
        step_index=step_index,
        timestamp_utc=timestamp,
        candidate_name=candidate.name,
        write_method=candidate.write_method,
        report_id=candidate.report_id,
        pad_length=candidate.pad_length,
        zone_index=zone_index,
        color=color,
        success=True,
        bytes_written=bytes_written,
        report_bytes=padded_packet,
        error=None,
    )


def _now_utc_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()
