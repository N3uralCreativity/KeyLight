from __future__ import annotations

from dataclasses import dataclass

from keylight.models import CapturedFrame, RgbColor, ZoneColor


@dataclass(frozen=True, slots=True)
class GridLayout:
    rows: int
    columns: int

    @property
    def zone_count(self) -> int:
        return self.rows * self.columns


class GridZoneMapper:
    """Maps a frame to zone colors using a simple rectangular grid."""

    def __init__(self, layout: GridLayout) -> None:
        if layout.rows <= 0 or layout.columns <= 0:
            raise ValueError("rows and columns must be positive")
        self._layout = layout

    @property
    def zone_count(self) -> int:
        return self._layout.zone_count

    def map_frame(self, frame: CapturedFrame) -> list[ZoneColor]:
        if frame.width <= 0 or frame.height <= 0:
            raise ValueError("frame dimensions must be positive")

        zone_colors: list[ZoneColor] = []
        zone_index = 0

        for row in range(self._layout.rows):
            y_start = row * frame.height // self._layout.rows
            y_end = (row + 1) * frame.height // self._layout.rows

            for column in range(self._layout.columns):
                x_start = column * frame.width // self._layout.columns
                x_end = (column + 1) * frame.width // self._layout.columns

                sampled: list[RgbColor] = []
                for y in range(y_start, y_end):
                    sampled.extend(frame.pixels[y][x_start:x_end])

                zone_color = ZoneColor(zone_index=zone_index, color=RgbColor.average(sampled))
                zone_colors.append(zone_color)
                zone_index += 1

        return zone_colors
