import json
from pathlib import Path

import pytest

from keylight.mapping.calibrated_mapper import CalibratedZoneMapper, load_zone_geometry_profile
from keylight.models import CapturedFrame, RgbColor


def test_calibrated_mapper_maps_profile_rectangles(tmp_path: Path) -> None:
    profile_path = tmp_path / "zones.json"
    profile_path.write_text(
        json.dumps(
            {
                "version": 1,
                "zones": [
                    {"zone_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 1.0},
                    {"zone_index": 1, "x0": 0.5, "y0": 0.0, "x1": 1.0, "y1": 1.0},
                ],
            }
        ),
        encoding="utf-8",
    )
    profile = load_zone_geometry_profile(profile_path)
    mapper = CalibratedZoneMapper(profile)
    frame = CapturedFrame(
        width=4,
        height=2,
        pixels=[
            [RgbColor(10, 0, 0), RgbColor(20, 0, 0), RgbColor(30, 0, 0), RgbColor(40, 0, 0)],
            [RgbColor(50, 0, 0), RgbColor(60, 0, 0), RgbColor(70, 0, 0), RgbColor(80, 0, 0)],
        ],
    )

    zones = mapper.map_frame(frame)

    assert mapper.zone_count == 2
    assert [zone.zone_index for zone in zones] == [0, 1]
    assert zones[0].color == RgbColor(35, 0, 0)
    assert zones[1].color == RgbColor(55, 0, 0)


def test_calibrated_mapper_rejects_non_contiguous_zone_indexes(tmp_path: Path) -> None:
    profile_path = tmp_path / "zones.json"
    profile_path.write_text(
        json.dumps(
            {
                "version": 1,
                "zones": [
                    {"zone_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 1.0},
                    {"zone_index": 2, "x0": 0.5, "y0": 0.0, "x1": 1.0, "y1": 1.0},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="contiguous"):
        load_zone_geometry_profile(profile_path)


def test_calibrated_mapper_ensures_single_pixel_sampling_for_tiny_zone(tmp_path: Path) -> None:
    profile_path = tmp_path / "zones.json"
    profile_path.write_text(
        json.dumps(
            {
                "version": 1,
                "zones": [
                    {"zone_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.01, "y1": 0.01},
                ],
            }
        ),
        encoding="utf-8",
    )
    profile = load_zone_geometry_profile(profile_path)
    mapper = CalibratedZoneMapper(profile)
    frame = CapturedFrame(
        width=2,
        height=2,
        pixels=[
            [RgbColor(1, 2, 3), RgbColor(100, 100, 100)],
            [RgbColor(100, 100, 100), RgbColor(100, 100, 100)],
        ],
    )

    zones = mapper.map_frame(frame)

    assert zones[0].color == RgbColor(1, 2, 3)
