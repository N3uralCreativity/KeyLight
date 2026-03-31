from __future__ import annotations

import importlib
import math
from dataclasses import dataclass, field
from typing import Any

from keylight.audio_input import AudioFrame
from keylight.models import RgbColor, ZoneColor

SUPPORTED_SOUND_EFFECTS = {
    "spectrum",
    "bass-pulse",
    "waveform",
    "stereo-split",
}
SUPPORTED_ZONE_LAYOUTS = {"linear", "mirror", "center-out"}
DEFAULT_PALETTE = (
    "0,80,255",
    "0,255,160",
    "255,200,0",
    "255,60,60",
)


@dataclass(frozen=True, slots=True)
class SoundReactiveConfig:
    rows: int = 2
    columns: int = 12
    effect: str = "spectrum"
    sensitivity: float = 1.0
    attack_alpha: float = 0.55
    decay_alpha: float = 0.2
    noise_floor: float = 0.02
    bass_gain: float = 1.3
    mid_gain: float = 1.0
    treble_gain: float = 1.0
    zone_layout: str = "linear"
    palette: tuple[RgbColor, ...] = field(
        default_factory=lambda: parse_palette_strings(DEFAULT_PALETTE)
    )

    def validate(self) -> None:
        if self.rows <= 0 or self.columns <= 0:
            raise ValueError("rows and columns must be positive.")
        if self.effect not in SUPPORTED_SOUND_EFFECTS:
            raise ValueError(
                "sound_effect must be one of bass-pulse, spectrum, stereo-split, waveform."
            )
        if self.zone_layout not in SUPPORTED_ZONE_LAYOUTS:
            raise ValueError("audio_zone_layout must be linear, mirror, or center-out.")
        if self.sensitivity <= 0:
            raise ValueError("audio_sensitivity must be positive.")
        _validate_unit_interval(self.attack_alpha, "audio_attack_alpha")
        _validate_unit_interval(self.decay_alpha, "audio_decay_alpha")
        _validate_unit_interval(self.noise_floor, "audio_noise_floor")
        if self.bass_gain < 0 or self.mid_gain < 0 or self.treble_gain < 0:
            raise ValueError("audio gains must be >= 0.")
        if len(self.palette) < 2 or len(self.palette) > 8:
            raise ValueError("audio_palette must define 2..8 colors.")


