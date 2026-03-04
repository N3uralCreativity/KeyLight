from keylight.mapping.grid_mapper import GridLayout, GridZoneMapper
from keylight.models import CapturedFrame, RgbColor


def test_grid_mapper_produces_expected_zone_colors() -> None:
    frame = CapturedFrame(
        width=4,
        height=2,
        pixels=[
            [RgbColor(10, 0, 0), RgbColor(20, 0, 0), RgbColor(30, 0, 0), RgbColor(40, 0, 0)],
            [RgbColor(50, 0, 0), RgbColor(60, 0, 0), RgbColor(70, 0, 0), RgbColor(80, 0, 0)],
        ],
    )
    mapper = GridZoneMapper(GridLayout(rows=1, columns=2))

    zones = mapper.map_frame(frame)

    assert len(zones) == 2
    assert zones[0].color == RgbColor(35, 0, 0)
    assert zones[1].color == RgbColor(55, 0, 0)


def test_grid_mapper_zone_count_matches_layout() -> None:
    frame = CapturedFrame(
        width=4,
        height=4,
        pixels=[[RgbColor(0, 0, 0) for _ in range(4)] for _ in range(4)],
    )
    mapper = GridZoneMapper(GridLayout(rows=2, columns=2))

    zones = mapper.map_frame(frame)

    assert len(zones) == 4
    assert [zone.zone_index for zone in zones] == [0, 1, 2, 3]

