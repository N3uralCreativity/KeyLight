from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

SUPPORTED_AUDIO_INPUT_KINDS = {"output-loopback", "microphone"}


@dataclass(frozen=True, slots=True)
class AudioDeviceInfo:
    id: str
    name: str
    kind: str
    is_default: bool


@dataclass(frozen=True, slots=True)
class AudioFrame:
    samples: Any
    sample_rate_hz: int
    device_id: str
    input_kind: str
    frame_size: int


@dataclass(frozen=True, slots=True)
class AudioInputConfig:
    input_kind: str = "output-loopback"
    device_id: str | None = None
    sample_rate_hz: int = 48_000
    frame_size: int = 2_048
    channels: int = 2

    def validate(self) -> None:
        if self.input_kind not in SUPPORTED_AUDIO_INPUT_KINDS:
            raise ValueError(
                "audio_input_kind must be 'output-loopback' or 'microphone'."
            )
        if self.sample_rate_hz <= 0:
            raise ValueError("audio_sample_rate_hz must be positive.")
        if self.frame_size <= 0:
            raise ValueError("audio_frame_size must be positive.")
        if self.channels <= 0:
            raise ValueError("audio channel count must be positive.")


def list_audio_devices() -> list[AudioDeviceInfo]:
    soundcard = _load_soundcard_module()
    speaker_default = _safe_name(soundcard.default_speaker())
    microphone_default = _safe_name(soundcard.default_microphone())

    devices: list[AudioDeviceInfo] = []
    for speaker in soundcard.all_speakers():
        name = _device_name(speaker)
        devices.append(
            AudioDeviceInfo(
                id=_speaker_device_id(name),
                name=name,
                kind="output-loopback",
                is_default=name == speaker_default,
            )
        )
    for microphone in soundcard.all_microphones(include_loopback=False):
        name = _device_name(microphone)
        devices.append(
            AudioDeviceInfo(
                id=_microphone_device_id(name),
                name=name,
                kind="microphone",
                is_default=name == microphone_default,
            )
        )
    return devices


class SoundCardAudioReader:
    def __init__(self, config: AudioInputConfig) -> None:
        config.validate()
        self._config = config
        self._soundcard: Any | None = None
        self._recorder: Any | None = None
        self._resolved_device: Any | None = None
        self._resolved_info: AudioDeviceInfo | None = None

    @property
    def resolved_device_info(self) -> AudioDeviceInfo | None:
        return self._resolved_info

    def read_input(self) -> AudioFrame:
        self._ensure_open()
        assert self._recorder is not None
        assert self._resolved_info is not None
        samples = self._recorder.record(numframes=self._config.frame_size)
        return AudioFrame(
            samples=samples,
            sample_rate_hz=self._config.sample_rate_hz,
            device_id=self._resolved_info.id,
            input_kind=self._config.input_kind,
            frame_size=self._config.frame_size,
        )

    def reconnect(self) -> bool:
        self.close()
        self._ensure_open()
        return True

    def close(self) -> None:
        recorder = self._recorder
        self._recorder = None
        self._resolved_device = None
        self._resolved_info = None
        if recorder is None:
            return
        exit_fn = getattr(recorder, "__exit__", None)
        if callable(exit_fn):
            exit_fn(None, None, None)
            return
        close_fn = getattr(recorder, "close", None)
        if callable(close_fn):
            close_fn()

    def _ensure_open(self) -> None:
        if self._recorder is not None:
            return
        soundcard = _load_soundcard_module()
        device, info = _resolve_audio_device(
            soundcard,
            input_kind=self._config.input_kind,
            device_id=self._config.device_id,
        )
        channels = _resolve_channel_count(device, requested=self._config.channels)
        recorder = device.recorder(
            samplerate=self._config.sample_rate_hz,
            channels=channels,
            blocksize=self._config.frame_size,
        )
        enter_fn = getattr(recorder, "__enter__", None)
        if callable(enter_fn):
            recorder = enter_fn()
        self._soundcard = soundcard
        self._resolved_device = device
        self._resolved_info = info
        self._recorder = recorder


def resolve_audio_device_id(
    *,
    input_kind: str,
    device_id: str | None,
) -> str | None:
    try:
        soundcard = _load_soundcard_module()
    except RuntimeError:
        return device_id
    _, info = _resolve_audio_device(
        soundcard,
        input_kind=input_kind,
        device_id=device_id,
    )
    return info.id


def _load_soundcard_module() -> Any:
    try:
        soundcard = importlib.import_module("soundcard")
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "Sound-reactive mode requires the SoundCard package. "
            "Install with: pip install -e \".[audio]\""
        ) from error
    _apply_soundcard_compatibility_patches()
    return soundcard


def _resolve_audio_device(
    soundcard: Any,
    *,
    input_kind: str,
    device_id: str | None,
) -> tuple[Any, AudioDeviceInfo]:
    if input_kind not in SUPPORTED_AUDIO_INPUT_KINDS:
        raise ValueError(
            "audio_input_kind must be 'output-loopback' or 'microphone'."
        )

    if input_kind == "output-loopback":
        return _resolve_output_loopback_device(soundcard, device_id=device_id)
    return _resolve_microphone_device(soundcard, device_id=device_id)


def _device_name(device: Any) -> str:
    name = getattr(device, "name", None)
    if not isinstance(name, str) or name.strip() == "":
        raise RuntimeError("SoundCard device is missing a usable name.")
    return name.strip()


