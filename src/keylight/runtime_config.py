from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from keylight.sound_reactive import DEFAULT_PALETTE, parse_palette_strings


@dataclass(frozen=True, slots=True)
class LiveCommandDefaults:
    mode_source: str = "screen"

    capturer: str = "windows-mss"
    monitor_index: int = 1
    capture_width: int = 120
    capture_height: int = 20

    mapper: str = "grid"
    zone_profile: Path | None = None
    rows: int = 2
    columns: int = 12
    fps: int = 30
    iterations: int = 300

    backend: str = "simulated"
    hid_path: str | None = None
    vendor_id: str | None = None
    product_id: str | None = None
    report_id: int = 1
    write_method: str = "output"
    pad_length: int = 64
    packet_template: str = "{report_id} {zone} {r} {g} {b}"
    calibration_profile: Path | None = None

    audio_input_kind: str = "output-loopback"
    audio_device_id: str | None = None
    sound_effect: str = "spectrum"
    audio_sample_rate_hz: int = 48_000
    audio_frame_size: int = 2_048
    audio_sensitivity: float = 1.0
    audio_attack_alpha: float = 0.55
    audio_decay_alpha: float = 0.2
    audio_noise_floor: float = 0.02
    audio_bass_gain: float = 1.3
    audio_mid_gain: float = 1.0
    audio_treble_gain: float = 1.0
    audio_zone_layout: str = "linear"
    audio_palette: tuple[str, ...] = DEFAULT_PALETTE

    smoothing_enabled: bool = False
    smoothing_alpha: float = 0.25
    brightness_max_percent: int = 100

    max_consecutive_errors: int = 5
    error_backoff_ms: int = 250
    stop_on_error: bool = False
    strict_preflight: bool = False
    reconnect_on_error: bool = True
    reconnect_attempts: int = 1
    watchdog_interval_iterations: int = 0
    watchdog_output: Path | None = None
    event_log_interval_iterations: int = 0
    event_log_output: Path | None = None
    restore_on_exit: bool = False
    restore_color: str = "0,0,0"


def load_live_command_defaults(
    config_path: Path,
    *,
    must_exist: bool = False,
) -> LiveCommandDefaults:
    if not config_path.exists():
        if must_exist:
            raise ValueError(f"config file not found: {config_path}")
        return LiveCommandDefaults()

    try:
        import tomllib
    except ModuleNotFoundError as error:
        raise RuntimeError("Python tomllib module is unavailable.") from error

    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid config format in {config_path}. Expected TOML table root.")

    app = _table(raw, "app")
    mode = _table(raw, "mode")
    capture = _table(raw, "capture")
    mapping = _table(raw, "mapping")
    driver = _table(raw, "driver")
    audio = _table(raw, "audio")
    smoothing = _table(raw, "smoothing")
    brightness = _table(raw, "brightness")
    runtime = _table(raw, "runtime")

    defaults = LiveCommandDefaults()
    defaults = replace(
        defaults,
        mode_source=_str(mode, "source", defaults.mode_source),
        rows=_int(app, "rows", defaults.rows),
        columns=_int(app, "columns", defaults.columns),
        fps=_int(app, "fps", defaults.fps),
        iterations=_int(app, "iterations", defaults.iterations),
    )
    defaults = replace(
        defaults,
        capturer=_str(capture, "backend", defaults.capturer),
        monitor_index=_int(capture, "monitor_index", defaults.monitor_index),
        capture_width=_int(capture, "width", defaults.capture_width),
        capture_height=_int(capture, "height", defaults.capture_height),
    )
    defaults = replace(
        defaults,
        mapper=_str(mapping, "backend", defaults.mapper),
        zone_profile=_optional_path(
            mapping,
            "zone_profile",
            defaults.zone_profile,
            base_dir=config_path.parent,
        ),
    )
    defaults = replace(
        defaults,
        backend=_str(driver, "backend", defaults.backend),
        hid_path=_optional_text(driver, "hid_path", defaults.hid_path),
        vendor_id=_optional_int_text(driver, "vendor_id", defaults.vendor_id),
        product_id=_optional_int_text(driver, "product_id", defaults.product_id),
        report_id=_int(driver, "report_id", defaults.report_id),
        write_method=_str(driver, "write_method", defaults.write_method),
        pad_length=_int(driver, "pad_length", defaults.pad_length),
        packet_template=_str(driver, "packet_template", defaults.packet_template),
        calibration_profile=_optional_path(
            driver,
            "calibration_profile",
            defaults.calibration_profile,
            base_dir=config_path.parent,
        ),
    )
    defaults = replace(
        defaults,
        audio_input_kind=_str(audio, "input_kind", defaults.audio_input_kind),
        audio_device_id=_optional_text(audio, "device_id", defaults.audio_device_id),
        sound_effect=_str(audio, "sound_effect", defaults.sound_effect),
        audio_sample_rate_hz=_int(audio, "sample_rate_hz", defaults.audio_sample_rate_hz),
        audio_frame_size=_int(audio, "frame_size", defaults.audio_frame_size),
        audio_sensitivity=_float(audio, "sensitivity", defaults.audio_sensitivity),
        audio_attack_alpha=_float(audio, "attack_alpha", defaults.audio_attack_alpha),
        audio_decay_alpha=_float(audio, "decay_alpha", defaults.audio_decay_alpha),
        audio_noise_floor=_float(audio, "noise_floor", defaults.audio_noise_floor),
        audio_bass_gain=_float(audio, "bass_gain", defaults.audio_bass_gain),
        audio_mid_gain=_float(audio, "mid_gain", defaults.audio_mid_gain),
        audio_treble_gain=_float(audio, "treble_gain", defaults.audio_treble_gain),
        audio_zone_layout=_str(audio, "zone_layout", defaults.audio_zone_layout),
        audio_palette=_string_tuple(audio, "palette", defaults.audio_palette),
    )
    defaults = replace(
        defaults,
        smoothing_enabled=_bool(smoothing, "enabled", defaults.smoothing_enabled),
        smoothing_alpha=_float(smoothing, "alpha", defaults.smoothing_alpha),
    )
    defaults = replace(
        defaults,
        brightness_max_percent=_int(
            brightness,
            "max_percent",
            defaults.brightness_max_percent,
        ),
    )
    defaults = replace(
        defaults,
        max_consecutive_errors=_int(
            runtime,
            "max_consecutive_errors",
            defaults.max_consecutive_errors,
        ),
        error_backoff_ms=_int(runtime, "error_backoff_ms", defaults.error_backoff_ms),
        stop_on_error=_bool(runtime, "stop_on_error", defaults.stop_on_error),
        strict_preflight=_bool(runtime, "strict_preflight", defaults.strict_preflight),
        reconnect_on_error=_bool(runtime, "reconnect_on_error", defaults.reconnect_on_error),
        reconnect_attempts=_int(runtime, "reconnect_attempts", defaults.reconnect_attempts),
        watchdog_interval_iterations=_int(
            runtime,
            "watchdog_interval_iterations",
            defaults.watchdog_interval_iterations,
        ),
        watchdog_output=_optional_path(
            runtime,
            "watchdog_output",
            defaults.watchdog_output,
            base_dir=config_path.parent,
        ),
        event_log_interval_iterations=_int(
            runtime,
            "event_log_interval_iterations",
            defaults.event_log_interval_iterations,
        ),
        event_log_output=_optional_path(
            runtime,
            "event_log_output",
            defaults.event_log_output,
            base_dir=config_path.parent,
        ),
        restore_on_exit=_bool(runtime, "restore_on_exit", defaults.restore_on_exit),
        restore_color=_str(runtime, "restore_color", defaults.restore_color),
    )
    _validate_live_defaults(defaults)
    return defaults


