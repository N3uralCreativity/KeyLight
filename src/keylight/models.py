from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RgbColor:
    r: int
    g: int
    b: int

    def clamped(self) -> RgbColor:
        return RgbColor(
            r=max(0, min(self.r, 255)),
            g=max(0, min(self.g, 255)),
            b=max(0, min(self.b, 255)),
        )

    @staticmethod
    def black() -> RgbColor:
        return RgbColor(0, 0, 0)

    @staticmethod
    def average(colors: list[RgbColor]) -> RgbColor:
        if not colors:
            return RgbColor.black()
        return RgbColor(
            r=sum(color.r for color in colors) // len(colors),
            g=sum(color.g for color in colors) // len(colors),
            b=sum(color.b for color in colors) // len(colors),
        )


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    width: int
    height: int
    pixels: list[list[RgbColor]]


@dataclass(frozen=True, slots=True)
class ZoneColor:
    zone_index: int
    color: RgbColor
