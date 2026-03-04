from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CalibrateZonesReport:
    started_at_utc: str
    finished_at_utc: str
    zone_count: int
    steps_executed: int
    sweep_report_path: str | None
    template_output_path: str | None
    profile_output_path: str | None
    observed_order: list[int] | None
    profile_built: bool
    verify_requested: bool = False
    verify_executed: bool = False
    verify_steps_executed: int = 0
    verify_report_path: str | None = None
    live_verify_requested: bool = False
    live_verify_executed: bool = False
    live_verify_report_path: str | None = None
    live_verify_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def write_calibrate_zones_report(report: CalibrateZonesReport, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return output_path


def build_observed_order_template(zone_count: int) -> str:
    if zone_count <= 0:
        raise ValueError("zone_count must be positive.")
    logical_indexes = ", ".join(str(index) for index in range(zone_count))
    lines = [
        "# KeyLight observed zone order template",
        "#",
        "# Step 1: run calibrate-zones sweep and watch the keyboard.",
        "# Step 2: for logical indexes 0..N-1, write the observed hardware index that lit up.",
        "# Step 3: provide this file with --observed-order-file.",
        "#",
        f"# zone_count={zone_count}",
        f"# logical_indexes={logical_indexes}",
        "",
        "observed_order=",
    ]
    return "\n".join(lines) + "\n"


def write_observed_order_template(zone_count: int, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_observed_order_template(zone_count), encoding="utf-8")
    return output_path


def now_utc_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()
