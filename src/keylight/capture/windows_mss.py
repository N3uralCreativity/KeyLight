from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from keylight.models import CapturedFrame, RgbColor


@dataclass(frozen=True, slots=True)
class MonitorInfo:
    index: int
    width: int
    height: int
    left: int
    top: int


def list_monitors() -> list[MonitorInfo]:
    mss_module = _load_mss_module()
    with mss_module.mss() as session:
        monitors: list[MonitorInfo] = []
        for index, monitor in enumerate(session.monitors):
            monitors.append(
                MonitorInfo(
                    index=index,
                    width=int(monitor["width"]),
                    height=int(monitor["height"]),
                    left=int(monitor["left"]),
                    top=int(monitor["top"]),
                )
            )
        return monitors


class WindowsMssCapturer:
    """Windows desktop capturer using mss with nearest-neighbor downsampling."""

    def __init__(
        self,
        *,
        monitor_index: int = 1,
        target_width: int = 120,
        target_height: int = 20,
    ) -> None:
        if monitor_index < 1:
            raise ValueError("monitor_index must be >= 1 (mss monitor 0 is all displays).")
        if target_width <= 0 or target_height <= 0:
            raise ValueError("target_width and target_height must be positive.")
        self._monitor_index = monitor_index
        self._target_width = target_width
        self._target_height = target_height
        self._session: Any | None = None
        self._mss_module: Any | None = None

    def capture_frame(self) -> CapturedFrame:
        session = self._ensure_session()
        monitors = session.monitors
        if self._monitor_index >= len(monitors):
            raise ValueError(
                f"monitor_index {self._monitor_index} unavailable; "
                f"monitor count is {len(monitors) - 1}."
            )
        monitor = monitors[self._monitor_index]
        shot = session.grab(monitor)
        src_width = int(shot.width)
        src_height = int(shot.height)
        raw: bytes = shot.raw

        pixels: list[list[RgbColor]] = []
        for y in range(self._target_height):
            src_y = y * src_height // self._target_height
            row: list[RgbColor] = []
            for x in range(self._target_width):
                src_x = x * src_width // self._target_width
                idx = (src_y * src_width + src_x) * 4
                blue = raw[idx]
                green = raw[idx + 1]
                red = raw[idx + 2]
                row.append(RgbColor(red, green, blue))
            pixels.append(row)

        return CapturedFrame(width=self._target_width, height=self._target_height, pixels=pixels)

    def close(self) -> None:
        if self._session is None:
            return
        close_fn = getattr(self._session, "close", None)
        if callable(close_fn):
            close_fn()
        self._session = None

    def _ensure_session(self) -> Any:
        if self._session is not None:
            return self._session
        mss_module = _load_mss_module()
        self._mss_module = mss_module
        self._session = mss_module.mss()
        return self._session


def _load_mss_module() -> Any:
    try:
        import mss
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "Windows mss capture requires package 'mss'. Install with: pip install mss"
        ) from error
    return mss
