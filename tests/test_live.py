from pathlib import Path

import pytest

from keylight.live import (
    LiveEventLogEntry,
    LiveRuntime,
    LiveRuntimeConfig,
    LiveWatchdogSnapshot,
    write_live_event_log_entry,
    write_live_runtime_report,
    write_live_watchdog_snapshot,
)
from keylight.models import CapturedFrame, RgbColor, ZoneColor
from keylight.processing import ColorProcessingConfig, ZoneColorProcessor


class _StubCapturer:
    def capture_frame(self) -> CapturedFrame:
        return CapturedFrame(width=1, height=1, pixels=[[RgbColor(10, 20, 30)]])


class _StubMapper:
    def map_frame(self, frame: CapturedFrame) -> list[ZoneColor]:
        assert frame.width == 1
        return [ZoneColor(zone_index=0, color=RgbColor(10, 20, 30))]


class _StubDriver:
    def __init__(self) -> None:
        self.calls = 0

    def apply_zone_colors(self, zones: list[ZoneColor]) -> None:
        self.calls += 1
        assert zones[0].zone_index == 0


class _AlwaysFailCapturer:
    def capture_frame(self) -> CapturedFrame:
        raise RuntimeError("capture failed")


class _FailThenRecoverCapturer:
    def __init__(self) -> None:
        self.calls = 0

    def capture_frame(self) -> CapturedFrame:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("capture failed once")
        return CapturedFrame(width=1, height=1, pixels=[[RgbColor(10, 20, 30)]])


class _RecoverableDriver(_StubDriver):
    def __init__(self) -> None:
        super().__init__()
        self.reconnect_calls = 0

    def reconnect(self) -> bool:
        self.reconnect_calls += 1
        return True


def test_live_runtime_runs_expected_iterations() -> None:
    driver = _StubDriver()
    runtime = LiveRuntime(
        capturer=_StubCapturer(),
        mapper=_StubMapper(),
        processor=ZoneColorProcessor(
            config=ColorProcessingConfig(
                smoothing_enabled=False,
                smoothing_alpha=0.25,
                brightness_max_percent=100,
            )
        ),
        driver=driver,
        config=LiveRuntimeConfig(fps=200, iterations=3),
    )

    report = runtime.run()

    assert driver.calls == 3
    assert report.iterations == 3
    assert report.attempted_iterations == 3
    assert report.completed_iterations == 3
    assert report.error_count == 0
    assert report.aborted is False
    assert report.recovery_attempts == 0
    assert report.recovery_successes == 0
    assert report.watchdog_emits == 0
    assert report.event_log_emits == 0
    assert report.restore_requested is False
    assert report.restore_applied is False
    assert report.restore_error is None
    assert report.started_at_utc != ""
    assert report.finished_at_utc != ""
    assert report.configured_fps == 200
    assert report.target_frame_interval_ms > 0.0
    assert report.effective_fps >= 0.0
    assert report.overrun_iterations >= 0
    assert report.avg_overrun_ms >= 0.0
    assert report.avg_total_ms >= 0.0


def test_live_runtime_aborts_after_max_consecutive_errors() -> None:
    runtime = LiveRuntime(
        capturer=_AlwaysFailCapturer(),
        mapper=_StubMapper(),
        processor=ZoneColorProcessor(config=ColorProcessingConfig()),
        driver=_StubDriver(),
        config=LiveRuntimeConfig(
            fps=120,
            iterations=10,
            max_consecutive_errors=2,
            error_backoff_ms=0,
        ),
    )

    report = runtime.run()

    assert report.aborted is True
    assert report.completed_iterations == 0
    assert report.attempted_iterations == 2
    assert report.error_count == 2
    assert report.max_consecutive_errors == 2
    assert report.last_error == "capture failed"
    assert report.recovery_attempts == 0
    assert report.recovery_successes == 0
    assert report.watchdog_emits == 0
    assert report.event_log_emits == 0
    assert report.restore_requested is False
    assert report.restore_applied is False
    assert report.restore_error is None


def test_live_runtime_stop_on_error_raises() -> None:
    runtime = LiveRuntime(
        capturer=_AlwaysFailCapturer(),
        mapper=_StubMapper(),
        processor=ZoneColorProcessor(config=ColorProcessingConfig()),
        driver=_StubDriver(),
        config=LiveRuntimeConfig(
            fps=120,
            iterations=10,
            max_consecutive_errors=2,
            error_backoff_ms=0,
            stop_on_error=True,
        ),
    )

    with pytest.raises(RuntimeError, match="capture failed"):
        runtime.run()


