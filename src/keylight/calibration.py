from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from keylight.contracts import KeyboardLightingDriver
from keylight.models import ZoneColor


@dataclass(frozen=True, slots=True)
class CalibrationProvenance:
    method: str
    observed_order: list[int] | None = None
    workflow_report_path: str | None = None

    def validate(self, *, zone_count: int) -> None:
        method_text = self.method.strip()
        if method_text == "":
            raise ValueError("provenance.method must not be empty")

        if self.observed_order is not None:
            if len(self.observed_order) != zone_count:
                raise ValueError(
                    "provenance.observed_order length must equal zone_count"
                )
            expected = set(range(zone_count))
            provided = set(self.observed_order)
            if provided != expected:
                raise ValueError(
                    "provenance.observed_order must be a full permutation of "
                    "0..zone_count-1"
                )

        if self.workflow_report_path is not None:
            if self.workflow_report_path.strip() == "":
                raise ValueError("provenance.workflow_report_path must not be empty")

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"method": self.method}
        if self.observed_order is not None:
            data["observed_order"] = self.observed_order.copy()
        if self.workflow_report_path is not None:
            data["workflow_report_path"] = self.workflow_report_path
        return data


@dataclass(frozen=True, slots=True)
class CalibrationProfile:
    zone_count: int
    logical_to_hardware: list[int]
    generated_at_utc: str | None = None
    provenance: CalibrationProvenance | None = None

    def validate(self) -> None:
        if self.zone_count <= 0:
            raise ValueError("zone_count must be positive")
        if len(self.logical_to_hardware) != self.zone_count:
            raise ValueError("logical_to_hardware length must equal zone_count")
        expected = set(range(self.zone_count))
        provided = set(self.logical_to_hardware)
        if provided != expected:
            raise ValueError(
                "logical_to_hardware must be a full permutation of 0..zone_count-1"
            )
        if self.generated_at_utc is not None:
            _parse_iso_datetime(self.generated_at_utc)
        if self.provenance is not None:
            self.provenance.validate(zone_count=self.zone_count)
            if (
                self.provenance.observed_order is not None
                and self.provenance.observed_order != self.logical_to_hardware
            ):
                raise ValueError(
                    "provenance.observed_order must match logical_to_hardware"
                )

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "zone_count": self.zone_count,
            "logical_to_hardware": self.logical_to_hardware.copy(),
        }
        if self.generated_at_utc is not None:
            data["generated_at_utc"] = self.generated_at_utc
        if self.provenance is not None:
            data["provenance"] = self.provenance.to_dict()
        return data


def identity_profile(
    zone_count: int,
    *,
    source_method: str = "identity",
) -> CalibrationProfile:
    observed_order = list(range(zone_count))
    profile = CalibrationProfile(
        zone_count=zone_count,
        logical_to_hardware=observed_order.copy(),
        generated_at_utc=_utc_now_iso(),
        provenance=CalibrationProvenance(
            method=source_method,
            observed_order=observed_order,
        ),
    )
    profile.validate()
    return profile


def profile_from_observed_order(
    observed_order: list[int],
    zone_count: int,
    *,
    source_method: str = "observed-order",
    workflow_report_path: Path | str | None = None,
) -> CalibrationProfile:
    if len(observed_order) != zone_count:
        raise ValueError(
            f"observed_order length {len(observed_order)} does not match zone_count {zone_count}"
        )
    workflow_text: str | None = None
    if workflow_report_path is not None:
        raw_workflow = str(workflow_report_path).strip()
        if raw_workflow == "":
            raise ValueError("workflow_report_path must not be empty")
        workflow_text = raw_workflow
    profile = CalibrationProfile(
        zone_count=zone_count,
        logical_to_hardware=observed_order.copy(),
        generated_at_utc=_utc_now_iso(),
        provenance=CalibrationProvenance(
            method=source_method,
            observed_order=observed_order.copy(),
            workflow_report_path=workflow_text,
        ),
    )
    profile.validate()
    return profile


