from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import sleep

from keylight.contracts import KeyboardLightingDriver
from keylight.models import RgbColor, ZoneColor


@dataclass(frozen=True, slots=True)
class SweepConfig:
    zone_count: int = 24
    loops: int = 1
    step_delay_ms: int = 350
    reverse: bool = False
    active_color: RgbColor = RgbColor(255, 0, 0)
    inactive_color: RgbColor = RgbColor(0, 0, 0)

    def validate(self) -> None:
        if self.zone_count <= 0:
            raise ValueError("zone_count must be positive")
        if self.loops <= 0:
            raise ValueError("loops must be positive")
        if self.step_delay_ms < 0:
            raise ValueError("step_delay_ms cannot be negative")


@dataclass(frozen=True, slots=True)
class SweepStep:
    loop_index: int
    zone_index: int
    timestamp_utc: str


@dataclass(frozen=True, slots=True)
class SweepReport:
    started_at_utc: str
    finished_at_utc: str
    config: SweepConfig
    steps: list[SweepStep]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ZoneSweeper:
    def __init__(
        self,
        driver: KeyboardLightingDriver,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self._driver = driver
        self._sleep = sleeper

    def run(self, config: SweepConfig) -> SweepReport:
        config.validate()
        started_at_utc = _now_utc_iso()
        steps: list[SweepStep] = []

        indexes = list(range(config.zone_count))
        if config.reverse:
            indexes = list(reversed(indexes))

        for loop_index in range(config.loops):
            for zone_index in indexes:
                payload = build_zone_payload(
                    zone_count=config.zone_count,
                    active_zone_index=zone_index,
                    active_color=config.active_color,
                    inactive_color=config.inactive_color,
                )
                self._driver.apply_zone_colors(payload)
                steps.append(
                    SweepStep(
                        loop_index=loop_index,
                        zone_index=zone_index,
                        timestamp_utc=_now_utc_iso(),
                    )
                )
                if config.step_delay_ms > 0:
                    self._sleep(config.step_delay_ms / 1000.0)

        clear_payload = [
            ZoneColor(zone_index=index, color=config.inactive_color.clamped())
            for index in range(config.zone_count)
        ]
        self._driver.apply_zone_colors(clear_payload)

        finished_at_utc = _now_utc_iso()
        return SweepReport(
            started_at_utc=started_at_utc,
            finished_at_utc=finished_at_utc,
            config=config,
            steps=steps,
        )


def write_sweep_report(report: SweepReport, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return output_path


def build_zone_payload(
    *,
    zone_count: int,
    active_zone_index: int,
    active_color: RgbColor,
    inactive_color: RgbColor,
) -> list[ZoneColor]:
    if active_zone_index < 0 or active_zone_index >= zone_count:
        raise ValueError("active_zone_index is outside zone_count")

    active = active_color.clamped()
    inactive = inactive_color.clamped()
    payload: list[ZoneColor] = []
    for zone_index in range(zone_count):
        color = active if zone_index == active_zone_index else inactive
        payload.append(ZoneColor(zone_index=zone_index, color=color))
    return payload


def _now_utc_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()
