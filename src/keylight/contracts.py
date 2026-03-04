from __future__ import annotations

from typing import Protocol

from keylight.models import CapturedFrame, ZoneColor


class ScreenCapturer(Protocol):
    def capture_frame(self) -> CapturedFrame: ...


class ZoneMapper(Protocol):
    def map_frame(self, frame: CapturedFrame) -> list[ZoneColor]: ...


class KeyboardLightingDriver(Protocol):
    def apply_zone_colors(self, zones: list[ZoneColor]) -> None: ...

