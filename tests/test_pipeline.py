from keylight.models import CapturedFrame, RgbColor, ZoneColor
from keylight.pipeline import KeyLightPipeline, PipelineConfig


class _StubCapturer:
    def capture_frame(self) -> CapturedFrame:
        return CapturedFrame(width=1, height=1, pixels=[[RgbColor(1, 2, 3)]])


class _StubMapper:
    def map_frame(self, frame: CapturedFrame) -> list[ZoneColor]:
        assert frame.width == 1
        return [ZoneColor(zone_index=0, color=RgbColor(10, 20, 30))]


class _StubDriver:
    def __init__(self) -> None:
        self.calls = 0
        self.last: list[ZoneColor] = []

    def apply_zone_colors(self, zones: list[ZoneColor]) -> None:
        self.calls += 1
        self.last = zones


def test_pipeline_runs_expected_iterations() -> None:
    driver = _StubDriver()
    pipeline = KeyLightPipeline(
        capturer=_StubCapturer(),
        mapper=_StubMapper(),
        driver=driver,
        config=PipelineConfig(fps=120, iterations=3),
    )

    pipeline.run()

    assert driver.calls == 3
    assert len(driver.last) == 1
    assert driver.last[0].color == RgbColor(10, 20, 30)