def test_write_live_runtime_report_writes_json(tmp_path: Path) -> None:
    runtime = LiveRuntime(
        capturer=_StubCapturer(),
        mapper=_StubMapper(),
        processor=ZoneColorProcessor(config=ColorProcessingConfig()),
        driver=_StubDriver(),
        config=LiveRuntimeConfig(fps=120, iterations=1),
    )
    report = runtime.run()

    output_path = write_live_runtime_report(report, tmp_path / "live_report.json")

    content = output_path.read_text(encoding="utf-8")
    assert '"iterations": 1' in content
    assert '"error_count": 0' in content


def test_live_runtime_attempts_driver_recovery() -> None:
    driver = _RecoverableDriver()
    runtime = LiveRuntime(
        capturer=_FailThenRecoverCapturer(),
        mapper=_StubMapper(),
        processor=ZoneColorProcessor(config=ColorProcessingConfig()),
        driver=driver,
        config=LiveRuntimeConfig(
            fps=120,
            iterations=3,
            max_consecutive_errors=2,
            error_backoff_ms=0,
            reconnect_attempts=1,
        ),
    )

    report = runtime.run()

    assert report.error_count == 1
    assert report.completed_iterations == 2
    assert report.recovery_attempts == 1
    assert report.recovery_successes == 1
    assert report.event_log_emits == 0
    assert driver.reconnect_calls == 1


def test_live_runtime_emits_watchdog_snapshots() -> None:
    snapshots: list[LiveWatchdogSnapshot] = []

    runtime = LiveRuntime(
        capturer=_StubCapturer(),
        mapper=_StubMapper(),
        processor=ZoneColorProcessor(config=ColorProcessingConfig()),
        driver=_StubDriver(),
        config=LiveRuntimeConfig(
            fps=120,
            iterations=5,
            watchdog_interval_iterations=2,
        ),
        watchdog_callback=snapshots.append,
    )
    report = runtime.run()

    assert report.watchdog_emits == 3
    assert len(snapshots) == 3
    assert snapshots[-1].attempted_iterations == 5
    assert snapshots[-1].completed_iterations == 5
    assert snapshots[-1].error_count == 0
    assert snapshots[-1].recovery_attempts == 0
    assert snapshots[-1].recovery_successes == 0
    assert report.event_log_emits == 0


def test_live_runtime_emits_event_log_entries() -> None:
    entries: list[LiveEventLogEntry] = []

    runtime = LiveRuntime(
        capturer=_StubCapturer(),
        mapper=_StubMapper(),
        processor=ZoneColorProcessor(config=ColorProcessingConfig()),
        driver=_StubDriver(),
        config=LiveRuntimeConfig(
            fps=120,
            iterations=5,
            event_log_interval_iterations=2,
        ),
        event_log_callback=entries.append,
    )

    report = runtime.run()

    assert report.event_log_emits == 2
    assert len(entries) == 2
    assert entries[0].status == "ok"
    assert entries[-1].attempted_iterations == 4
    assert entries[-1].completed_iterations == 4


def test_write_live_watchdog_snapshot_writes_json(tmp_path: Path) -> None:
    snapshot = LiveWatchdogSnapshot(
        timestamp_utc="2026-03-03T00:00:00+00:00",
        iterations=300,
        attempted_iterations=10,
        completed_iterations=10,
        error_count=0,
        consecutive_errors=0,
        aborted=False,
        last_error=None,
        recovery_attempts=0,
        recovery_successes=0,
    )

    output_path = write_live_watchdog_snapshot(snapshot, tmp_path / "watchdog.json")

    content = output_path.read_text(encoding="utf-8")
    assert '"attempted_iterations": 10' in content
    assert '"aborted": false' in content


def test_write_live_event_log_entry_appends_jsonl(tmp_path: Path) -> None:
    output_path = tmp_path / "events.jsonl"
    first = LiveEventLogEntry(
        timestamp_utc="2026-03-03T00:00:00+00:00",
        status="ok",
        iteration_index=1,
        iterations=3,
        attempted_iterations=1,
        completed_iterations=1,
        error_count=0,
        consecutive_errors=0,
        aborted=False,
        error=None,
        recovery_attempts=0,
        recovery_successes=0,
        capture_ms=1.0,
        map_ms=1.0,
        process_ms=1.0,
        send_ms=1.0,
        total_ms=4.0,
    )
    second = LiveEventLogEntry(
        timestamp_utc="2026-03-03T00:00:01+00:00",
        status="error",
        iteration_index=2,
        iterations=3,
        attempted_iterations=2,
        completed_iterations=1,
        error_count=1,
        consecutive_errors=1,
        aborted=False,
        error="capture failed",
        recovery_attempts=1,
        recovery_successes=1,
        capture_ms=0.5,
        map_ms=0.0,
        process_ms=0.0,
        send_ms=0.0,
        total_ms=0.5,
    )

    write_live_event_log_entry(first, output_path)
    write_live_event_log_entry(second, output_path)

    lines = output_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert '"status": "ok"' in lines[0]
    assert '"status": "error"' in lines[1]