def load_calibration_profile(path: Path) -> CalibrationProfile:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("Calibration profile JSON must be an object.")

    zone_count = _parse_required_int(raw, "zone_count")
    raw_mapping = raw.get("logical_to_hardware")
    if not isinstance(raw_mapping, list):
        raise ValueError("logical_to_hardware must be a list.")

    mapping: list[int] = []
    for index, item in enumerate(raw_mapping):
        try:
            mapping.append(int(item))
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"logical_to_hardware[{index}] must be an integer."
            ) from error

    generated_at_utc = _parse_optional_string(raw, "generated_at_utc")

    raw_provenance = raw.get("provenance")
    provenance: CalibrationProvenance | None = None
    if raw_provenance is not None:
        if not isinstance(raw_provenance, dict):
            raise ValueError("provenance must be an object.")
        provenance = CalibrationProvenance(
            method=_parse_required_string(raw_provenance, "method"),
            observed_order=_parse_optional_int_list(raw_provenance, "observed_order"),
            workflow_report_path=_parse_optional_string(
                raw_provenance,
                "workflow_report_path",
            ),
        )

    profile = CalibrationProfile(
        zone_count=zone_count,
        logical_to_hardware=mapping,
        generated_at_utc=generated_at_utc,
        provenance=provenance,
    )
    profile.validate()
    return profile


def write_calibration_profile(profile: CalibrationProfile, path: Path) -> Path:
    profile.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
    return path


def remap_zones_to_hardware(
    zones: list[ZoneColor],
    profile: CalibrationProfile,
) -> list[ZoneColor]:
    profile.validate()
    remapped: list[ZoneColor] = []
    for zone in zones:
        logical_index = zone.zone_index
        if logical_index < 0 or logical_index >= profile.zone_count:
            raise ValueError(
                f"logical zone index {logical_index} is outside profile zone_count "
                f"{profile.zone_count}"
            )
        hardware_index = profile.logical_to_hardware[logical_index]
        remapped.append(ZoneColor(zone_index=hardware_index, color=zone.color))
    return remapped


class CalibratedDriver:
    def __init__(self, base_driver: KeyboardLightingDriver, profile: CalibrationProfile) -> None:
        self._base_driver = base_driver
        self._profile = profile

    def apply_zone_colors(self, zones: list[ZoneColor]) -> None:
        remapped = remap_zones_to_hardware(zones, self._profile)
        self._base_driver.apply_zone_colors(remapped)


def _parse_required_int(raw: dict[str, object], key: str) -> int:
    if key not in raw:
        raise ValueError(f"Missing required key '{key}' in calibration profile.")
    value = raw[key]
    if isinstance(value, bool):
        raise ValueError(f"'{key}' must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 10)
        except ValueError as error:
            raise ValueError(f"'{key}' must be an integer.") from error
    raise ValueError(f"'{key}' must be an integer.")


def _parse_required_string(raw: dict[str, object], key: str) -> str:
    if key not in raw:
        raise ValueError(f"Missing required key '{key}' in calibration profile.")
    value = raw[key]
    if not isinstance(value, str):
        raise ValueError(f"'{key}' must be a string.")
    text = value.strip()
    if text == "":
        raise ValueError(f"'{key}' must not be empty.")
    return text


def _parse_optional_string(raw: dict[str, object], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"'{key}' must be a string.")
    text = value.strip()
    if text == "":
        raise ValueError(f"'{key}' must not be empty.")
    return text


def _parse_optional_int_list(raw: dict[str, object], key: str) -> list[int] | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f"'{key}' must be a list.")
    parsed: list[int] = []
    for index, item in enumerate(value):
        if isinstance(item, bool):
            raise ValueError(f"'{key}[{index}]' must be an integer.")
        if isinstance(item, int):
            parsed.append(item)
            continue
        if isinstance(item, str):
            try:
                parsed.append(int(item, 10))
                continue
            except ValueError as error:
                raise ValueError(f"'{key}[{index}]' must be an integer.") from error
        raise ValueError(f"'{key}[{index}]' must be an integer.")
    return parsed


def _parse_iso_datetime(value: str) -> datetime:
    text = value.strip()
    if text == "":
        raise ValueError("generated_at_utc must not be empty")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError("generated_at_utc must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()
