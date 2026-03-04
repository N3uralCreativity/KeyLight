from keylight.models import RgbColor


def test_clamped_limits_channels_to_byte_range() -> None:
    color = RgbColor(-10, 260, 300)

    assert color.clamped() == RgbColor(0, 255, 255)

