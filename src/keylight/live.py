from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter, sleep

from keylight.contracts import KeyboardLightingDriver, ScreenCapturer, ZoneMapper
from keylight.processing import ZoneColorProcessor


@dataclass(frozen=True, slots=True)
class LiveRuntimeConfig:
    fps: int = 30
    iterations: int = 300
    max_consecutive_errors: int = 5
    error_backoff_ms: int = 250
    stop_on_error: bool = False
    reconnect_on_error: bool = True
    reconnect_attempts: int = 1
    watchdog_interval_iterations: int = 0
    event_log_interval_iterations: int = 0

    def validate(self) -> None:
        if self.fps <= 0:
            raise ValueError("fps must be positive")
        if self.iterations <= 0:
            raise ValueError("iterations must be positive")
        if self.max_consecutive_errors <= 0:
            raise ValueError("max_consecutive_errors must be positive")
        if self.error_backoff_ms < 0:
            raise ValueError("error_backoff_ms must be >= 0")
        if self.reconnect_attempts < 0:
            raise ValueError("reconnect_attempts must be >= 0")
        if self.watchdog_interval_iterations < 0:
            raise ValueError("watchdog_interval_iterations must be >= 0")
        if self.event_log_interval_iterations < 0:
            raise ValueError("event_log_interval_iterations must be >= 0")

    @property
    def frame_interval_seconds(self) -> float:
        return 1.0 / self.fps

    @property
    def error_backoff_seconds(self) -> float:
        return self.error_backoff_ms / 1000.0


@dataclass(frozen=True, slots=True)
class LiveRuntimeReport:
    started_at_utc: str
    finished_at_utc: str
    configured_fps: int
    iterations: int
    attempted_iterations: int
    completed_iterations: int
    error_count: int
    max_consecutive_errors: int
    aborted: bool
    last_error: str | None
    recovery_attempts: int
    recovery_successes: int
    avg_capture_ms: float
    avg_map_ms: float
    avg_process_ms: float
    avg_send_ms: float
    avg_total_ms: float
    target_frame_interval_ms: float
    effective_fps: float
    overrun_iterations: int
    avg_overrun_ms: float
    watchdog_emits: int
    event_log_emits: int
    restore_requested: bool = False
    restore_applied: bool = False
    restore_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "configured_fps": self.configured_fps,
            "iterations": self.iterations,
            "attempted_iterations": self.attempted_iterations,
            "completed_iterations": self.completed_iterations,
            "error_count": self.error_count,
            "max_consecutive_errors": self.max_consecutive_errors,
            "aborted": self.aborted,
            "last_error": self.last_error,
            "recovery_attempts": self.recovery_attempts,
            "recovery_successes": self.recovery_successes,
            "avg_capture_ms": self.avg_capture_ms,
            "avg_map_ms": self.avg_map_ms,
            "avg_process_ms": self.avg_process_ms,
            "avg_send_ms": self.avg_send_ms,
            "avg_total_ms": self.avg_total_ms,
            "target_frame_interval_ms": self.target_frame_interval_ms,
            "effective_fps": self.effective_fps,
            "overrun_iterations": self.overrun_iterations,
            "avg_overrun_ms": self.avg_overrun_ms,
            "watchdog_emits": self.watchdog_emits,
            "event_log_emits": self.event_log_emits,
            "restore_requested": self.restore_requested,
            "restore_applied": self.restore_applied,
            "restore_error": self.restore_error,
        }


@dataclass(frozen=True, slots=True)
class LiveWatchdogSnapshot:
    timestamp_utc: str
    iterations: int
    attempted_iterations: int
    completed_iterations: int
    error_count: int
    consecutive_errors: int
    aborted: bool
    last_error: str | None
    recovery_attempts: int
    recovery_successes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp_utc": self.timestamp_utc,
            "iterations": self.iterations,
            "attempted_iterations": self.attempted_iterations,
            "completed_iterations": self.completed_iterations,
            "error_count": self.error_count,
            "consecutive_errors": self.consecutive_errors,
            "aborted": self.aborted,
            "last_error": self.last_error,
            "recovery_attempts": self.recovery_attempts,
            "recovery_successes": self.recovery_successes,
        }