def _validate_live_defaults(defaults: LiveCommandDefaults) -> None:
    if defaults.mode_source not in {"screen", "sound"}:
        raise ValueError("mode.source must be 'screen' or 'sound'.")
    if defaults.capturer not in {"windows-mss", "mock"}:
        raise ValueError("capture.backend must be 'windows-mss' or 'mock'.")
    if defaults.mapper not in {"grid", "calibrated"}:
        raise ValueError("mapping.backend must be 'grid' or 'calibrated'.")
    if defaults.backend not in {"simulated", "msi-mystic-hid"}:
        raise ValueError("driver.backend must be 'simulated' or 'msi-mystic-hid'.")
    if defaults.write_method not in {"output", "feature"}:
        raise ValueError("driver.write_method must be 'output' or 'feature'.")
    if defaults.audio_input_kind not in {"output-loopback", "microphone"}:
        raise ValueError("audio.input_kind must be 'output-loopback' or 'microphone'.")
    if defaults.sound_effect not in {
        "bass-pulse",
        "spectrum",
        "stereo-split",
        "waveform",
    }:
        raise ValueError("audio.sound_effect is invalid.")
    if defaults.audio_zone_layout not in {"linear", "mirror", "center-out"}:
        raise ValueError("audio.zone_layout must be linear, mirror, or center-out.")
    if defaults.rows <= 0 or defaults.columns <= 0:
        raise ValueError("app.rows and app.columns must be positive.")
    if defaults.fps <= 0:
        raise ValueError("app.fps must be positive.")
    if defaults.iterations <= 0:
        raise ValueError("app.iterations must be positive.")
    if defaults.monitor_index < 1:
        raise ValueError("capture.monitor_index must be >= 1.")
    if defaults.capture_width <= 0 or defaults.capture_height <= 0:
        raise ValueError("capture.width and capture.height must be positive.")
    if (
        defaults.mode_source == "screen"
        and defaults.mapper == "calibrated"
        and defaults.zone_profile is None
    ):
        raise ValueError("mapping.zone_profile must be set when mapping.backend=calibrated.")
    if defaults.report_id < 0 or defaults.report_id > 255:
        raise ValueError("driver.report_id must be in range 0..255.")
    if defaults.pad_length <= 0:
        raise ValueError("driver.pad_length must be positive.")
    _validate_unit_interval(defaults.smoothing_alpha, "smoothing.alpha")
    _validate_unit_interval(defaults.audio_attack_alpha, "audio.attack_alpha")
    _validate_unit_interval(defaults.audio_decay_alpha, "audio.decay_alpha")
    _validate_unit_interval(defaults.audio_noise_floor, "audio.noise_floor")
    if defaults.brightness_max_percent < 1 or defaults.brightness_max_percent > 100:
        raise ValueError("brightness.max_percent must be in range 1..100.")
    if defaults.max_consecutive_errors <= 0:
        raise ValueError("runtime.max_consecutive_errors must be positive.")
    if defaults.error_backoff_ms < 0:
        raise ValueError("runtime.error_backoff_ms must be >= 0.")
    if defaults.reconnect_attempts < 0:
        raise ValueError("runtime.reconnect_attempts must be >= 0.")
    if defaults.watchdog_interval_iterations < 0:
        raise ValueError("runtime.watchdog_interval_iterations must be >= 0.")
    if defaults.event_log_interval_iterations < 0:
        raise ValueError("runtime.event_log_interval_iterations must be >= 0.")
    if defaults.audio_sample_rate_hz <= 0:
        raise ValueError("audio.sample_rate_hz must be positive.")
    if defaults.audio_frame_size <= 0:
        raise ValueError("audio.frame_size must be positive.")
    if defaults.audio_sensitivity <= 0:
        raise ValueError("audio.sensitivity must be positive.")
    if (
        defaults.audio_bass_gain < 0
        or defaults.audio_mid_gain < 0
        or defaults.audio_treble_gain < 0
    ):
        raise ValueError("audio gains must be >= 0.")
    _validate_rgb_triplet_text(defaults.restore_color, "runtime.restore_color")
    parse_palette_strings(defaults.audio_palette)


