from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from keylight.mapping.calibrated_mapper import ZoneGeometryProfile, ZoneRect


@dataclass(frozen=True, slots=True)
class ZoneProfileBuildConfig:
    rows: int
    columns: int
    row_weights: list[float] | None = None
    column_weights: list[float] | None = None
    row_column_weights: list[list[float]] | None = None
    x_start: float = 0.0
    x_end: float = 1.0
    y_start: float = 0.0
    y_end: float = 1.0
    row_direction: str = "top-to-bottom"
    column_direction: str = "left-to-right"
    serpentine: bool = False

    def validate(self) -> None:
        if self.rows <= 0 or self.columns <= 0:
            raise ValueError("rows and columns must be positive.")
        if self.row_direction not in {"top-to-bottom", "bottom-to-top"}:
            raise ValueError("row_direction must be 'top-to-bottom' or 'bottom-to-top'.")
        if self.column_direction not in {"left-to-right", "right-to-left"}:
            raise ValueError("column_direction must be 'left-to-right' or 'right-to-left'.")
        if self.x_start < 0.0 or self.x_end > 1.0 or self.x_start >= self.x_end:
            raise ValueError("x_start/x_end must satisfy 0.0 <= x_start < x_end <= 1.0.")
        if self.y_start < 0.0 or self.y_end > 1.0 or self.y_start >= self.y_end:
            raise ValueError("y_start/y_end must satisfy 0.0 <= y_start < y_end <= 1.0.")

        if self.row_weights is not None:
            _validate_weights(self.row_weights, expected_count=self.rows, label="row_weights")
        if self.column_weights is not None:
            _validate_weights(
                self.column_weights,
                expected_count=self.columns,
                label="column_weights",
            )
        if self.row_column_weights is not None:
            if len(self.row_column_weights) != self.rows:
                raise ValueError("row_column_weights row count must match rows.")
            for row_index, row_weights in enumerate(self.row_column_weights):
                _validate_weights(
                    row_weights,
                    expected_count=self.columns,
                    label=f"row_column_weights[{row_index}]",
                )


def build_zone_geometry_profile(config: ZoneProfileBuildConfig) -> ZoneGeometryProfile:
    config.validate()

    row_weights = config.row_weights if config.row_weights is not None else [1.0] * config.rows
    row_spans = _weighted_spans(row_weights, start=config.y_start, end=config.y_end)

    column_weights_default = (
        config.column_weights if config.column_weights is not None else [1.0] * config.columns
    )
    columns_per_row: list[list[tuple[float, float]]] = []
    for row_index in range(config.rows):
        row_column_weights = (
            config.row_column_weights[row_index]
            if config.row_column_weights is not None
            else column_weights_default
        )
        columns_per_row.append(
            _weighted_spans(
                row_column_weights,
                start=config.x_start,
                end=config.x_end,
            )
        )

    row_order = list(range(config.rows))
    if config.row_direction == "bottom-to-top":
        row_order.reverse()

    base_column_order = list(range(config.columns))
    if config.column_direction == "right-to-left":
        base_column_order.reverse()

    zones: list[ZoneRect] = []
    zone_index = 0
    for row_position, row_index in enumerate(row_order):
        column_order = list(base_column_order)
        if config.serpentine and row_position % 2 == 1:
            column_order.reverse()
        y0, y1 = row_spans[row_index]
        for column_index in column_order:
            x0, x1 = columns_per_row[row_index][column_index]
            zones.append(ZoneRect(zone_index=zone_index, x0=x0, y0=y0, x1=x1, y1=y1))
            zone_index += 1

    profile = ZoneGeometryProfile(version=1, zones=zones)
    profile.validate()
    return profile


def write_zone_geometry_profile(profile: ZoneGeometryProfile, output_path: Path) -> Path:
    profile.validate()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": profile.version,
        "zones": [
            {
                "zone_index": zone.zone_index,
                "x0": zone.x0,
                "y0": zone.y0,
                "x1": zone.x1,
                "y1": zone.y1,
            }
            for zone in sorted(profile.zones, key=lambda value: value.zone_index)
        ],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def _validate_weights(weights: list[float], *, expected_count: int, label: str) -> None:
    if len(weights) != expected_count:
        raise ValueError(f"{label} must contain exactly {expected_count} values.")
    if any(weight <= 0.0 for weight in weights):
        raise ValueError(f"{label} values must be positive.")


def _weighted_spans(weights: list[float], *, start: float, end: float) -> list[tuple[float, float]]:
    total = sum(weights)
    if total <= 0:
        raise ValueError("weight total must be positive.")

    spans: list[tuple[float, float]] = []
    cursor = start
    extent = end - start
    for index, weight in enumerate(weights):
        if index == len(weights) - 1:
            next_cursor = end
        else:
            next_cursor = cursor + extent * (weight / total)
        spans.append((cursor, next_cursor))
        cursor = next_cursor
    return spans
