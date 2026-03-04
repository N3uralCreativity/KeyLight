from __future__ import annotations

from dataclasses import dataclass

from keylight.models import RgbColor, ZoneColor


@dataclass(frozen=True, slots=True)
class ColorProcessingConfig:
    smoothing_enabled: bool = False
    smoothing_alpha: float = 0.25
    brightness_max_percent: int = 100

    def validate(self) -> None:
        if self.smoothing_alpha < 0.0 or self.smoothing_alpha > 1.0:
            raise ValueError("smoothing_alpha must be in range 0.0..1.0")
        if self.brightness_max_percent <= 0 or self.brightness_max_percent > 100:
            raise ValueError("brightness_max_percent must be in range 1..100")


class ZoneColorProcessor:
    def __init__(self, config: ColorProcessingConfig) -> None:
        config.validate()
        self._config = config
        self._previous: dict[int, RgbColor] = {}

    def process(self, zones: list[ZoneColor]) -> list[ZoneColor]:
        brightness_adjusted = apply_brightness_cap(zones, self._config.brightness_max_percent)
        if not self._config.smoothing_enabled:
            self._previous = {zone.zone_index: zone.color for zone in brightness_adjusted}
            return brightness_adjusted

        smoothed: list[ZoneColor] = []
        for zone in brightness_adjusted:
            previous_color = self._previous.get(zone.zone_index, zone.color)
            color = blend(previous_color, zone.color, self._config.smoothing_alpha)
            smoothed.append(ZoneColor(zone_index=zone.zone_index, color=color))
            self._previous[zone.zone_index] = color
        return smoothed


def apply_brightness_cap(zones: list[ZoneColor], max_percent: int) -> list[ZoneColor]:
    if max_percent <= 0 or max_percent > 100:
        raise ValueError("max_percent must be in range 1..100")
    if max_percent == 100:
        return [ZoneColor(zone_index=zone.zone_index, color=zone.color.clamped()) for zone in zones]

    factor = max_percent / 100.0
    adjusted: list[ZoneColor] = []
    for zone in zones:
        color = zone.color.clamped()
        adjusted.append(
            ZoneColor(
                zone_index=zone.zone_index,
                color=RgbColor(
                    r=int(color.r * factor),
                    g=int(color.g * factor),
                    b=int(color.b * factor),
                ),
            )
        )
    return adjusted


def blend(previous: RgbColor, current: RgbColor, alpha: float) -> RgbColor:
    if alpha < 0.0 or alpha > 1.0:
        raise ValueError("alpha must be in range 0.0..1.0")

    prev = previous.clamped()
    curr = current.clamped()
    inverse = 1.0 - alpha
    return RgbColor(
        r=int(prev.r * inverse + curr.r * alpha),
        g=int(prev.g * inverse + curr.g * alpha),
        b=int(prev.b * inverse + curr.b * alpha),
    )

