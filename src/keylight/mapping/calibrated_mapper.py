from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from keylight.models import CapturedFrame, RgbColor, ZoneColor


@dataclass(frozen=True, slots=True)
class ZoneRect:
    zone_index: int
    x0: float
    y0: float
    x1: float
    y1: float

    def validate(self) -> None:
        if self.zone_index < 0:
            raise ValueError("zone_index must be non-negative.")
        if self.x0 < 0.0 or self.y0 < 0.0 or self.x1 > 1.0 or self.y1 > 1.0:
            raise ValueError("zone rect coordinates must be normalized in range 0.0..1.0.")
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("zone rect must satisfy x0 < x1 and y0 < y1.")


@dataclass(frozen=True, slots=True)
class ZoneGeometryProfile:
    zones: list[ZoneRect]
    version: int = 1

    @property
    def zone_count(self) -> int:
        return len(self.zones)

    def validate(self) -> None:
        if self.version <= 0:
            raise ValueError("profile version must be positive.")
        if not self.zones:
            raise ValueError("profile must define at least one zone.")

        zone_indexes = [zone.zone_index for zone in self.zones]
        if len(set(zone_indexes)) != len(zone_indexes):
            raise ValueError("profile zone indexes must be unique.")
        expected = list(range(len(zone_indexes)))
        if sorted(zone_indexes) != expected:
            raise ValueError("profile zone indexes must be contiguous 0..N-1.")

        for zone in self.zones:
            zone.validate()

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> ZoneGeometryProfile:
        version_raw = raw.get("version", 1)
        if not isinstance(version_raw, int):
            raise ValueError("profile version must be an integer.")

        zones_raw = raw.get("zones")
        if not isinstance(zones_raw, list):
            raise ValueError("profile 'zones' must be a list.")
        zones: list[ZoneRect] = []
        for item in zones_raw:
            if not isinstance(item, dict):
                raise ValueError("each zone must be an object.")
            zones.append(
                ZoneRect(
                    zone_index=_require_int(item, "zone_index"),
                    x0=_require_number(item, "x0"),
                    y0=_require_number(item, "y0"),
                    x1=_require_number(item, "x1"),
                    y1=_require_number(item, "y1"),
                )
            )

        profile = ZoneGeometryProfile(version=version_raw, zones=zones)
        profile.validate()
        return profile


class CalibratedZoneMapper:
    """Maps frames using calibrated normalized rectangles per zone."""

    def __init__(self, profile: ZoneGeometryProfile) -> None:
        profile.validate()
        self._zones = sorted(profile.zones, key=lambda zone: zone.zone_index)

    @property
    def zone_count(self) -> int:
        return len(self._zones)

    def map_frame(self, frame: CapturedFrame) -> list[ZoneColor]:
        if frame.width <= 0 or frame.height <= 0:
            raise ValueError("frame dimensions must be positive")

        zone_colors: list[ZoneColor] = []
        for zone in self._zones:
            x_start, x_end = _to_pixel_span(zone.x0, zone.x1, frame.width)
            y_start, y_end = _to_pixel_span(zone.y0, zone.y1, frame.height)

            sampled: list[RgbColor] = []
            for y in range(y_start, y_end):
                sampled.extend(frame.pixels[y][x_start:x_end])
            zone_colors.append(
                ZoneColor(
                    zone_index=zone.zone_index,
                    color=RgbColor.average(sampled),
                )
            )
        return zone_colors


def load_zone_geometry_profile(path: Path) -> ZoneGeometryProfile:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("zone geometry profile root must be an object.")
    return ZoneGeometryProfile.from_dict(data)


def _require_int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int):
        raise ValueError(f"zone field '{key}' must be an integer.")
    return value


def _require_number(raw: dict[str, Any], key: str) -> float:
    value = raw.get(key)
    if not isinstance(value, (int, float)):
        raise ValueError(f"zone field '{key}' must be a number.")
    return float(value)


def _to_pixel_span(start: float, end: float, size: int) -> tuple[int, int]:
    start_index = int(start * size)
    end_index = int(end * size)

    if start_index < 0:
        start_index = 0
    if start_index >= size:
        start_index = size - 1
    if end_index <= start_index:
        end_index = start_index + 1
    if end_index > size:
        end_index = size
    return start_index, end_index
