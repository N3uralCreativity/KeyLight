import json
from pathlib import Path

import pytest

from keylight.live_analysis import (
    LiveQualityThresholds,
    analyze_live_run,
    write_live_analysis_report,
)


def _write_live_report(
    path: Path,
    *,
    configured_fps: int = 30,
    iterations: int = 10,
    attempted_iterations: int = 10,
    completed_iterations: int = 10,
    error_count: int = 0,
    aborted: bool = False,
    avg_total_ms: float = 10.0,
    effective_fps: float = 30.0,
    overrun_iterations: int = 0,
) -> None:
    path.write_text(
        json.dumps(
            {
                "started_at_utc": "2026-03-03T00:00:00+00:00",
                "finished_at_utc": "2026-03-03T00:00:01+00:00",
                "configured_fps": configured_fps,
                "iterations": iterations,
                "attempted_iterations": attempted_iterations,
                "completed_iterations": completed_iterations,
                "error_count": error_count,
                "max_consecutive_errors": error_count,
                "aborted": aborted,
                "last_error": None,
                "recovery_attempts": 0,
                "recovery_successes": 0,
                "avg_capture_ms": 1.0,
                "avg_map_ms": 1.0,
                "avg_process_ms": 1.0,
                "avg_send_ms": 1.0,
                "avg_total_ms": avg_total_ms,
                "target_frame_interval_ms": 1000.0 / configured_fps,
                "effective_fps": effective_fps,
                "overrun_iterations": overrun_iterations,
                "avg_overrun_ms": 0.0,
                "watchdog_emits": 0,
                "event_log_emits": 0,
            }
        ),
        encoding="utf-8",
    )


