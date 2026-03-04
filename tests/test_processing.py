from keylight.models import RgbColor, ZoneColor
from keylight.processing import (
    ColorProcessingConfig,
    ZoneColorProcessor,
    apply_brightness_cap,
    blend,
)


def test_apply_brightness_cap_scales_channels() -> None:
    zones = [ZoneColor(zone_index=0, color=RgbColor(200, 100, 50))]

    adjusted = apply_brightness_cap(zones, 50)

    assert adjusted[0].color == RgbColor(100, 50, 25)


def test_blend_interpolates_between_colors() -> None:
    result = blend(RgbColor(0, 0, 0), RgbColor(100, 200, 50), 0.5)

    assert result == RgbColor(50, 100, 25)


def test_zone_color_processor_applies_smoothing() -> None:
    processor = ZoneColorProcessor(
        config=ColorProcessingConfig(
            smoothing_enabled=True,
            smoothing_alpha=0.5,
            brightness_max_percent=100,
        )
    )
    first = [ZoneColor(zone_index=0, color=RgbColor(0, 0, 0))]
    second = [ZoneColor(zone_index=0, color=RgbColor(100, 0, 0))]

    processor.process(first)
    output = processor.process(second)

    assert output[0].color == RgbColor(50, 0, 0)
