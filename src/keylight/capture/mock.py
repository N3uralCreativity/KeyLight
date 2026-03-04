from __future__ import annotations

from keylight.models import CapturedFrame, RgbColor


class MockGradientCapturer:
    """Synthetic frame source for deterministic local testing."""

    def __init__(self, width: int = 120, height: int = 20) -> None:
        self._width = width
        self._height = height

    def capture_frame(self) -> CapturedFrame:
        pixels: list[list[RgbColor]] = []
        for y in range(self._height):
            row: list[RgbColor] = []
            for x in range(self._width):
                red = int((x / max(self._width - 1, 1)) * 255)
                green = int((y / max(self._height - 1, 1)) * 255)
                blue = int((((x + y) / max(self._width + self._height - 2, 1))) * 255)
                row.append(RgbColor(red, green, blue))
            pixels.append(row)
        return CapturedFrame(width=self._width, height=self._height, pixels=pixels)

