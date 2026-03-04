from pathlib import Path

import pytest

from keylight.mapping.profile_builder import (
    ZoneProfileBuildConfig,
    build_zone_geometry_profile,
    write_zone_geometry_profile,
)


def test_build_zone_profile_applies_weighted_columns() -> None:
    profile = build_zone_geometry_profile(
        ZoneProfileBuildConfig(
            rows=1,
            columns=3,
            column_weights=[1.0, 2.0, 1.0],
        )
    )

    zones = sorted(profile.zones, key=lambda item: item.zone_index)
    assert zones[0].x0 == 0.0
    assert zones[0].x1 == pytest.approx(0.25)
    assert zones[1].x0 == pytest.approx(0.25)
    assert zones[1].x1 == pytest.approx(0.75)
    assert zones[2].x0 == pytest.approx(0.75)
    assert zones[2].x1 == 1.0


def test_build_zone_profile_supports_serpentine() -> None:
    profile = build_zone_geometry_profile(
        ZoneProfileBuildConfig(
            rows=2,
            columns=3,
            serpentine=True,
        )
    )

    zones = {zone.zone_index: zone for zone in profile.zones}
    assert zones[0].y0 == 0.0
    assert zones[0].x0 == 0.0
    assert zones[2].x0 == pytest.approx(2.0 / 3.0)
    assert zones[3].y0 == 0.5
    assert zones[3].x0 == pytest.approx(2.0 / 3.0)
    assert zones[5].x0 == 0.0


def test_build_zone_profile_validates_row_column_weights_shape() -> None:
    with pytest.raises(ValueError, match="row_column_weights row count"):
        build_zone_geometry_profile(
            ZoneProfileBuildConfig(
                rows=2,
                columns=3,
                row_column_weights=[[1.0, 1.0, 1.0]],
            )
        )


def test_write_zone_geometry_profile_writes_json(tmp_path: Path) -> None:
    profile = build_zone_geometry_profile(
        ZoneProfileBuildConfig(
            rows=2,
            columns=2,
        )
    )

    output_path = write_zone_geometry_profile(profile, tmp_path / "profile.json")

    content = output_path.read_text(encoding="utf-8")
    assert '"version": 1' in content
    assert '"zone_index": 3' in content