class SoundReactiveRenderer:
    def __init__(self, config: SoundReactiveConfig) -> None:
        config.validate()
        self._config = config
        self._column_levels = [0.0] * config.columns
        self._wave_history = [0.0] * config.columns
        self._pulse_level = 0.0
        self._stereo_levels = [0.0, 0.0]

    @property
    def zone_count(self) -> int:
        return self._config.rows * self._config.columns

    def render(self, payload: object) -> list[ZoneColor]:
        if not isinstance(payload, AudioFrame):
            raise TypeError("SoundReactiveRenderer requires AudioFrame input.")
        numpy = _load_numpy_module()
        samples = numpy.asarray(payload.samples, dtype=float)
        if samples.ndim == 1:
            samples = samples.reshape((-1, 1))
        if samples.shape[0] == 0:
            return self._uniform_black()

        if self._config.effect == "spectrum":
            column_levels = self._render_spectrum(samples, payload.sample_rate_hz, numpy)
        elif self._config.effect == "bass-pulse":
            column_levels = self._render_bass_pulse(samples, payload.sample_rate_hz, numpy)
        elif self._config.effect == "waveform":
            column_levels = self._render_waveform(samples, numpy)
        else:
            column_levels = self._render_stereo_split(samples, payload.sample_rate_hz, numpy)

        colors = [self._palette_color(level) for level in column_levels]
        return self._expand_columns(colors)

    def _render_spectrum(self, samples: Any, sample_rate_hz: int, numpy: Any) -> list[float]:
        mono = numpy.mean(samples, axis=1)
        if mono.size == 0:
            return [0.0] * self._config.columns
        windowed = mono * numpy.hanning(mono.size)
        magnitudes = numpy.abs(numpy.fft.rfft(windowed))
        frequencies = numpy.fft.rfftfreq(mono.size, d=1.0 / sample_rate_hz)

        if self._config.zone_layout == "mirror":
            band_count = math.ceil(self._config.columns / 2)
        else:
            band_count = self._config.columns
        edges = numpy.geomspace(20.0, max(sample_rate_hz / 2, 21.0), band_count + 1)

        values: list[float] = []
        for index in range(band_count):
            lower = float(edges[index])
            upper = float(edges[index + 1])
            mask = (frequencies >= lower) & (frequencies < upper)
            if not numpy.any(mask):
                raw_value = 0.0
            else:
                band = magnitudes[mask]
                center = (lower + upper) / 2.0
                gain = self._gain_for_frequency(center)
                raw_value = float(numpy.mean(band)) * gain
            values.append(self._normalize_level(raw_value))

        arranged = self._arrange_columns(values)
        return self._smooth_columns(arranged)

    def _render_bass_pulse(self, samples: Any, sample_rate_hz: int, numpy: Any) -> list[float]:
        mono = numpy.mean(samples, axis=1)
        if mono.size == 0:
            return [0.0] * self._config.columns
        windowed = mono * numpy.hanning(mono.size)
        magnitudes = numpy.abs(numpy.fft.rfft(windowed))
        frequencies = numpy.fft.rfftfreq(mono.size, d=1.0 / sample_rate_hz)
        mask = (frequencies >= 20.0) & (frequencies < 250.0)
        if numpy.any(mask):
            raw_value = float(numpy.mean(magnitudes[mask])) * self._config.bass_gain
        else:
            raw_value = 0.0
        target = self._normalize_level(raw_value)
        self._pulse_level = self._smooth_value(self._pulse_level, target)
        return [self._pulse_level] * self._config.columns

    def _render_waveform(self, samples: Any, numpy: Any) -> list[float]:
        if samples.size == 0:
            return [0.0] * self._config.columns
        amplitude = float(numpy.mean(numpy.abs(samples)))
        target = self._normalize_level(amplitude)
        self._wave_history = self._wave_history[1:] + [target]
        smoothed = [
            self._smooth_value(previous, current)
            for previous, current in zip(self._column_levels, self._wave_history, strict=False)
        ]
        self._column_levels = smoothed
        return smoothed

    def _render_stereo_split(
        self,
        samples: Any,
        sample_rate_hz: int,
        numpy: Any,
    ) -> list[float]:
        if samples.shape[1] == 1:
            left = samples[:, 0]
            right = samples[:, 0]
        else:
            left = samples[:, 0]
            right = samples[:, 1]
        left_level = self._channel_energy(left, sample_rate_hz, numpy)
        right_level = self._channel_energy(right, sample_rate_hz, numpy)
        self._stereo_levels[0] = self._smooth_value(self._stereo_levels[0], left_level)
        self._stereo_levels[1] = self._smooth_value(self._stereo_levels[1], right_level)

        midpoint = self._config.columns // 2
        columns: list[float] = []
        for index in range(self._config.columns):
            if index < midpoint:
                columns.append(self._stereo_levels[0])
            else:
                columns.append(self._stereo_levels[1])
        if self._config.columns % 2 == 1 and midpoint < len(columns):
            columns[midpoint] = max(self._stereo_levels)
        return columns

    def _channel_energy(self, samples: Any, sample_rate_hz: int, numpy: Any) -> float:
        if samples.size == 0:
            return 0.0
        windowed = samples * numpy.hanning(samples.size)
        magnitudes = numpy.abs(numpy.fft.rfft(windowed))
        frequencies = numpy.fft.rfftfreq(samples.size, d=1.0 / sample_rate_hz)
        weighted = magnitudes.copy()
        bass_mask = frequencies < 250.0
        mid_mask = (frequencies >= 250.0) & (frequencies < 2000.0)
        treble_mask = frequencies >= 2000.0
        weighted[bass_mask] *= self._config.bass_gain
        weighted[mid_mask] *= self._config.mid_gain
        weighted[treble_mask] *= self._config.treble_gain
        return self._normalize_level(float(numpy.mean(weighted)) if weighted.size else 0.0)

    def _expand_columns(self, column_colors: list[RgbColor]) -> list[ZoneColor]:
        zones: list[ZoneColor] = []
        zone_index = 0
        for _row in range(self._config.rows):
            for color in column_colors:
                zones.append(ZoneColor(zone_index=zone_index, color=color))
                zone_index += 1
        return zones

    def _uniform_black(self) -> list[ZoneColor]:
        return self._expand_columns([RgbColor.black()] * self._config.columns)

    def _arrange_columns(self, values: list[float]) -> list[float]:
        if self._config.zone_layout == "linear":
            if len(values) == self._config.columns:
                return values
            return (values + [values[-1]] * self._config.columns)[: self._config.columns]

        if self._config.zone_layout == "mirror":
            arranged: list[float] = []
            for index in range(self._config.columns):
                mirrored_index = min(index, self._config.columns - 1 - index)
                arranged.append(values[min(mirrored_index, len(values) - 1)])
            return arranged

        positions = _center_out_positions(self._config.columns)
        arranged = [0.0] * self._config.columns
        for source_index, position in enumerate(positions):
            if source_index >= len(values):
                break
            arranged[position] = values[source_index]
        return arranged

    def _smooth_columns(self, values: list[float]) -> list[float]:
        smoothed = [
            self._smooth_value(previous, current)
            for previous, current in zip(self._column_levels, values, strict=False)
        ]
        self._column_levels = smoothed
        return smoothed

    def _smooth_value(self, previous: float, current: float) -> float:
        alpha = self._config.attack_alpha if current >= previous else self._config.decay_alpha
        return max(0.0, min(1.0, previous + ((current - previous) * alpha)))

    def _normalize_level(self, value: float) -> float:
        adjusted = max(0.0, value * self._config.sensitivity)
        if adjusted <= self._config.noise_floor:
            return 0.0
        normalized = (adjusted - self._config.noise_floor) / max(
            1e-6, 1.0 - self._config.noise_floor
        )
        return max(0.0, min(1.0, normalized))

    def _gain_for_frequency(self, frequency_hz: float) -> float:
        if frequency_hz < 250.0:
            return self._config.bass_gain
        if frequency_hz < 2000.0:
            return self._config.mid_gain
        return self._config.treble_gain

    def _palette_color(self, level: float) -> RgbColor:
        if level <= 0.0:
            return RgbColor.black()
        palette = self._config.palette
        scaled = level * (len(palette) - 1)
        lower_index = int(math.floor(scaled))
        upper_index = min(lower_index + 1, len(palette) - 1)
        blend = scaled - lower_index
        lower = palette[lower_index]
        upper = palette[upper_index]
        return RgbColor(
            r=int(lower.r + ((upper.r - lower.r) * blend)),
            g=int(lower.g + ((upper.g - lower.g) * blend)),
            b=int(lower.b + ((upper.b - lower.b) * blend)),
        ).clamped()


