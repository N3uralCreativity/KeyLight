from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LiveQualityThresholds:
    max_error_rate_percent: float = 1.0
    max_avg_total_ms: float = 80.0
    max_p95_total_ms: float = 120.0
    min_effective_fps: float = 0.0
    max_overrun_percent: float = 100.0
    require_no_abort: bool = True
    min_completed_iterations: int = 1

    def validate(self) -> None:
        if self.max_error_rate_percent < 0:
            raise ValueError("max_error_rate_percent must be >= 0.")
        if self.max_avg_total_ms < 0:
            raise ValueError("max_avg_total_ms must be >= 0.")
        if self.max_p95_total_ms < 0:
            raise ValueError("max_p95_total_ms must be >= 0.")
        if self.min_effective_fps < 0:
            raise ValueError("min_effective_fps must be >= 0.")
        if self.max_overrun_percent < 0 or self.max_overrun_percent > 100:
            raise ValueError("max_overrun_percent must be in range 0..100.")
        if self.min_completed_iterations < 0:
            raise ValueError("min_completed_iterations must be >= 0.")

    def to_dict(self) -> dict[str, object]:
        return {
            "max_error_rate_percent": self.max_error_rate_percent,
            "max_avg_total_ms": self.max_avg_total_ms,
            "max_p95_total_ms": self.max_p95_total_ms,
            "min_effective_fps": self.min_effective_fps,
            "max_overrun_percent": self.max_overrun_percent,
            "require_no_abort": self.require_no_abort,
            "min_completed_iterations": self.min_completed_iterations,
        }


@dataclass(frozen=True, slots=True)
class LiveAnalysisReport:
    generated_at_utc: str
    source_report_path: str
    source_event_log_path: str | None
    iterations: int
    attempted_iterations: int
    completed_iterations: int
    error_count: int
    aborted: bool
    error_rate_percent: float
    avg_total_ms: float
    configured_fps: int | None
    effective_fps: float
    overrun_iterations: int
    overrun_percent: float
    p95_total_ms: float | None
    event_samples: int
    error_event_samples: int
    thresholds: dict[str, object]
    pass_checks: list[str]
    failed_checks: list[str]
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "source_report_path": self.source_report_path,
            "source_event_log_path": self.source_event_log_path,
            "iterations": self.iterations,
            "attempted_iterations": self.attempted_iterations,
            "completed_iterations": self.completed_iterations,
            "error_count": self.error_count,
            "aborted": self.aborted,
            "error_rate_percent": self.error_rate_percent,
            "avg_total_ms": self.avg_total_ms,
            "configured_fps": self.configured_fps,
            "effective_fps": self.effective_fps,
            "overrun_iterations": self.overrun_iterations,
            "overrun_percent": self.overrun_percent,
            "p95_total_ms": self.p95_total_ms,
            "event_samples": self.event_samples,
            "error_event_samples": self.error_event_samples,
            "thresholds": self.thresholds,
            "pass_checks": self.pass_checks,
            "failed_checks": self.failed_checks,
            "passed": self.passed,
        }


