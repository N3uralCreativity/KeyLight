from keylight.models import RgbColor, ZoneColor
from keylight.sweep import SweepConfig, ZoneSweeper, build_zone_payload


class _RecordingDriver:
    def __init__(self) -> None:
        self.calls: list[list[tuple[int, RgbColor]]] = []

    def apply_zone_colors(self, zones: list[ZoneColor]) -> None:
        serialized: list[tuple[int, RgbColor]] = []
        for zone in zones:
            serialized.append((zone.zone_index, zone.color))
        self.calls.append(serialized)


def test_build_zone_payload_marks_single_active_zone() -> None:
    payload = build_zone_payload(
        zone_count=4,
        active_zone_index=2,
        active_color=RgbColor(255, 0, 0),
        inactive_color=RgbColor(0, 0, 0),
    )

    assert len(payload) == 4
    active = [zone for zone in payload if zone.color == RgbColor(255, 0, 0)]
    assert len(active) == 1
    assert active[0].zone_index == 2


def test_zone_sweeper_executes_all_steps_and_clears() -> None:
    driver = _RecordingDriver()
    sweeper = ZoneSweeper(driver=driver, sleeper=lambda _: None)
    config = SweepConfig(zone_count=4, loops=2, step_delay_ms=0)

    report = sweeper.run(config)

    assert len(report.steps) == 8
    assert [step.zone_index for step in report.steps] == [0, 1, 2, 3, 0, 1, 2, 3]
    assert len(driver.calls) == 9
    final_call = driver.calls[-1]
    assert all(color == RgbColor(0, 0, 0) for _, color in final_call)


def test_zone_sweeper_reverse_order() -> None:
    driver = _RecordingDriver()
    sweeper = ZoneSweeper(driver=driver, sleeper=lambda _: None)
    config = SweepConfig(zone_count=4, loops=1, reverse=True, step_delay_ms=0)

    report = sweeper.run(config)

    assert [step.zone_index for step in report.steps] == [3, 2, 1, 0]
