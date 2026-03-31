import numpy
import pytest

from keylight.audio_input import AudioFrame
from keylight.sound_reactive import (
    SoundReactiveConfig,
    SoundReactiveRenderer,
    format_palette_strings,
    parse_palette_strings,
)


def _frame(samples: numpy.ndarray, *, rate: int = 48_000) -> AudioFrame:
    return AudioFrame(
        samples=samples,
        sample_rate_hz=rate,
        device_id="speaker:Desk Speakers",
        input_kind="output-loopback",
        frame_size=int(samples.shape[0]),
    )


def test_parse_palette_strings_round_trip() -> None:
    palette = parse_palette_strings(["0,80,255", "255,60,60"])

    assert format_palette_strings(palette) == ("0,80,255", "255,60,60")


def test_parse_palette_strings_rejects_short_palette() -> None:
    with pytest.raises(ValueError, match="audio.palette"):
        parse_palette_strings(["255,0,0"])


@pytest.mark.parametrize(
    ("effect", "samples"),
    [
        (
            "spectrum",
            numpy.column_stack(
                [
                    numpy.sin(numpy.linspace(0.0, 20.0, 2048)),
                    numpy.sin(numpy.linspace(0.0, 50.0, 2048)),
                ]
            ),
        ),
        (
            "bass-pulse",
            numpy.column_stack(
                [
                    numpy.sin(numpy.linspace(0.0, 4.0, 2048)) * 0.8,
                    numpy.sin(numpy.linspace(0.0, 4.0, 2048)) * 0.8,
                ]
            ),
        ),
        (
            "waveform",
            numpy.column_stack(
                [
                    numpy.linspace(-1.0, 1.0, 2048),
                    numpy.linspace(1.0, -1.0, 2048),
                ]
            ),
        ),
        (
            "stereo-split",
            numpy.column_stack(
                [
                    numpy.sin(numpy.linspace(0.0, 12.0, 2048)) * 0.9,
                    numpy.sin(numpy.linspace(0.0, 2.0, 2048)) * 0.2,
                ]
            ),
        ),
    ],
)
def test_sound_reactive_renderer_effects_cover_24_zones(
    effect: str,
    samples: numpy.ndarray,
) -> None:
    renderer = SoundReactiveRenderer(
        SoundReactiveConfig(
            rows=2,
            columns=12,
            effect=effect,
        )
    )

    zones = renderer.render(_frame(samples))

    assert len(zones) == 24
    assert zones[0].zone_index == 0
    assert zones[-1].zone_index == 23
    assert any(
        zone.color.r > 0 or zone.color.g > 0 or zone.color.b > 0 for zone in zones
    )


def test_sound_reactive_renderer_mirror_duplicates_columns() -> None:
    renderer = SoundReactiveRenderer(
        SoundReactiveConfig(
            rows=2,
            columns=12,
            effect="spectrum",
            zone_layout="mirror",
        )
    )

    zones = renderer.render(
        _frame(
            numpy.column_stack(
                [
                    numpy.sin(numpy.linspace(0.0, 20.0, 2048)),
                    numpy.sin(numpy.linspace(0.0, 20.0, 2048)),
                ]
            )
        )
    )

    top_row = zones[:12]
    assert top_row[0].color == top_row[-1].color
