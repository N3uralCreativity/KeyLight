from keylight.interactive_calibration import capture_observed_order_interactive
from keylight.models import RgbColor, ZoneColor


class _TrackingDriver:
    def __init__(self) -> None:
        self.calls: list[list[ZoneColor]] = []

    def apply_zone_colors(self, zones: list[ZoneColor]) -> None:
        self.calls.append(zones.copy())


def test_capture_observed_order_interactive_collects_unique_indexes() -> None:
    driver = _TrackingDriver()
    responses = iter(["2", "0", "3", "1"])
    messages: list[str] = []

    observed = capture_observed_order_interactive(
        driver=driver,
        zone_count=4,
        active_color=RgbColor(255, 0, 0),
        inactive_color=RgbColor(0, 0, 0),
        prompt_fn=lambda _: next(responses),
        print_fn=messages.append,
    )

    assert observed == [2, 0, 3, 1]
    assert len(driver.calls) == 5
    assert all(zone.color == RgbColor(0, 0, 0) for zone in driver.calls[-1])


def test_capture_observed_order_interactive_rejects_duplicate_and_repeat() -> None:
    driver = _TrackingDriver()
    responses = iter(["1", "1", "r", "0"])
    messages: list[str] = []

    observed = capture_observed_order_interactive(
        driver=driver,
        zone_count=2,
        active_color=RgbColor(255, 0, 0),
        inactive_color=RgbColor(0, 0, 0),
        prompt_fn=lambda _: next(responses),
        print_fn=messages.append,
    )

    assert observed == [1, 0]
    assert any("already assigned" in message for message in messages)
    assert any("Repeating logical zone 1" in message for message in messages)