@dataclass(frozen=True, slots=True)
class LiveEventLogEntry:
    timestamp_utc: str
    status: str
    iteration_index: int
    iterations: int
    attempted_iterations: int
    completed_iterations: int
    error_count: int
    consecutive_errors: int
    aborted: bool
    error: str | None
    recovery_attempts: int
    recovery_successes: int
    capture_ms: float
    map_ms: float
    process_ms: float
    send_ms: float
    total_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp_utc": self.timestamp_utc,
            "status": self.status,
            "iteration_index": self.iteration_index,
            "iterations": self.iterations,
            "attempted_iterations": self.attempted_iterations,
            "completed_iterations": self.completed_iterations,
            "error_count": self.error_count,
            "consecutive_errors": self.consecutive_errors,
            "aborted": self.aborted,
            "error": self.error,
            "recovery_attempts": self.recovery_attempts,
            "recovery_successes": self.recovery_successes,
            "capture_ms": self.capture_ms,
            "map_ms": self.map_ms,
            "process_ms": self.process_ms,
            "send_ms": self.send_ms,
            "total_ms": self.total_ms,
        }


class LiveRuntime:
    def __init__(
        self,
        *,
        capturer: ScreenCapturer,
        mapper: ZoneMapper,
        processor: ZoneColorProcessor,
        driver: KeyboardLightingDriver,
        config: LiveRuntimeConfig,
        watchdog_callback: Callable[[LiveWatchdogSnapshot], None] | None = None,
        event_log_callback: Callable[[LiveEventLogEntry], None] | None = None,
    ) -> None:
        self._capturer = capturer
        self._mapper = mapper
        self._processor = processor
        self._driver = driver
        self._config = config
        self._watchdog_callback = watchdog_callback
        self._event_log_callback = event_log_callback

    def run(self) -> LiveRuntimeReport:
        self._config.validate()
        started_at_utc = _utc_now_iso()

        total_capture = 0.0
        total_map = 0.0
        total_process = 0.0
        total_send = 0.0
        total_loop = 0.0
        interval = self._config.frame_interval_seconds
        error_backoff = self._config.error_backoff_seconds

        completed_iterations = 0
        error_count = 0
        consecutive_errors = 0
        max_consecutive_errors = 0
        aborted = False
        last_error: str | None = None
        recovery_attempts = 0
        recovery_successes = 0
        watchdog_emits = 0
        event_log_emits = 0
        overrun_iterations = 0
        total_overrun = 0.0

        def emit_watchdog(*, force: bool, consecutive: int) -> None:
            nonlocal watchdog_emits
            if self._watchdog_callback is None:
                return
            interval_count = self._config.watchdog_interval_iterations
            if interval_count <= 0:
                return
            attempted = completed_iterations + error_count
            if attempted <= 0:
                return
            if not force and attempted % interval_count != 0:
                return
            snapshot = LiveWatchdogSnapshot(
                timestamp_utc=_utc_now_iso(),
                iterations=self._config.iterations,
                attempted_iterations=attempted,
                completed_iterations=completed_iterations,
                error_count=error_count,
                consecutive_errors=consecutive,
                aborted=aborted,
                last_error=last_error,
                recovery_attempts=recovery_attempts,
                recovery_successes=recovery_successes,
            )
            try:
                self._watchdog_callback(snapshot)
            except Exception:
                return
            watchdog_emits += 1

        def emit_event_log(
            *,
            force: bool,
            status: str,
            iteration_index: int,
            consecutive: int,
            error: str | None,
            capture_seconds: float,
            map_seconds: float,
            process_seconds: float,
            send_seconds: float,
            total_seconds: float,
        ) -> None:
            nonlocal event_log_emits
            if self._event_log_callback is None:
                return
            interval_count = self._config.event_log_interval_iterations
            if interval_count <= 0:
                return
            attempted = completed_iterations + error_count
            if attempted <= 0:
                return
            if not force and attempted % interval_count != 0:
                return
            event = LiveEventLogEntry(
                timestamp_utc=_utc_now_iso(),
                status=status,
                iteration_index=iteration_index,
                iterations=self._config.iterations,
                attempted_iterations=attempted,
                completed_iterations=completed_iterations,
                error_count=error_count,
                consecutive_errors=consecutive,
                aborted=aborted,
                error=error,
                recovery_attempts=recovery_attempts,
                recovery_successes=recovery_successes,
                capture_ms=capture_seconds * 1000.0,
                map_ms=map_seconds * 1000.0,
                process_ms=process_seconds * 1000.0,
                send_ms=send_seconds * 1000.0,
                total_ms=total_seconds * 1000.0,
            )
            try:
                self._event_log_callback(event)
            except Exception:
                return
            event_log_emits += 1

        for iteration_index in range(1, self._config.iterations + 1):
            loop_start = perf_counter()
            capture_elapsed = 0.0
            map_elapsed = 0.0
            process_elapsed = 0.0
            send_elapsed = 0.0

            try:
                capture_start = perf_counter()
                frame = self._capturer.capture_frame()
                capture_elapsed = perf_counter() - capture_start
                total_capture += capture_elapsed

                map_start = perf_counter()
                zones = self._mapper.map_frame(frame)
                map_elapsed = perf_counter() - map_start
                total_map += map_elapsed

                process_start = perf_counter()
                processed = self._processor.process(zones)
                process_elapsed = perf_counter() - process_start
                total_process += process_elapsed

                send_start = perf_counter()
                self._driver.apply_zone_colors(processed)
                send_elapsed = perf_counter() - send_start
                total_send += send_elapsed
            except Exception as error:
                error_count += 1
                consecutive_errors += 1
                max_consecutive_errors = max(max_consecutive_errors, consecutive_errors)
                last_error = str(error)
                _reset_driver_cache_if_supported(self._driver)
                attempted_recoveries, recovered = _recover_driver_if_supported(
                    self._driver,
                    error,
                    attempts=self._config.reconnect_attempts
                    if self._config.reconnect_on_error
                    else 0,
                )
                recovery_attempts += attempted_recoveries
                if recovered:
                    recovery_successes += 1
                if self._config.stop_on_error:
                    raise
                if consecutive_errors >= self._config.max_consecutive_errors:
                    aborted = True
                    loop_elapsed = perf_counter() - loop_start
                    total_loop += loop_elapsed
                    emit_event_log(
                        force=True,
                        status="aborted",
                        iteration_index=iteration_index,
                        consecutive=consecutive_errors,
                        error=last_error,
                        capture_seconds=capture_elapsed,
                        map_seconds=map_elapsed,
                        process_seconds=process_elapsed,
                        send_seconds=send_elapsed,
                        total_seconds=loop_elapsed,
                    )
                    emit_watchdog(force=True, consecutive=consecutive_errors)
                    overrun = loop_elapsed - interval
                    if overrun > 0:
                        overrun_iterations += 1
                        total_overrun += overrun
                    break
                if error_backoff > 0:
                    sleep(error_backoff)
                loop_elapsed = perf_counter() - loop_start
                total_loop += loop_elapsed
                emit_event_log(
                    force=True,
                    status="error",
                    iteration_index=iteration_index,
                    consecutive=consecutive_errors,
                    error=last_error,
                    capture_seconds=capture_elapsed,
                    map_seconds=map_elapsed,
                    process_seconds=process_elapsed,
                    send_seconds=send_elapsed,
                    total_seconds=loop_elapsed,
                )
                emit_watchdog(force=False, consecutive=consecutive_errors)
                overrun = loop_elapsed - interval
                if overrun > 0:
                    overrun_iterations += 1
                    total_overrun += overrun
                continue

            elapsed = perf_counter() - loop_start
            total_loop += elapsed
            completed_iterations += 1
            consecutive_errors = 0
            emit_event_log(
                force=False,
                status="ok",
                iteration_index=iteration_index,
                consecutive=consecutive_errors,
                error=None,
                capture_seconds=capture_elapsed,
                map_seconds=map_elapsed,
                process_seconds=process_elapsed,
                send_seconds=send_elapsed,
                total_seconds=elapsed,
            )
            emit_watchdog(force=False, consecutive=consecutive_errors)
            overrun = elapsed - interval
            if overrun > 0:
                overrun_iterations += 1
                total_overrun += overrun
            remaining = interval - elapsed
            if remaining > 0:
                sleep(remaining)

        attempted_iterations = completed_iterations + error_count
        if attempted_iterations > 0 and self._config.watchdog_interval_iterations > 0:
            interval_count = self._config.watchdog_interval_iterations
            if attempted_iterations % interval_count != 0:
                emit_watchdog(force=True, consecutive=consecutive_errors)
        divisor = float(attempted_iterations if attempted_iterations > 0 else 1)
        overrun_divisor = float(overrun_iterations if overrun_iterations > 0 else 1)
        effective_fps = (
            float(completed_iterations) / total_loop if total_loop > 0.0 else 0.0
        )
        finished_at_utc = _utc_now_iso()
        return LiveRuntimeReport(
            started_at_utc=started_at_utc,
            finished_at_utc=finished_at_utc,
            configured_fps=self._config.fps,
            iterations=self._config.iterations,
            attempted_iterations=attempted_iterations,
            completed_iterations=completed_iterations,
            error_count=error_count,
            max_consecutive_errors=max_consecutive_errors,
            aborted=aborted,
            last_error=last_error,
            recovery_attempts=recovery_attempts,
            recovery_successes=recovery_successes,
            avg_capture_ms=(total_capture / divisor) * 1000.0,
            avg_map_ms=(total_map / divisor) * 1000.0,
            avg_process_ms=(total_process / divisor) * 1000.0,
            avg_send_ms=(total_send / divisor) * 1000.0,
            avg_total_ms=(total_loop / divisor) * 1000.0,
            target_frame_interval_ms=interval * 1000.0,
            effective_fps=effective_fps,
            overrun_iterations=overrun_iterations,
            avg_overrun_ms=(total_overrun / overrun_divisor) * 1000.0,
            watchdog_emits=watchdog_emits,
            event_log_emits=event_log_emits,
        )