def _safe_name(device: Any) -> str | None:
    if device is None:
        return None
    name = getattr(device, "name", None)
    if not isinstance(name, str):
        return None
    stripped = name.strip()
    return stripped if stripped else None


def _speaker_device_id(name: str) -> str:
    return f"speaker:{name}"


def _microphone_device_id(name: str) -> str:
    return f"microphone:{name}"


def _resolve_output_loopback_device(
    soundcard: Any,
    *,
    device_id: str | None,
) -> tuple[Any, AudioDeviceInfo]:
    speakers = list(soundcard.all_speakers())
    default_speaker = soundcard.default_speaker()
    default_name = _safe_name(default_speaker)

    requested_name = _speaker_name_from_device_id(device_id)
    chosen_name = requested_name or default_name
    if chosen_name is None and speakers:
        chosen_name = _device_name(speakers[0])

    if chosen_name is None:
        raise RuntimeError("No output-loopback audio devices are available.")

    recorder_device = _lookup_loopback_microphone(soundcard, chosen_name)
    if recorder_device is None:
        fallback = _first_loopback_microphone(soundcard)
        if fallback is None:
            raise RuntimeError("No output-loopback audio devices are available.")
        recorder_device = fallback
        chosen_name = _device_name(fallback)

    return (
        recorder_device,
        AudioDeviceInfo(
            id=_speaker_device_id(chosen_name),
            name=chosen_name,
            kind="output-loopback",
            is_default=chosen_name == default_name,
        ),
    )


def _resolve_microphone_device(
    soundcard: Any,
    *,
    device_id: str | None,
) -> tuple[Any, AudioDeviceInfo]:
    microphones = list(soundcard.all_microphones(include_loopback=False))
    default_microphone = soundcard.default_microphone()
    default_name = _safe_name(default_microphone)

    chosen = default_microphone
    if device_id is not None and device_id.strip() != "":
        for microphone in microphones:
            name = _device_name(microphone)
            if _microphone_device_id(name) == device_id.strip():
                chosen = microphone
                break

    if chosen is None:
        if microphones:
            chosen = microphones[0]
        else:
            raise RuntimeError("No microphone audio devices are available.")

    chosen_name = _device_name(chosen)
    return (
        chosen,
        AudioDeviceInfo(
            id=_microphone_device_id(chosen_name),
            name=chosen_name,
            kind="microphone",
            is_default=chosen_name == default_name,
        ),
    )


def _speaker_name_from_device_id(device_id: str | None) -> str | None:
    if device_id is None:
        return None
    text = device_id.strip()
    if text == "":
        return None
    prefix = "speaker:"
    if text.lower().startswith(prefix):
        name = text[len(prefix) :].strip()
        return name or None
    return text


def _lookup_loopback_microphone(soundcard: Any, speaker_name: str) -> Any | None:
    get_microphone = getattr(soundcard, "get_microphone", None)
    if callable(get_microphone):
        try:
            microphone = get_microphone(speaker_name, include_loopback=True)
        except Exception:
            microphone = None
        else:
            if microphone is not None:
                return microphone

    for microphone in _all_microphones_with_loopback(soundcard):
        if _device_name(microphone) == speaker_name and bool(
            getattr(microphone, "isloopback", False)
        ):
            return microphone
    return None


def _first_loopback_microphone(soundcard: Any) -> Any | None:
    for microphone in _all_microphones_with_loopback(soundcard):
        if bool(getattr(microphone, "isloopback", False)):
            return microphone
    return None


def _all_microphones_with_loopback(soundcard: Any) -> list[Any]:
    try:
        return list(soundcard.all_microphones(include_loopback=True))
    except TypeError:
        return list(soundcard.all_microphones())


def _resolve_channel_count(device: Any, *, requested: int) -> int:
    available = getattr(device, "channels", None)
    if not isinstance(available, int) or available <= 0:
        return requested
    return min(requested, available)


def _apply_soundcard_compatibility_patches() -> None:
    try:
        mediafoundation = importlib.import_module("soundcard.mediafoundation")
    except ModuleNotFoundError:
        return

    if bool(getattr(mediafoundation, "_keylight_numpy_binary_fromstring_patch", False)):
        return

    numpy_module = getattr(mediafoundation, "numpy", None)
    if numpy_module is None:
        return

    try:
        numpy_module.fromstring(b"\x00\x00\x00\x00", dtype="float32")
    except ValueError as error:
        if "binary mode of fromstring is removed" not in str(error):
            return
        mediafoundation.numpy = _NumpyCompatProxy(numpy_module)
        mediafoundation._keylight_numpy_binary_fromstring_patch = True
    except Exception:
        return


class _NumpyCompatProxy:
    def __init__(self, numpy_module: Any) -> None:
        self._numpy = numpy_module

    def fromstring(
        self,
        obj: Any,
        dtype: Any = float,
        count: int = -1,
        sep: str = "",
        *,
        like: Any = None,
    ) -> Any:
        if sep not in {"", None}:
            return self._numpy.fromstring(
                obj,
                dtype=dtype,
                count=count,
                sep=sep,
                like=like,
            )
        return self._numpy.frombuffer(
            obj,
            dtype=dtype,
            count=count,
            like=like,
        ).copy()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._numpy, name)
