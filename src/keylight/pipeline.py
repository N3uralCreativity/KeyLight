from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter, sleep

from keylight.contracts import KeyboardLightingDriver, ScreenCapturer, ZoneMapper


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    fps: int = 30
    iterations: int = 1

    def frame_interval_seconds(self) -> float:
        if self.fps <= 0:
            raise ValueError("fps must be positive")
        return 1.0 / self.fps


class KeyLightPipeline:
    def __init__(
        self,
        capturer: ScreenCapturer,
        mapper: ZoneMapper,
        driver: KeyboardLightingDriver,
        config: PipelineConfig,
    ) -> None:
        self._capturer = capturer
        self._mapper = mapper
        self._driver = driver
        self._config = config

    def run(self) -> None:
        interval = self._config.frame_interval_seconds()

        for _ in range(self._config.iterations):
            start = perf_counter()
            frame = self._capturer.capture_frame()
            zones = self._mapper.map_frame(frame)
            self._driver.apply_zone_colors(zones)

            elapsed = perf_counter() - start
            remaining = interval - elapsed
            if remaining > 0:
                sleep(remaining)

