from __future__ import annotations

from collections.abc import Callable

from keylight.contracts import KeyboardLightingDriver
from keylight.models import RgbColor, ZoneColor

PromptFn = Callable[[str], str]
PrintFn = Callable[[str], None]


def capture_observed_order_interactive(
    *,
    driver: KeyboardLightingDriver,
    zone_count: int,
    active_color: RgbColor,
    inactive_color: RgbColor,
    prompt_fn: PromptFn,
    print_fn: PrintFn,
) -> list[int]:
    if zone_count <= 0:
        raise ValueError("zone_count must be positive.")

    observed: list[int] = []
    used: set[int] = set()

    for logical_index in range(zone_count):
        while True:
            _apply_single_active_zone(
                driver=driver,
                zone_count=zone_count,
                active_index=logical_index,
                active_color=active_color,
                inactive_color=inactive_color,
            )
            response = prompt_fn(
                f"logical zone {logical_index}: enter observed hardware index "
                f"(0..{zone_count - 1}) or 'r' to repeat: "
            ).strip()

            if response.lower() == "r":
                print_fn(f"Repeating logical zone {logical_index}.")
                continue

            try:
                hardware_index = int(response, 10)
            except ValueError:
                print_fn(f"Invalid input '{response}'. Enter an integer or 'r'.")
                continue

            if hardware_index < 0 or hardware_index >= zone_count:
                print_fn(f"Value {hardware_index} is outside 0..{zone_count - 1}.")
                continue
            if hardware_index in used:
                print_fn(f"Value {hardware_index} is already assigned; enter a unique index.")
                continue

            observed.append(hardware_index)
            used.add(hardware_index)
            break

    _apply_all_inactive(driver=driver, zone_count=zone_count, inactive_color=inactive_color)
    return observed


def _apply_single_active_zone(
    *,
    driver: KeyboardLightingDriver,
    zone_count: int,
    active_index: int,
    active_color: RgbColor,
    inactive_color: RgbColor,
) -> None:
    payload: list[ZoneColor] = []
    for zone_index in range(zone_count):
        color = active_color if zone_index == active_index else inactive_color
        payload.append(ZoneColor(zone_index=zone_index, color=color))
    driver.apply_zone_colors(payload)


def _apply_all_inactive(
    *,
    driver: KeyboardLightingDriver,
    zone_count: int,
    inactive_color: RgbColor,
) -> None:
    payload = [ZoneColor(zone_index=index, color=inactive_color) for index in range(zone_count)]
    driver.apply_zone_colors(payload)