def _table(root: dict[str, Any], key: str) -> dict[str, Any]:
    value = root.get(key)
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    raise ValueError(f"Section '{key}' must be a TOML table.")


def _int(section: dict[str, Any], key: str, default: int) -> int:
    raw = section.get(key)
    if raw is None:
        return default
    if not isinstance(raw, int):
        raise ValueError(f"'{key}' must be an integer.")
    return raw


def _float(section: dict[str, Any], key: str, default: float) -> float:
    raw = section.get(key)
    if raw is None:
        return default
    if isinstance(raw, (float, int)) and not isinstance(raw, bool):
        return float(raw)
    raise ValueError(f"'{key}' must be a number.")


def _bool(section: dict[str, Any], key: str, default: bool) -> bool:
    raw = section.get(key)
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise ValueError(f"'{key}' must be a boolean.")
    return raw


def _str(section: dict[str, Any], key: str, default: str) -> str:
    raw = section.get(key)
    if raw is None:
        return default
    if not isinstance(raw, str):
        raise ValueError(f"'{key}' must be a string.")
    value = raw.strip()
    if value == "":
        raise ValueError(f"'{key}' must not be empty.")
    return value


def _optional_text(section: dict[str, Any], key: str, default: str | None) -> str | None:
    raw = section.get(key)
    if raw is None:
        return default
    if not isinstance(raw, str):
        raise ValueError(f"'{key}' must be a string.")
    value = raw.strip()
    if value == "":
        return None
    return value


def _optional_int_text(
    section: dict[str, Any],
    key: str,
    default: str | None,
) -> str | None:
    raw = section.get(key)
    if raw is None:
        return default
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, str):
        value = raw.strip()
        if value == "":
            return None
        return value
    raise ValueError(f"'{key}' must be an integer or string.")


def _string_tuple(
    section: dict[str, Any],
    key: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    raw = section.get(key)
    if raw is None:
        return default
    if not isinstance(raw, list):
        raise ValueError(f"'{key}' must be an array of strings.")
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"'{key}' must contain only strings.")
        stripped = item.strip()
        if stripped == "":
            raise ValueError(f"'{key}' entries must not be empty.")
        values.append(stripped)
    return tuple(values)


def _optional_path(
    section: dict[str, Any],
    key: str,
    default: Path | None,
    *,
    base_dir: Path,
) -> Path | None:
    raw = section.get(key)
    if raw is None:
        return default
    if not isinstance(raw, str):
        raise ValueError(f"'{key}' must be a string path.")
    value = raw.strip()
    if value == "":
        return None
    resolved = Path(value)
    if not resolved.is_absolute():
        resolved = (base_dir / resolved).resolve()
    return resolved


def _validate_rgb_triplet_text(value: str, key: str) -> None:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 3:
        raise ValueError(f"{key} must use RGB format R,G,B.")
    for part in parts:
        if part == "":
            raise ValueError(f"{key} contains empty color channel.")
        try:
            parsed = int(part, 10)
        except ValueError as error:
            raise ValueError(f"{key} channels must be integers.") from error
        if parsed < 0 or parsed > 255:
            raise ValueError(f"{key} channels must be in range 0..255.")


def _validate_unit_interval(value: float, key: str) -> None:
    if value < 0.0 or value > 1.0:
        raise ValueError(f"{key} must be in range 0.0..1.0.")