def analyze_live_run(
    *,
    report_path: Path,
    event_log_path: Path | None,
    thresholds: LiveQualityThresholds,
) -> LiveAnalysisReport:
    thresholds.validate()
    root = _load_json_object(report_path)

    iterations = _int_field(root, "iterations")
    attempted_iterations = _int_field(root, "attempted_iterations")
    completed_iterations = _int_field(root, "completed_iterations")
    error_count = _int_field(root, "error_count")
    aborted = _bool_field(root, "aborted")
    avg_total_ms = _float_field(root, "avg_total_ms")
    configured_fps = _optional_int_field(root, "configured_fps")
    effective_fps = _optional_float_field(root, "effective_fps")
    overrun_iterations_raw = _optional_int_field(root, "overrun_iterations", default=0)
    overrun_iterations = 0 if overrun_iterations_raw is None else overrun_iterations_raw

    if attempted_iterations < 0 or completed_iterations < 0 or error_count < 0:
        raise ValueError("Live report counters must be non-negative.")
    if completed_iterations > attempted_iterations:
        raise ValueError("completed_iterations cannot exceed attempted_iterations.")
    if error_count > attempted_iterations:
        raise ValueError("error_count cannot exceed attempted_iterations.")
    if configured_fps is not None and configured_fps <= 0:
        raise ValueError("configured_fps must be positive when provided.")
    if overrun_iterations < 0:
        raise ValueError("overrun_iterations cannot be negative.")
    if overrun_iterations > attempted_iterations:
        raise ValueError("overrun_iterations cannot exceed attempted_iterations.")

    if effective_fps is None:
        effective_fps = _estimate_effective_fps(
            attempted_iterations=attempted_iterations,
            avg_total_ms=avg_total_ms,
        )
    if effective_fps < 0:
        raise ValueError("effective_fps cannot be negative.")

    error_rate_percent = (
        (float(error_count) / float(attempted_iterations)) * 100.0
        if attempted_iterations > 0
        else 0.0
    )
    overrun_percent = (
        (float(overrun_iterations) / float(attempted_iterations)) * 100.0
        if attempted_iterations > 0
        else 0.0
    )

    event_samples = 0
    error_event_samples = 0
    p95_total_ms: float | None = None
    if event_log_path is not None:
        totals, error_rows = _load_event_totals(event_log_path)
        event_samples = len(totals)
        error_event_samples = error_rows
        if totals:
            p95_total_ms = _percentile_95(totals)

    pass_checks: list[str] = []
    failed_checks: list[str] = []

    _append_check(
        passed=(not thresholds.require_no_abort) or (not aborted),
        pass_message="runtime_not_aborted",
        fail_message="runtime_aborted",
        pass_checks=pass_checks,
        failed_checks=failed_checks,
    )
    _append_check(
        passed=completed_iterations >= thresholds.min_completed_iterations,
        pass_message=f"completed_iterations>={thresholds.min_completed_iterations}",
        fail_message=(
            f"completed_iterations<{thresholds.min_completed_iterations}: "
            f"{completed_iterations}"
        ),
        pass_checks=pass_checks,
        failed_checks=failed_checks,
    )
    _append_check(
        passed=error_rate_percent <= thresholds.max_error_rate_percent,
        pass_message=f"error_rate<={thresholds.max_error_rate_percent:.3f}%",
        fail_message=(
            f"error_rate>{thresholds.max_error_rate_percent:.3f}%: "
            f"{error_rate_percent:.3f}%"
        ),
        pass_checks=pass_checks,
        failed_checks=failed_checks,
    )
    _append_check(
        passed=avg_total_ms <= thresholds.max_avg_total_ms,
        pass_message=f"avg_total_ms<={thresholds.max_avg_total_ms:.3f}",
        fail_message=f"avg_total_ms>{thresholds.max_avg_total_ms:.3f}: {avg_total_ms:.3f}",
        pass_checks=pass_checks,
        failed_checks=failed_checks,
    )
    _append_check(
        passed=effective_fps >= thresholds.min_effective_fps,
        pass_message=f"effective_fps>={thresholds.min_effective_fps:.3f}",
        fail_message=f"effective_fps<{thresholds.min_effective_fps:.3f}: {effective_fps:.3f}",
        pass_checks=pass_checks,
        failed_checks=failed_checks,
    )
    _append_check(
        passed=overrun_percent <= thresholds.max_overrun_percent,
        pass_message=f"overrun_percent<={thresholds.max_overrun_percent:.3f}%",
        fail_message=(
            f"overrun_percent>{thresholds.max_overrun_percent:.3f}%: "
            f"{overrun_percent:.3f}%"
        ),
        pass_checks=pass_checks,
        failed_checks=failed_checks,
    )

    if p95_total_ms is None:
        pass_checks.append("p95_total_ms_skipped_no_event_samples")
    else:
        _append_check(
            passed=p95_total_ms <= thresholds.max_p95_total_ms,
            pass_message=f"p95_total_ms<={thresholds.max_p95_total_ms:.3f}",
            fail_message=(
                f"p95_total_ms>{thresholds.max_p95_total_ms:.3f}: {p95_total_ms:.3f}"
            ),
            pass_checks=pass_checks,
            failed_checks=failed_checks,
        )

    passed = len(failed_checks) == 0
    return LiveAnalysisReport(
        generated_at_utc=_utc_now_iso(),
        source_report_path=str(report_path.resolve()),
        source_event_log_path=str(event_log_path.resolve()) if event_log_path else None,
        iterations=iterations,
        attempted_iterations=attempted_iterations,
        completed_iterations=completed_iterations,
        error_count=error_count,
        aborted=aborted,
        error_rate_percent=error_rate_percent,
        avg_total_ms=avg_total_ms,
        configured_fps=configured_fps,
        effective_fps=effective_fps,
        overrun_iterations=overrun_iterations,
        overrun_percent=overrun_percent,
        p95_total_ms=p95_total_ms,
        event_samples=event_samples,
        error_event_samples=error_event_samples,
        thresholds=thresholds.to_dict(),
        pass_checks=pass_checks,
        failed_checks=failed_checks,
        passed=passed,
    )