def _write_event_log(
    path: Path,
    totals: list[float],
    *,
    error_indexes: set[int] | None = None,
) -> None:
    rows: list[str] = []
    error_indexes = error_indexes or set()
    for index, total in enumerate(totals, start=1):
        status = "error" if index in error_indexes else "ok"
        rows.append(
            json.dumps(
                {
                    "timestamp_utc": "2026-03-03T00:00:00+00:00",
                    "status": status,
                    "iteration_index": index,
                    "iterations": len(totals),
                    "attempted_iterations": index,
                    "completed_iterations": index if status == "ok" else index - 1,
                    "error_count": 1 if status == "error" else 0,
                    "consecutive_errors": 1 if status == "error" else 0,
                    "aborted": False,
                    "error": "capture failed" if status == "error" else None,
                    "recovery_attempts": 0,
                    "recovery_successes": 0,
                    "capture_ms": 1.0,
                    "map_ms": 1.0,
                    "process_ms": 1.0,
                    "send_ms": 1.0,
                    "total_ms": total,
                }
            )
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_analyze_live_run_passes_with_event_log(tmp_path: Path) -> None:
    report_path = tmp_path / "live_report.json"
    event_path = tmp_path / "live_events.jsonl"
    _write_live_report(report_path, avg_total_ms=12.0)
    _write_event_log(event_path, [10.0, 11.0, 12.0, 13.0, 14.0])

    analysis = analyze_live_run(
        report_path=report_path,
        event_log_path=event_path,
        thresholds=LiveQualityThresholds(
            max_error_rate_percent=1.0,
            max_avg_total_ms=80.0,
            max_p95_total_ms=20.0,
        ),
    )

    assert analysis.passed is True
    assert analysis.event_samples == 5
    assert analysis.p95_total_ms is not None
    assert analysis.p95_total_ms <= 20.0


def test_analyze_live_run_fails_min_effective_fps_threshold(tmp_path: Path) -> None:
    report_path = tmp_path / "live_report.json"
    _write_live_report(
        report_path,
        effective_fps=8.0,
    )

    analysis = analyze_live_run(
        report_path=report_path,
        event_log_path=None,
        thresholds=LiveQualityThresholds(min_effective_fps=20.0),
    )

    assert analysis.passed is False
    assert any(item.startswith("effective_fps<") for item in analysis.failed_checks)


def test_analyze_live_run_fails_max_overrun_percent_threshold(tmp_path: Path) -> None:
    report_path = tmp_path / "live_report.json"
    _write_live_report(
        report_path,
        attempted_iterations=10,
        overrun_iterations=4,
    )

    analysis = analyze_live_run(
        report_path=report_path,
        event_log_path=None,
        thresholds=LiveQualityThresholds(max_overrun_percent=20.0),
    )

    assert analysis.passed is False
    assert any(item.startswith("overrun_percent>") for item in analysis.failed_checks)


def test_analyze_live_run_fails_thresholds(tmp_path: Path) -> None:
    report_path = tmp_path / "live_report.json"
    _write_live_report(
        report_path,
        attempted_iterations=10,
        completed_iterations=8,
        error_count=2,
        aborted=False,
        avg_total_ms=150.0,
    )

    analysis = analyze_live_run(
        report_path=report_path,
        event_log_path=None,
        thresholds=LiveQualityThresholds(
            max_error_rate_percent=1.0,
            max_avg_total_ms=80.0,
        ),
    )

    assert analysis.passed is False
    assert any(item.startswith("error_rate>") for item in analysis.failed_checks)
    assert any(item.startswith("avg_total_ms>") for item in analysis.failed_checks)


def test_analyze_live_run_supports_legacy_report_without_timing_fields(tmp_path: Path) -> None:
    report_path = tmp_path / "live_report.json"
    report_path.write_text(
        json.dumps(
            {
                "started_at_utc": "2026-03-03T00:00:00+00:00",
                "finished_at_utc": "2026-03-03T00:00:01+00:00",
                "iterations": 10,
                "attempted_iterations": 10,
                "completed_iterations": 10,
                "error_count": 0,
                "max_consecutive_errors": 0,
                "aborted": False,
                "last_error": None,
                "recovery_attempts": 0,
                "recovery_successes": 0,
                "avg_capture_ms": 1.0,
                "avg_map_ms": 1.0,
                "avg_process_ms": 1.0,
                "avg_send_ms": 1.0,
                "avg_total_ms": 10.0,
                "watchdog_emits": 0,
                "event_log_emits": 0,
            }
        ),
        encoding="utf-8",
    )

    analysis = analyze_live_run(
        report_path=report_path,
        event_log_path=None,
        thresholds=LiveQualityThresholds(),
    )

    assert analysis.passed is True
    assert analysis.effective_fps > 0.0


def test_analyze_live_run_fails_aborted_when_required(tmp_path: Path) -> None:
    report_path = tmp_path / "live_report.json"
    _write_live_report(report_path, aborted=True)

    analysis = analyze_live_run(
        report_path=report_path,
        event_log_path=None,
        thresholds=LiveQualityThresholds(require_no_abort=True),
    )

    assert analysis.passed is False
    assert "runtime_aborted" in analysis.failed_checks


def test_write_live_analysis_report_writes_json(tmp_path: Path) -> None:
    report_path = tmp_path / "live_report.json"
    _write_live_report(report_path)
    analysis = analyze_live_run(
        report_path=report_path,
        event_log_path=None,
        thresholds=LiveQualityThresholds(),
    )

    output_path = write_live_analysis_report(analysis, tmp_path / "analysis.json")

    content = output_path.read_text(encoding="utf-8")
    assert '"passed": true' in content
    assert '"error_rate_percent": 0.0' in content


def test_analyze_live_run_raises_for_invalid_event_log_line(tmp_path: Path) -> None:
    report_path = tmp_path / "live_report.json"
    event_path = tmp_path / "live_events.jsonl"
    _write_live_report(report_path)
    event_path.write_text("{\"total_ms\": 10}\nnot-json\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid JSON in event log at line 2"):
        analyze_live_run(
            report_path=report_path,
            event_log_path=event_path,
            thresholds=LiveQualityThresholds(),
        )
