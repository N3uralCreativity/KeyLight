from __future__ import annotations

from pathlib import Path

from keylight.runtime_config import LiveCommandDefaults


def render_live_defaults_toml(defaults: LiveCommandDefaults, *, output_path: Path) -> str:
    output_dir = output_path.parent.resolve()
    palette_items = ", ".join(
        f'"{_escape_toml(value)}"' for value in defaults.audio_palette
    )
    lines = [
        "[app]",
        f"fps = {defaults.fps}",
        f"rows = {defaults.rows}",
        f"columns = {defaults.columns}",
        f"iterations = {defaults.iterations}",
        "",
        "[mode]",
        f'source = "{_escape_toml(defaults.mode_source)}"',
        "",
        "[capture]",
        f'backend = "{_escape_toml(defaults.capturer)}"',
        f"monitor_index = {defaults.monitor_index}",
        f"width = {defaults.capture_width}",
        f"height = {defaults.capture_height}",
        "",
        "[mapping]",
        f'backend = "{_escape_toml(defaults.mapper)}"',
        f'zone_profile = "{_escape_toml(_path_text(defaults.zone_profile, base_dir=output_dir))}"',
        "",
        "[driver]",
        f'backend = "{_escape_toml(defaults.backend)}"',
        f'hid_path = "{_escape_toml(defaults.hid_path or "")}"',
        f'vendor_id = "{_escape_toml(defaults.vendor_id or "")}"',
        f'product_id = "{_escape_toml(defaults.product_id or "")}"',
        f"report_id = {defaults.report_id}",
        f'write_method = "{_escape_toml(defaults.write_method)}"',
        f"pad_length = {defaults.pad_length}",
        f'packet_template = "{_escape_toml(defaults.packet_template)}"',
        (
            'calibration_profile = "'
            f'{_escape_toml(_path_text(defaults.calibration_profile, base_dir=output_dir))}"'
        ),
        "",
        "[audio]",
        f'input_kind = "{_escape_toml(defaults.audio_input_kind)}"',
        f'device_id = "{_escape_toml(defaults.audio_device_id or "")}"',
        f'sound_effect = "{_escape_toml(defaults.sound_effect)}"',
        f"sample_rate_hz = {defaults.audio_sample_rate_hz}",
        f"frame_size = {defaults.audio_frame_size}",
        f"sensitivity = {defaults.audio_sensitivity}",
        f"attack_alpha = {defaults.audio_attack_alpha}",
        f"decay_alpha = {defaults.audio_decay_alpha}",
        f"noise_floor = {defaults.audio_noise_floor}",
        f"bass_gain = {defaults.audio_bass_gain}",
        f"mid_gain = {defaults.audio_mid_gain}",
        f"treble_gain = {defaults.audio_treble_gain}",
        f'zone_layout = "{_escape_toml(defaults.audio_zone_layout)}"',
        f"palette = [{palette_items}]",
        "",
        "[smoothing]",
        f"enabled = {_toml_bool(defaults.smoothing_enabled)}",
        f"alpha = {defaults.smoothing_alpha}",
        "",
        "[brightness]",
        f"max_percent = {defaults.brightness_max_percent}",
        "",
        "[runtime]",
        f"max_consecutive_errors = {defaults.max_consecutive_errors}",
        f"error_backoff_ms = {defaults.error_backoff_ms}",
        f"stop_on_error = {_toml_bool(defaults.stop_on_error)}",
        f"strict_preflight = {_toml_bool(defaults.strict_preflight)}",
        f"reconnect_on_error = {_toml_bool(defaults.reconnect_on_error)}",
        f"reconnect_attempts = {defaults.reconnect_attempts}",
        f"watchdog_interval_iterations = {defaults.watchdog_interval_iterations}",
        (
            'watchdog_output = "'
            f'{_escape_toml(_path_text(defaults.watchdog_output, base_dir=output_dir))}"'
        ),
        f"event_log_interval_iterations = {defaults.event_log_interval_iterations}",
        (
            'event_log_output = "'
            f'{_escape_toml(_path_text(defaults.event_log_output, base_dir=output_dir))}"'
        ),
        f"restore_on_exit = {_toml_bool(defaults.restore_on_exit)}",
        f'restore_color = "{_escape_toml(defaults.restore_color)}"',
    ]
    return "\n".join(lines) + "\n"


def write_live_defaults_toml(defaults: LiveCommandDefaults, output_path: Path) -> Path:
    content = render_live_defaults_toml(defaults, output_path=output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def _path_text(path: Path | None, *, base_dir: Path) -> str:
    if path is None:
        return ""

    raw = path
    if raw.is_absolute():
        try:
            return raw.resolve().relative_to(base_dir).as_posix()
        except ValueError:
            return raw.resolve().as_posix()
    return raw.as_posix()


def _escape_toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"