def write_live_analysis_report(report: LiveAnalysisReport, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return output_path


def _append_check(
    *,
    passed: bool,
    pass_message: str,
    fail_message: str,
    pass_checks: list[str],
    failed_checks: list[str],
) -> None:
    if passed:
        pass_checks.append(pass_message)
    else:
        failed_checks.append(fail_message)


def _load_event_totals(path: Path) -> tuple[list[float], int]:
    if not path.exists():
        raise ValueError(f"event log file not found: {path}")

    totals: list[float] = []
    error_rows = 0
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if line == "":
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Invalid JSON in event log at line {line_number}."
            ) from error
        if not isinstance(parsed, dict):
            raise ValueError(f"Invalid event row at line {line_number}: expected object.")
        total_ms = parsed.get("total_ms")
        if not isinstance(total_ms, (int, float)):
            raise ValueError(f"Invalid total_ms at line {line_number}.")
        status = parsed.get("status")
        if isinstance(status, str) and status in {"error", "aborted"}:
            error_rows += 1
        totals.append(float(total_ms))
    return totals, error_rows


def _percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = int(0.95 * len(ordered))
    if (0.95 * len(ordered)).is_integer():
        index -= 1
    index = max(0, min(index, len(ordered) - 1))
    return ordered[index]


def _load_json_object(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ValueError(f"live report file not found: {path}")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in live report file: {path}") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"Invalid live report format in {path}: expected JSON object.")
    return parsed


def _int_field(data: dict[str, object], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise ValueError(f"Invalid or missing integer field '{key}' in live report.")
    return value


def _float_field(data: dict[str, object], key: str) -> float:
    value = data.get(key)
    if not isinstance(value, (int, float)):
        raise ValueError(f"Invalid or missing numeric field '{key}' in live report.")
    return float(value)


def _bool_field(data: dict[str, object], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Invalid or missing boolean field '{key}' in live report.")
    return value


def _optional_int_field(
    data: dict[str, object],
    key: str,
    default: int | None = None,
) -> int | None:
    value = data.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Invalid integer field '{key}' in live report.")
    return value


def _optional_float_field(data: dict[str, object], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        raise ValueError(f"Invalid numeric field '{key}' in live report.")
    return float(value)


def _estimate_effective_fps(*, attempted_iterations: int, avg_total_ms: float) -> float:
    if attempted_iterations <= 0 or avg_total_ms <= 0:
        return 0.0
    total_seconds = (float(attempted_iterations) * avg_total_ms) / 1000.0
    if total_seconds <= 0:
        return 0.0
    return float(attempted_iterations) / total_seconds


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")