def _reset_driver_cache_if_supported(driver: KeyboardLightingDriver) -> None:
    reset_fn = getattr(driver, "reset_cache", None)
    if callable(reset_fn):
        reset_fn()


def _recover_driver_if_supported(
    driver: KeyboardLightingDriver,
    error: Exception,
    *,
    attempts: int,
) -> tuple[int, bool]:
    if attempts <= 0:
        return (0, False)

    attempted = 0
    for _ in range(attempts):
        outcome = _invoke_recovery(driver, error)
        if outcome is None:
            return (attempted, False)
        attempted += 1
        if outcome:
            return (attempted, True)
    return (attempted, False)


def _invoke_recovery(driver: KeyboardLightingDriver, error: Exception) -> bool | None:
    recover_fn = getattr(driver, "recover_from_error", None)
    if callable(recover_fn):
        try:
            result = recover_fn(error)
        except Exception:
            return False
        if result is None:
            return True
        return bool(result)

    reconnect_fn = getattr(driver, "reconnect", None)
    if callable(reconnect_fn):
        try:
            result = reconnect_fn()
        except Exception:
            return False
        if result is None:
            return True
        return bool(result)

    return None


def write_live_runtime_report(report: LiveRuntimeReport, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return output_path


def write_live_watchdog_snapshot(snapshot: LiveWatchdogSnapshot, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
    return output_path


def write_live_event_log_entry(entry: LiveEventLogEntry, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry.to_dict()))
        handle.write("\n")
    return output_path


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")
