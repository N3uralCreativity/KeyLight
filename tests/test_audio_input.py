import types

from keylight.audio_input import (
    AudioInputConfig,
    SoundCardAudioReader,
    _apply_soundcard_compatibility_patches,
    _NumpyCompatProxy,
    list_audio_devices,
)


class _FakeRecorder:
    def __init__(self, samples: list[list[float]]) -> None:
        self._samples = samples
        self.closed = False

    def __enter__(self) -> "_FakeRecorder":
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True

    def record(self, *, numframes: int) -> list[list[float]]:
        return self._samples[:numframes]


class _FakeDevice:
    def __init__(self, name: str, samples: list[list[float]], *, channels: int = 2) -> None:
        self.name = name
        self._samples = samples
        self.channels = channels
        self.isloopback = False
        self.recorder_calls: list[dict[str, object]] = []

    def recorder(self, **_kwargs: object) -> _FakeRecorder:
        self.recorder_calls.append(dict(_kwargs))
        return _FakeRecorder(self._samples)


def test_list_audio_devices_builds_stable_ids(monkeypatch) -> None:
    soundcard = types.SimpleNamespace(
        all_speakers=lambda: [
            _FakeDevice("Main Speakers", [[0.1, 0.2]]),
            _FakeDevice("Desk Speakers", [[0.1, 0.2]]),
        ],
        all_microphones=lambda include_loopback=False: [
            _FakeDevice("Room Mic", [[0.1]]),
        ],
        default_speaker=lambda: _FakeDevice("Desk Speakers", [[0.1, 0.2]]),
        default_microphone=lambda: _FakeDevice("Room Mic", [[0.1]]),
    )
    monkeypatch.setattr("keylight.audio_input._load_soundcard_module", lambda: soundcard)

    devices = list_audio_devices()

    assert [device.id for device in devices] == [
        "speaker:Main Speakers",
        "speaker:Desk Speakers",
        "microphone:Room Mic",
    ]
    assert devices[1].is_default is True
    assert devices[2].is_default is True


def test_soundcard_reader_falls_back_to_default_device(monkeypatch) -> None:
    speaker = _FakeDevice("Desk Speakers", [[0.1, 0.2], [0.3, 0.4]])
    loopback = _FakeDevice("Desk Speakers", [[0.1, 0.2], [0.3, 0.4]])
    loopback.isloopback = True
    soundcard = types.SimpleNamespace(
        all_speakers=lambda: [speaker],
        all_microphones=lambda include_loopback=False: [loopback] if include_loopback else [],
        default_speaker=lambda: speaker,
        default_microphone=lambda: None,
        get_microphone=lambda name, include_loopback=False: loopback
        if include_loopback and name == "Desk Speakers"
        else None,
    )
    monkeypatch.setattr("keylight.audio_input._load_soundcard_module", lambda: soundcard)

    reader = SoundCardAudioReader(
        AudioInputConfig(
            input_kind="output-loopback",
            device_id="speaker:Missing Device",
            sample_rate_hz=48_000,
            frame_size=2,
        )
    )

    frame = reader.read_input()

    assert frame.device_id == "speaker:Desk Speakers"
    assert frame.sample_rate_hz == 48_000
    assert frame.frame_size == 2
    reader.close()


def test_soundcard_reader_clamps_channels_to_device_capability(monkeypatch) -> None:
    microphone = _FakeDevice("Room Mic", [[0.1], [0.2]], channels=1)
    soundcard = types.SimpleNamespace(
        all_speakers=lambda: [],
        all_microphones=lambda include_loopback=False: [microphone],
        default_speaker=lambda: None,
        default_microphone=lambda: microphone,
    )
    monkeypatch.setattr("keylight.audio_input._load_soundcard_module", lambda: soundcard)

    reader = SoundCardAudioReader(
        AudioInputConfig(
            input_kind="microphone",
            sample_rate_hz=48_000,
            frame_size=2,
            channels=2,
        )
    )

    reader.read_input()

    assert microphone.recorder_calls == [
        {
            "samplerate": 48_000,
            "channels": 1,
            "blocksize": 2,
        }
    ]
    reader.close()


def test_apply_soundcard_compatibility_patches_wraps_binary_fromstring(monkeypatch) -> None:
    class _BrokenArray:
        def __init__(self, payload: str) -> None:
            self._payload = payload

        def copy(self) -> str:
            return self._payload

    class _BrokenNumpy:
        def __init__(self) -> None:
            self.frombuffer_calls: list[tuple[object, object, int, object]] = []

        def fromstring(
            self,
            obj: object,
            dtype: object = float,
            count: int = -1,
            sep: str = "",
            *,
            like: object = None,
        ) -> object:
            if sep in {"", None}:
                raise ValueError("The binary mode of fromstring is removed, use frombuffer instead")
            return ("text", obj, dtype, count, sep, like)

        def frombuffer(
            self,
            obj: object,
            dtype: object = float,
            count: int = -1,
            offset: int = 0,
            *,
            like: object = None,
        ) -> _BrokenArray:
            assert offset == 0
            self.frombuffer_calls.append((obj, dtype, count, like))
            return _BrokenArray("patched-result")

    broken_numpy = _BrokenNumpy()
    mediafoundation = types.SimpleNamespace(numpy=broken_numpy)

    def _fake_import_module(name: str) -> object:
        if name == "soundcard.mediafoundation":
            return mediafoundation
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("keylight.audio_input.importlib.import_module", _fake_import_module)

    _apply_soundcard_compatibility_patches()

    assert mediafoundation._keylight_numpy_binary_fromstring_patch is True
    assert isinstance(mediafoundation.numpy, _NumpyCompatProxy)
    assert mediafoundation.numpy.fromstring(b"abcd", dtype="float32") == "patched-result"
    assert broken_numpy.frombuffer_calls == [(b"abcd", "float32", -1, None)]
