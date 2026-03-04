from __future__ import annotations

from keylight.models import ZoneColor


class SimulatedKeyboardDriver:
    """In-memory driver useful before real hardware integration."""

    def __init__(self) -> None:
        self.last_zone_colors: list[ZoneColor] = []

    def apply_zone_colors(self, zones: list[ZoneColor]) -> None:
        self.last_zone_colors = zones.copy()