def parse_palette_strings(values: tuple[str, ...] | list[str]) -> tuple[RgbColor, ...]:
    palette = tuple(_parse_palette_entry(value) for value in values)
    if len(palette) < 2 or len(palette) > 8:
        raise ValueError("audio.palette must define 2..8 RGB entries.")
    return palette


def format_palette_strings(palette: tuple[RgbColor, ...] | list[RgbColor]) -> tuple[str, ...]:
    return tuple(f"{color.r},{color.g},{color.b}" for color in palette)


def _parse_palette_entry(value: str) -> RgbColor:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 3:
        raise ValueError("audio.palette entries must use RGB format R,G,B.")
    try:
        red, green, blue = (int(part, 10) for part in parts)
    except ValueError as error:
        raise ValueError("audio.palette entries must use integer RGB channels.") from error
    for channel in (red, green, blue):
        if channel < 0 or channel > 255:
            raise ValueError("audio.palette RGB channels must be in range 0..255.")
    return RgbColor(red, green, blue)


def _center_out_positions(count: int) -> list[int]:
    if count <= 0:
        return []
    if count % 2 == 0:
        left = (count // 2) - 1
        right = count // 2
        positions = [left, right]
        offset = 1
        while len(positions) < count:
            if left - offset >= 0:
                positions.append(left - offset)
            if right + offset < count:
                positions.append(right + offset)
            offset += 1
        return positions[:count]

    center = count // 2
    positions = [center]
    offset = 1
    while len(positions) < count:
        if center - offset >= 0:
            positions.append(center - offset)
        if center + offset < count:
            positions.append(center + offset)
        offset += 1
    return positions[:count]


def _load_numpy_module() -> Any:
    try:
        return importlib.import_module("numpy")
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "Sound-reactive mode requires numpy. Install with: pip install -e \".[audio]\""
        ) from error


def _validate_unit_interval(value: float, key: str) -> None:
    if value < 0.0 or value > 1.0:
        raise ValueError(f"{key} must be in range 0.0..1.0.")
