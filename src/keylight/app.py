
from __future__ import annotations

import argparse
import importlib
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from keylight.audio_input import list_audio_devices
from keylight.drivers.hid_raw import HidDeviceInfo, list_hid_devices
from keylight.runtime_config import LiveCommandDefaults, load_live_command_defaults
from keylight.runtime_config_writer import write_live_defaults_toml
from keylight.sound_reactive import DEFAULT_PALETTE

RUN_UNTIL_STOP_ITERATIONS = 2_000_000_000
TRAY_ICON_SIZE = 64
MSI_BRAND_ICON_RELATIVE_PATH = Path("docs") / "vect image-removebg-preview (1).svg"
MSI_BRAND_ICON_SIZE = 56
UI_REVEAL_STEP_MS = 90
HERO_ACCENT_INTERVAL_MS = 30
STATUS_PULSE_INTERVAL_MS = 650
STOP_FORCE_KILL_TIMEOUT_MS = 2500


@dataclass(frozen=True, slots=True)
class AppLiveRunConfig:
    config_path: Path
    output_path: Path

    def validate(self) -> None:
        config_text = str(self.config_path).strip()
        if config_text in {"", "."}:
            raise ValueError("Config path is required.")


def select_preferred_msi_hid_path(devices: list[HidDeviceInfo]) -> str | None:
    candidates = [
        device
        for device in devices
        if device.vendor_id == 0x1462 and device.product_id == 0x1603
    ]
    if not candidates:
        return None
    exact = [
        device
        for device in candidates
        if device.usage_page == 0x00FF and device.usage == 0x0001 and device.path.strip() != ""
    ]
    if exact:
        return exact[0].path
    with_path = [device for device in candidates if device.path.strip() != ""]
    if with_path:
        return with_path[0].path
    return None


def build_live_command(
    *,
    python_executable: str,
    config: AppLiveRunConfig,
) -> list[str]:
    config.validate()
    command = [
        python_executable,
        "-m",
        "keylight.cli",
        "live",
        "--config",
        str(config.config_path),
        "--output",
        str(config.output_path),
    ]
    return command


def _build_main_window_class(qtwidgets: Any) -> type[Any]:
    class _KeyLightMainWindow(qtwidgets.QMainWindow):
        def __init__(self, owner: KeyLightDesktopApp) -> None:
            super().__init__()
            self._owner = owner

        def closeEvent(self, event: Any) -> None:
            self._owner._on_close_requested(event)

    return _KeyLightMainWindow


class KeyLightDesktopApp:
    def __init__(
        self,
        *,
        app: Any,
        repo_root: Path,
        qtcore: Any,
        qtgui: Any,
        qtwidgets: Any,
        qtsvg: Any | None,
        autostart: bool = True,
        tray_enabled: bool = True,
        start_hidden: bool = True,
    ) -> None:
        self._app = app
        self._repo_root = repo_root
        self._QtCore = qtcore
        self._QtGui = qtgui
        self._QtWidgets = qtwidgets
        self._QtSvg = qtsvg
        self._tray_enabled = tray_enabled

        defaults = self._load_defaults(repo_root / "config" / "default.toml")
        self._defaults = defaults

        self._hid_path_input: Any
        self._mode_input: Any
        self._rows_input: Any
        self._columns_input: Any
        self._fps_input: Any
        self._iterations_input: Any
        self._monitor_input: Any
        self._audio_source_input: Any
        self._audio_device_input: Any
        self._sound_effect_input: Any
        self._audio_zone_layout_input: Any
        self._audio_sample_rate_input: Any
        self._audio_frame_size_input: Any
        self._audio_sensitivity_input: Any
        self._audio_attack_alpha_input: Any
        self._audio_decay_alpha_input: Any
        self._audio_noise_floor_input: Any
        self._audio_bass_gain_input: Any
        self._audio_mid_gain_input: Any
        self._audio_treble_gain_input: Any
        self._audio_palette_input: Any
        self._strict_check: Any
        self._run_until_stop_check: Any
        self._start_button: Any
        self._save_button: Any
        self._stop_button: Any
        self._hide_button: Any
        self._status_badge: Any
        self._runtime_status_value: Any
        self._apply_hint_label: Any
        self._log_widget: Any
        self._hero_accent_track: Any
        self._hero_accent_glow: Any
        self._screen_card: Any
        self._sound_source_card: Any
        self._sound_effect_card: Any

        self._tray_icon: Any | None = None
        self._tray_pause_action: Any | None = None
        self._tray_resume_action: Any | None = None
        self._window_visible = True
        self._shutting_down = False

        self._process: Any | None = None
        self._process_buffer = ""
        self._stop_in_progress = False
        self._force_stop_timer: Any | None = None

        self._reveal_animations: list[Any] = []
        self._accent_offset = 0
        self._accent_direction = 1
        self._status_pulse_phase = False
        self._animations_enabled = True

        main_window_class = _build_main_window_class(self._QtWidgets)
        self._window = main_window_class(self)
        self._build_ui(defaults)
        self._setup_tray_if_available()

        self._window.show()
        self._set_running(False)

        if start_hidden and self._tray_icon is not None:
            self._QtCore.QTimer.singleShot(220, self._hide_to_tray)

        if autostart:
            self._QtCore.QTimer.singleShot(500, self._autostart_if_possible)

        self._start_ui_animations()

    def _load_defaults(self, config_path: Path) -> LiveCommandDefaults:
        return load_live_command_defaults(config_path)

    def _build_ui(self, defaults: LiveCommandDefaults) -> None:
        self._window.setWindowTitle("KeyLight Studio")
        self._window.resize(1240, 760)
        self._window.setMinimumSize(1020, 640)

        root = self._QtWidgets.QWidget()
        root.setObjectName("Root")
        self._window.setCentralWidget(root)
        self._window.setStyleSheet(self._build_stylesheet())

        main_layout = self._QtWidgets.QVBoxLayout(root)
        main_layout.setContentsMargins(14, 14, 14, 12)
        main_layout.setSpacing(10)

        hero_card = self._QtWidgets.QFrame()
        hero_card.setObjectName("HeroCard")
        hero_layout = self._QtWidgets.QHBoxLayout(hero_card)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(12)

        brand_block = self._QtWidgets.QLabel()
        brand_block.setObjectName("BrandBlock")
        brand_pixmap = self._load_brand_pixmap(MSI_BRAND_ICON_SIZE)
        brand_block.setPixmap(brand_pixmap)
        brand_block.setFixedSize(MSI_BRAND_ICON_SIZE, MSI_BRAND_ICON_SIZE)
        brand_block.setScaledContents(True)
        hero_layout.addWidget(brand_block, 0, self._QtCore.Qt.AlignmentFlag.AlignVCenter)

        title_wrap = self._QtWidgets.QWidget()
        title_layout = self._QtWidgets.QVBoxLayout(title_wrap)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(4)

        title = self._QtWidgets.QLabel("KeyLight Studio")
        title.setObjectName("TitleLabel")
        subtitle = self._QtWidgets.QLabel(
            "MSI zone lighting control with live capture and diagnostics"
        )
        subtitle.setObjectName("SubtitleLabel")
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)

        hero_layout.addWidget(title_wrap, 1)

        self._status_badge = self._QtWidgets.QLabel("Idle")
        self._status_badge.setObjectName("StatusBadge")
        self._status_badge.setProperty("state", "idle")
        hero_layout.addWidget(
            self._status_badge,
            0,
            self._QtCore.Qt.AlignmentFlag.AlignRight | self._QtCore.Qt.AlignmentFlag.AlignVCenter,
        )

        main_layout.addWidget(hero_card)

        self._hero_accent_track = self._QtWidgets.QFrame()
        self._hero_accent_track.setObjectName("AccentTrack")
        self._hero_accent_track.setFixedHeight(4)
        self._hero_accent_glow = self._QtWidgets.QFrame(self._hero_accent_track)
        self._hero_accent_glow.setObjectName("AccentGlow")
        self._hero_accent_glow.setGeometry(0, 0, 180, 4)
        main_layout.addWidget(self._hero_accent_track)

        splitter = self._QtWidgets.QSplitter(self._QtCore.Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        main_layout.addWidget(splitter, 1)

        left_scroll = self._QtWidgets.QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(self._QtWidgets.QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(
            self._QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        left_scroll.setObjectName("SettingsScroll")

        left_panel = self._QtWidgets.QWidget()
        left_panel.setObjectName("SettingsPanel")
        left_layout = self._QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        left_scroll.setWidget(left_panel)

        right_panel = self._QtWidgets.QWidget()
        right_layout = self._QtWidgets.QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        splitter.addWidget(left_scroll)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        reveal_targets: list[Any] = []

        device_card, device_layout = self._build_card("Device")
        device_row = self._QtWidgets.QHBoxLayout()
        device_row.setSpacing(10)

        hid_label = self._QtWidgets.QLabel("MSI HID Path")
        hid_label.setObjectName("FieldLabel")
        self._hid_path_input = self._QtWidgets.QLineEdit(defaults.hid_path or "")

        detect_button = self._QtWidgets.QPushButton("Detect MSI HID")
        detect_button.setObjectName("SoftButton")
        detect_button.setCursor(self._QtCore.Qt.CursorShape.PointingHandCursor)
        detect_button.clicked.connect(self._detect_hid_path)

        device_row.addWidget(hid_label)
        device_row.addWidget(self._hid_path_input, 1)
        device_row.addWidget(detect_button)
        device_layout.addLayout(device_row)

        left_layout.addWidget(device_card)
        reveal_targets.append(device_card)

        mode_card, mode_layout = self._build_card("Mode")
        mode_row = self._QtWidgets.QHBoxLayout()
        mode_row.setSpacing(10)
        mode_label = self._QtWidgets.QLabel("Lighting Mode")
        mode_label.setObjectName("FieldLabel")
        self._mode_input = self._build_combo_input(
            [
                ("Screen Replication", "screen"),
                ("Sound Reactive", "sound"),
            ]
        )
        self._set_combo_to_data(self._mode_input, defaults.mode_source)
        self._mode_input.currentIndexChanged.connect(self._sync_mode_panels)
        mode_row.addWidget(mode_label)
        mode_row.addWidget(self._mode_input, 1)
        mode_layout.addLayout(mode_row)
        left_layout.addWidget(mode_card)
        reveal_targets.append(mode_card)

        self._screen_card, capture_layout = self._build_card("Screen")
        capture_grid = self._QtWidgets.QGridLayout()
        capture_grid.setHorizontalSpacing(10)
        capture_grid.setVerticalSpacing(6)

        self._rows_input = self._build_number_input(str(defaults.rows))
        self._columns_input = self._build_number_input(str(defaults.columns))
        self._fps_input = self._build_number_input(str(defaults.fps))
        self._monitor_input = self._build_number_input(str(defaults.monitor_index))
        self._iterations_input = self._build_number_input(str(defaults.iterations))

        capture_fields = [
            ("Rows", self._rows_input, 0),
            ("Columns", self._columns_input, 1),
            ("FPS", self._fps_input, 2),
            ("Monitor", self._monitor_input, 3),
        ]
        for label_text, input_widget, col in capture_fields:
            label = self._QtWidgets.QLabel(label_text)
            label.setObjectName("FieldLabel")
            capture_grid.addWidget(label, 0, col)
            capture_grid.addWidget(input_widget, 1, col)

        iter_label = self._QtWidgets.QLabel("Iterations")
        iter_label.setObjectName("FieldLabel")
        capture_grid.addWidget(iter_label, 2, 0)
        capture_grid.addWidget(self._iterations_input, 3, 0)

        self._run_until_stop_check = self._QtWidgets.QCheckBox("Run Until Stopped")
        self._run_until_stop_check.setChecked(defaults.iterations >= RUN_UNTIL_STOP_ITERATIONS)
        self._run_until_stop_check.toggled.connect(self._toggle_iterations_state)
        capture_grid.addWidget(self._run_until_stop_check, 3, 1, 1, 3)

        capture_layout.addLayout(capture_grid)

        left_layout.addWidget(self._screen_card)
        reveal_targets.append(self._screen_card)

        self._sound_source_card, sound_source_layout = self._build_card("Sound Source")
        sound_source_grid = self._QtWidgets.QGridLayout()
        sound_source_grid.setHorizontalSpacing(10)
        sound_source_grid.setVerticalSpacing(6)

        source_label = self._QtWidgets.QLabel("Input Kind")
        source_label.setObjectName("FieldLabel")
        self._audio_source_input = self._build_combo_input(
            [
                ("Output Loopback", "output-loopback"),
                ("Microphone", "microphone"),
            ]
        )
        self._set_combo_to_data(self._audio_source_input, defaults.audio_input_kind)
        self._audio_source_input.currentIndexChanged.connect(self._refresh_audio_devices)
        sound_source_grid.addWidget(source_label, 0, 0)
        sound_source_grid.addWidget(self._audio_source_input, 1, 0, 1, 2)

        device_label = self._QtWidgets.QLabel("Audio Device")
        device_label.setObjectName("FieldLabel")
        self._audio_device_input = self._QtWidgets.QComboBox()
        refresh_audio_button = self._QtWidgets.QPushButton("Refresh Devices")
        refresh_audio_button.setObjectName("SoftButton")
        refresh_audio_button.setCursor(self._QtCore.Qt.CursorShape.PointingHandCursor)
        refresh_audio_button.clicked.connect(self._refresh_audio_devices)
        sound_source_grid.addWidget(device_label, 2, 0)
        sound_source_grid.addWidget(self._audio_device_input, 3, 0)
        sound_source_grid.addWidget(refresh_audio_button, 3, 1)
        sound_source_layout.addLayout(sound_source_grid)

        left_layout.addWidget(self._sound_source_card)
        reveal_targets.append(self._sound_source_card)

        self._sound_effect_card, sound_effect_layout = self._build_card("Sound Effect")
        sound_effect_grid = self._QtWidgets.QGridLayout()
        sound_effect_grid.setHorizontalSpacing(10)
        sound_effect_grid.setVerticalSpacing(6)

        self._sound_effect_input = self._build_combo_input(
            [
                ("Spectrum", "spectrum"),
                ("Bass Pulse", "bass-pulse"),
                ("Waveform", "waveform"),
                ("Stereo Split", "stereo-split"),
            ]
        )
        self._set_combo_to_data(self._sound_effect_input, defaults.sound_effect)
        self._audio_zone_layout_input = self._build_combo_input(
            [
                ("Linear", "linear"),
                ("Mirror", "mirror"),
                ("Center Out", "center-out"),
            ]
        )
        self._set_combo_to_data(self._audio_zone_layout_input, defaults.audio_zone_layout)

        self._audio_sample_rate_input = self._build_number_input(str(defaults.audio_sample_rate_hz))
        self._audio_frame_size_input = self._build_number_input(str(defaults.audio_frame_size))
        self._audio_sensitivity_input = self._build_number_input(
            str(defaults.audio_sensitivity)
        )
        self._audio_attack_alpha_input = self._build_number_input(
            str(defaults.audio_attack_alpha)
        )
        self._audio_decay_alpha_input = self._build_number_input(
            str(defaults.audio_decay_alpha)
        )
        self._audio_noise_floor_input = self._build_number_input(
            str(defaults.audio_noise_floor)
        )
        self._audio_bass_gain_input = self._build_number_input(str(defaults.audio_bass_gain))
        self._audio_mid_gain_input = self._build_number_input(str(defaults.audio_mid_gain))
        self._audio_treble_gain_input = self._build_number_input(
            str(defaults.audio_treble_gain)
        )
        self._audio_palette_input = self._QtWidgets.QLineEdit(
            ";".join(defaults.audio_palette or DEFAULT_PALETTE)
        )

        sound_fields = [
            ("Effect", self._sound_effect_input, 0, 0),
            ("Zone Layout", self._audio_zone_layout_input, 0, 1),
            ("Sample Rate", self._audio_sample_rate_input, 2, 0),
            ("Frame Size", self._audio_frame_size_input, 2, 1),
            ("Sensitivity", self._audio_sensitivity_input, 4, 0),
            ("Attack", self._audio_attack_alpha_input, 4, 1),
            ("Decay", self._audio_decay_alpha_input, 6, 0),
            ("Noise Floor", self._audio_noise_floor_input, 6, 1),
            ("Bass Gain", self._audio_bass_gain_input, 8, 0),
            ("Mid Gain", self._audio_mid_gain_input, 8, 1),
            ("Treble Gain", self._audio_treble_gain_input, 10, 0),
        ]
        for label_text, widget, row, col in sound_fields:
            label = self._QtWidgets.QLabel(label_text)
            label.setObjectName("FieldLabel")
            sound_effect_grid.addWidget(label, row, col)
            sound_effect_grid.addWidget(widget, row + 1, col)

        palette_label = self._QtWidgets.QLabel("Palette")
        palette_label.setObjectName("FieldLabel")
        sound_effect_grid.addWidget(palette_label, 12, 0, 1, 2)
        sound_effect_grid.addWidget(self._audio_palette_input, 13, 0, 1, 2)
        sound_effect_layout.addLayout(sound_effect_grid)

        left_layout.addWidget(self._sound_effect_card)
        reveal_targets.append(self._sound_effect_card)

        behavior_card, behavior_layout = self._build_card("Behavior")
        self._strict_check = self._QtWidgets.QCheckBox("Strict Preflight")
        self._strict_check.setChecked(defaults.strict_preflight)
        behavior_layout.addWidget(self._strict_check)

        left_layout.addWidget(behavior_card)
        reveal_targets.append(behavior_card)

        actions_card, actions_layout = self._build_card("Actions")
        action_row = self._QtWidgets.QHBoxLayout()
        action_row.setSpacing(8)

        self._start_button = self._QtWidgets.QPushButton("Start Live")
        self._start_button.setObjectName("PrimaryButton")
        self._start_button.setCursor(self._QtCore.Qt.CursorShape.PointingHandCursor)
        self._start_button.clicked.connect(self._start_live)

        self._save_button = self._QtWidgets.QPushButton("Save Settings")
        self._save_button.setObjectName("SoftButton")
        self._save_button.setCursor(self._QtCore.Qt.CursorShape.PointingHandCursor)
        self._save_button.clicked.connect(lambda: self._save_settings(show_message=True))

        self._stop_button = self._QtWidgets.QPushButton("Stop")
        self._stop_button.setObjectName("DangerButton")
        self._stop_button.setCursor(self._QtCore.Qt.CursorShape.PointingHandCursor)
        self._stop_button.clicked.connect(self._stop_live)

        self._hide_button = self._QtWidgets.QPushButton("Minimize To Tray")
        self._hide_button.setObjectName("SoftButton")
        self._hide_button.setCursor(self._QtCore.Qt.CursorShape.PointingHandCursor)
        self._hide_button.clicked.connect(self._hide_to_tray)

        action_row.addWidget(self._start_button)
        action_row.addWidget(self._save_button)
        action_row.addWidget(self._stop_button)
        action_row.addWidget(self._hide_button)
        actions_layout.addLayout(action_row)

        self._apply_hint_label = self._QtWidgets.QLabel("Changes apply immediately when saved.")
        self._apply_hint_label.setObjectName("MutedLabel")
        actions_layout.addWidget(self._apply_hint_label)

        runtime_label = self._QtWidgets.QLabel("Runtime status")
        runtime_label.setObjectName("MutedLabel")
        self._runtime_status_value = self._QtWidgets.QLabel("Idle")
        self._runtime_status_value.setObjectName("RuntimeStatus")
        actions_layout.addWidget(runtime_label)
        actions_layout.addWidget(self._runtime_status_value)

        left_layout.addWidget(actions_card)
        reveal_targets.append(actions_card)
        left_layout.addStretch(1)

        log_card, log_layout = self._build_card("Runtime Log")
        log_note = self._QtWidgets.QLabel(
            "Live output, command traces, and process diagnostics"
        )
        log_note.setObjectName("MutedLabel")
        log_layout.addWidget(log_note)

        self._log_widget = self._QtWidgets.QPlainTextEdit()
        self._log_widget.setObjectName("RuntimeLog")
        self._log_widget.setReadOnly(True)
        self._log_widget.setLineWrapMode(self._QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth)
        log_layout.addWidget(self._log_widget, 1)

        right_layout.addWidget(log_card, 1)
        reveal_targets.append(log_card)

        self._run_staggered_reveal(reveal_targets)
        self._refresh_audio_devices(silent=True)
        self._sync_mode_panels()
        self._toggle_iterations_state()
        self._set_status_text("Idle")

    def _build_stylesheet(self) -> str:
        return """
QWidget#Root {
    background-color: #07111d;
    color: #e8f0fc;
    font-family: "Segoe UI";
    font-size: 10pt;
}
QFrame#HeroCard {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #0f1e31,
        stop:0.65 #0c1a2b,
        stop:1 #0a1626
    );
    border: 1px solid #2a3d57;
    border-radius: 14px;
}
QLabel#TitleLabel {
    color: #f5f8ff;
    font-size: 21pt;
    font-weight: 700;
}
QLabel#SubtitleLabel {
    color: #9ab0cd;
    font-size: 13pt;
}
QLabel#StatusBadge {
    border-radius: 10px;
    padding: 8px 18px;
    min-width: 122px;
    font-size: 12pt;
    font-weight: 700;
    qproperty-alignment: AlignCenter;
}
QLabel#StatusBadge[state="idle"] {
    background-color: #2f4158;
    color: #dfeaf9;
}
QLabel#StatusBadge[state="running"] {
    background-color: #1f6a4a;
    color: #ebfff5;
}
QLabel#StatusBadge[state="running-pulse"] {
    background-color: #27885d;
    color: #f4fff9;
}
QLabel#StatusBadge[state="tray"] {
    background-color: #6f4f1a;
    color: #ffedc9;
}
QLabel#StatusBadge[state="tray-pulse"] {
    background-color: #876124;
    color: #fff3d7;
}
QFrame#AccentTrack {
    background-color: #2a3f58;
    border-radius: 2px;
}
QFrame#AccentGlow {
    background-color: #2ab3dc;
    border-radius: 2px;
}
QGroupBox#Card {
    background-color: #122034;
    border: 1px solid #2b425f;
    border-radius: 12px;
    margin-top: 0px;
    padding-top: 22px;
}
QGroupBox#Card::title {
    subcontrol-origin: padding;
    subcontrol-position: top left;
    left: 14px;
    top: 0px;
    padding: 0 0 2px 0;
    color: #e1eaf9;
    background: transparent;
    font-size: 13pt;
    font-weight: 600;
}
QLabel#FieldLabel {
    color: #adc0da;
    font-size: 10.5pt;
}
QLabel#MutedLabel {
    color: #8ea4c3;
    font-size: 10.5pt;
}
QLabel#RuntimeStatus {
    color: #f3f7ff;
    font-size: 14pt;
    font-weight: 700;
}
QLineEdit {
    background-color: #0a1522;
    border: 1px solid #3a536f;
    border-radius: 8px;
    color: #ebf3ff;
    padding: 7px 10px;
    font-size: 11pt;
}
QLineEdit:focus {
    background-color: #101f31;
    border: 1px solid #2cb6df;
}
QComboBox {
    background-color: #0a1522;
    border: 1px solid #3a536f;
    border-radius: 8px;
    color: #ebf3ff;
    padding: 7px 10px;
    font-size: 11pt;
}
QComboBox:focus {
    background-color: #101f31;
    border: 1px solid #2cb6df;
}
QComboBox QAbstractItemView {
    background-color: #0a1522;
    color: #ebf3ff;
    border: 1px solid #3a536f;
    selection-background-color: #2f6ea4;
}
QScrollArea#SettingsScroll {
    background: transparent;
    border: none;
}
QWidget#SettingsPanel {
    background: transparent;
}
QScrollBar:vertical {
    background-color: #0a1522;
    width: 12px;
    margin: 4px 0 4px 0;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    background-color: #355678;
    min-height: 28px;
    border-radius: 6px;
}
QScrollBar::handle:vertical:hover {
    background-color: #47709c;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0px;
}
QCheckBox {
    color: #d8e4f7;
    spacing: 8px;
    font-size: 12pt;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
}
QPushButton {
    border: none;
    border-radius: 9px;
    padding: 9px 16px;
    font-size: 11.5pt;
}
QPushButton:disabled {
    color: #95a6be;
    background-color: #303c4b;
}
QPushButton#PrimaryButton {
    color: #2c1b01;
    background-color: #efbc4e;
    font-weight: 700;
}
QPushButton#PrimaryButton:hover {
    background-color: #ffd77b;
}
QPushButton#PrimaryButton:pressed {
    background-color: #cb982c;
}
QPushButton#DangerButton {
    color: #fff6f4;
    background-color: #e85b43;
    font-weight: 700;
}
QPushButton#DangerButton:hover {
    background-color: #ff7a65;
}
QPushButton#DangerButton:pressed {
    background-color: #bf4332;
}
QPushButton#SoftButton {
    color: #e6eefb;
    background-color: #324b68;
}
QPushButton#SoftButton:hover {
    background-color: #3e6085;
}
QPushButton#SoftButton:pressed {
    background-color: #2a4660;
}
QPlainTextEdit#RuntimeLog {
    background-color: #050d16;
    border: 1px solid #335c86;
    border-radius: 10px;
    color: #d4e2f5;
    selection-background-color: #2f6ea4;
    font-family: "Consolas";
    font-size: 11pt;
    padding: 10px;
}
"""

    def _build_card(self, title: str) -> tuple[Any, Any]:
        card = self._QtWidgets.QGroupBox(title)
        card.setObjectName("Card")
        layout = self._QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)
        return card, layout

    def _build_number_input(self, value: str) -> Any:
        widget = self._QtWidgets.QLineEdit(value)
        widget.setMaximumWidth(140)
        return widget

    def _build_combo_input(self, options: list[tuple[str, str]]) -> Any:
        widget = self._QtWidgets.QComboBox()
        for label, value in options:
            widget.addItem(label, value)
        return widget

    def _combo_current_data(self, widget: Any) -> str:
        data = widget.currentData()
        if isinstance(data, str):
            return data
        text = widget.currentText()
        if not isinstance(text, str) or text.strip() == "":
            raise ValueError("Combo box selection is required.")
        return text.strip()

    def _set_combo_to_data(self, widget: Any, value: str | None) -> None:
        if value is None:
            return
        index = widget.findData(value)
        if index >= 0:
            widget.setCurrentIndex(index)

    def _current_mode(self) -> str:
        return self._combo_current_data(self._mode_input)

    def _load_brand_pixmap(self, size: int) -> Any:
        brand_path = (self._repo_root / MSI_BRAND_ICON_RELATIVE_PATH).resolve()

        if brand_path.exists():
            if self._QtSvg is not None:
                renderer = self._QtSvg.QSvgRenderer(str(brand_path))
                if renderer.isValid():
                    image = self._QtGui.QPixmap(size, size)
                    image.fill(self._QtCore.Qt.GlobalColor.transparent)
                    painter = self._QtGui.QPainter(image)
                    renderer.render(painter)
                    painter.end()
                    return image

            image = self._QtGui.QPixmap(str(brand_path))
            if not image.isNull():
                return image.scaled(
                    size,
                    size,
                    self._QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    self._QtCore.Qt.TransformationMode.SmoothTransformation,
                )

        return self._build_fallback_brand_pixmap(size)

    def _build_fallback_brand_pixmap(self, size: int) -> Any:
        pixmap = self._QtGui.QPixmap(size, size)
        pixmap.fill(self._QtGui.QColor("#ea5a41"))
        painter = self._QtGui.QPainter(pixmap)
        painter.setRenderHint(self._QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setPen(self._QtGui.QColor("#ffffff"))
        font = self._QtGui.QFont("Segoe UI", max(9, size // 4))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            pixmap.rect(),
            int(self._QtCore.Qt.AlignmentFlag.AlignCenter),
            "MSI",
        )
        painter.end()
        return pixmap

    def _run_staggered_reveal(self, widgets: list[Any]) -> None:
        self._reveal_animations.clear()
        for index, widget in enumerate(widgets):
            effect = self._QtWidgets.QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.0)
            widget.setGraphicsEffect(effect)

            animation = self._QtCore.QPropertyAnimation(effect, b"opacity", widget)
            animation.setDuration(360)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            animation.setEasingCurve(self._QtCore.QEasingCurve.Type.OutCubic)
            self._reveal_animations.append(animation)

            self._QtCore.QTimer.singleShot(
                (index + 1) * UI_REVEAL_STEP_MS,
                animation.start,
            )

    def _start_ui_animations(self) -> None:
        self._accent_timer = self._QtCore.QTimer(self._window)
        self._accent_timer.timeout.connect(self._animate_hero_accent)
        self._accent_timer.start(HERO_ACCENT_INTERVAL_MS)

        self._status_timer = self._QtCore.QTimer(self._window)
        self._status_timer.timeout.connect(self._animate_status_pulse)
        self._status_timer.start(STATUS_PULSE_INTERVAL_MS)

    def _animate_hero_accent(self) -> None:
        if not self._animations_enabled or self._shutting_down:
            return
        track_width = max(self._hero_accent_track.width(), 1)
        glow_width = max(track_width // 6, 110)
        max_offset = max(track_width - glow_width, 0)

        step = max(2, track_width // 180)
        self._accent_offset += self._accent_direction * step
        if self._accent_offset <= 0:
            self._accent_offset = 0
            self._accent_direction = 1
        elif self._accent_offset >= max_offset:
            self._accent_offset = max_offset
            self._accent_direction = -1

        self._hero_accent_glow.setGeometry(self._accent_offset, 0, glow_width, 4)

    def _animate_status_pulse(self) -> None:
        if not self._animations_enabled or self._shutting_down:
            return
        self._status_pulse_phase = not self._status_pulse_phase
        self._sync_status_badge()

    def _set_status_text(self, text: str) -> None:
        self._status_badge.setText(text)
        self._runtime_status_value.setText(text)
        self._sync_status_badge()

    def _sync_status_badge(self) -> None:
        if self._is_running():
            state = "running-pulse" if self._status_pulse_phase else "running"
        elif not self._window_visible and self._tray_icon is not None:
            state = "tray-pulse" if self._status_pulse_phase else "tray"
        else:
            state = "idle"
        if self._status_badge.property("state") != state:
            self._status_badge.setProperty("state", state)
            self._status_badge.style().unpolish(self._status_badge)
            self._status_badge.style().polish(self._status_badge)

    def _setup_tray_if_available(self) -> None:
        if not self._tray_enabled:
            self._append_log("Tray disabled by launch option.")
            return
        if not self._QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self._append_log("Tray unavailable in this desktop session.")
            return

        self._tray_icon = self._QtWidgets.QSystemTrayIcon(self._window)
        self._tray_icon.setIcon(self._create_tray_icon(is_running=False))
        self._tray_icon.setToolTip("KeyLight (Idle)")

        menu = self._QtWidgets.QMenu(self._window)
        self._tray_pause_action = menu.addAction("Pause")
        self._tray_resume_action = menu.addAction("Resume")
        open_action = menu.addAction("Open Settings")
        menu.addSeparator()
        exit_action = menu.addAction("Exit")

        self._tray_pause_action.triggered.connect(self._on_tray_pause)
        self._tray_resume_action.triggered.connect(self._on_tray_resume)
        open_action.triggered.connect(self._on_tray_open_settings)
        exit_action.triggered.connect(self._on_tray_exit)

        self._tray_icon.setContextMenu(menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()
        self._append_log("Tray icon initialized.")

    def _create_tray_icon(self, *, is_running: bool) -> Any:
        icon_pixmap = self._load_brand_pixmap(TRAY_ICON_SIZE)
        pixmap = icon_pixmap.copy()

        painter = self._QtGui.QPainter(pixmap)
        painter.setRenderHint(self._QtGui.QPainter.RenderHint.Antialiasing, True)
        if is_running:
            indicator_color = self._QtGui.QColor("#2dc17a")
        else:
            indicator_color = self._QtGui.QColor("#8b9bb4")
        painter.setBrush(indicator_color)
        painter.setPen(self._QtGui.QPen(self._QtGui.QColor("#f1f6ff"), 2))
        painter.drawEllipse(TRAY_ICON_SIZE - 19, TRAY_ICON_SIZE - 19, 13, 13)
        painter.end()

        return self._QtGui.QIcon(pixmap)

    def _update_tray_state(self) -> None:
        if self._tray_icon is None:
            return
        running = self._is_running()
        self._tray_icon.setIcon(self._create_tray_icon(is_running=running))
        visibility = "Hidden" if not self._window_visible else "Visible"
        status = "Running" if running else "Idle"
        self._tray_icon.setToolTip(f"KeyLight ({status}, {visibility})")

        if self._tray_pause_action is not None:
            self._tray_pause_action.setEnabled(running)
        if self._tray_resume_action is not None:
            self._tray_resume_action.setEnabled(not running)

    def _is_running(self) -> bool:
        process = self._process
        if process is None:
            return False
        return process.state() != self._QtCore.QProcess.ProcessState.NotRunning

    def _on_tray_activated(self, reason: Any) -> None:
        if reason == self._QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_window()

    def _on_tray_pause(self) -> None:
        self._stop_live()

    def _on_tray_resume(self) -> None:
        self._start_live()

    def _on_tray_open_settings(self) -> None:
        self._show_window()

    def _on_tray_exit(self) -> None:
        self._exit_application()

    def _show_window(self) -> None:
        self._window_visible = True
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()
        self._set_status_text("Running" if self._is_running() else "Idle")
        self._append_log("Window restored from tray.")
        self._update_tray_state()

    def _hide_to_tray(self) -> bool:
        if self._tray_icon is None:
            return False
        self._window_visible = False
        self._window.hide()
        if self._is_running():
            self._set_status_text("Running (Tray)")
        else:
            self._set_status_text("Idle (Tray)")
        self._append_log("Window minimized to tray.")
        self._update_tray_state()
        return True

    def _on_close_requested(self, event: Any) -> None:
        if self._hide_to_tray():
            event.ignore()
            return
        event.accept()
        self._exit_application()

    def _detect_hid_path(self, *, silent: bool = False) -> None:
        try:
            devices = list_hid_devices()
        except RuntimeError as error:
            if not silent:
                self._QtWidgets.QMessageBox.critical(
                    self._window,
                    "KeyLight",
                    f"HID enumerate failed: {error}",
                )
            self._append_log(f"HID enumerate failed: {error}")
            return

        selected = select_preferred_msi_hid_path(devices)
        if selected is None:
            if not silent:
                self._QtWidgets.QMessageBox.warning(
                    self._window,
                    "KeyLight",
                    "No MSI VID=1462 PID=1603 HID path found.",
                )
            return

        self._hid_path_input.setText(selected)
        self._append_log(f"Detected HID path: {selected}")

    def _refresh_audio_devices(self, *_args: Any, silent: bool = False) -> None:
        previous_id = None
        try:
            previous_id = self._combo_current_data(self._audio_device_input)
        except Exception:
            previous_id = None

        source_kind = self._combo_current_data(self._audio_source_input)
        selected_default = self._defaults.audio_device_id
        self._audio_device_input.clear()
        try:
            devices = [device for device in list_audio_devices() if device.kind == source_kind]
        except RuntimeError as error:
            self._append_log(f"Audio device enumerate failed: {error}")
            if not silent:
                self._QtWidgets.QMessageBox.warning(
                    self._window,
                    "KeyLight",
                    f"Audio device enumerate failed: {error}",
                )
            return

        for device in devices:
            label = device.name + (" (default)" if device.is_default else "")
            self._audio_device_input.addItem(label, device.id)

        preferred_id = previous_id or selected_default
        if preferred_id is not None:
            self._set_combo_to_data(self._audio_device_input, preferred_id)
        elif self._audio_device_input.count() > 0:
            self._audio_device_input.setCurrentIndex(0)

    def _sync_mode_panels(self, *_args: Any) -> None:
        is_screen = self._current_mode() == "screen"
        self._screen_card.setVisible(is_screen)
        self._sound_source_card.setVisible(not is_screen)
        self._sound_effect_card.setVisible(not is_screen)

    def _collect_defaults_from_ui(self) -> LiveCommandDefaults:
        rows = self._parse_int(self._rows_input.text(), "Rows")
        columns = self._parse_int(self._columns_input.text(), "Columns")
        fps = self._parse_int(self._fps_input.text(), "FPS")
        monitor_index = self._parse_int(self._monitor_input.text(), "Monitor index")
        run_until_stopped = bool(self._run_until_stop_check.isChecked())
        iterations = RUN_UNTIL_STOP_ITERATIONS if run_until_stopped else self._parse_int(
            self._iterations_input.text(),
            "Iterations",
        )

        defaults = replace(
            self._defaults,
            mode_source=self._current_mode(),
            backend="msi-mystic-hid",
            capturer="windows-mss",
            hid_path=self._hid_path_input.text().strip() or None,
            rows=rows,
            columns=columns,
            fps=fps,
            iterations=iterations,
            monitor_index=monitor_index,
            strict_preflight=bool(self._strict_check.isChecked()),
            audio_input_kind=self._combo_current_data(self._audio_source_input),
            audio_device_id=(
                self._combo_current_data(self._audio_device_input)
                if self._audio_device_input.count() > 0
                else None
            ),
            sound_effect=self._combo_current_data(self._sound_effect_input),
            audio_zone_layout=self._combo_current_data(self._audio_zone_layout_input),
            audio_sample_rate_hz=self._parse_int(
                self._audio_sample_rate_input.text(),
                "Sample rate",
            ),
            audio_frame_size=self._parse_int(
                self._audio_frame_size_input.text(),
                "Frame size",
            ),
            audio_sensitivity=self._parse_float(
                self._audio_sensitivity_input.text(),
                "Sensitivity",
            ),
            audio_attack_alpha=self._parse_float(
                self._audio_attack_alpha_input.text(),
                "Attack alpha",
            ),
            audio_decay_alpha=self._parse_float(
                self._audio_decay_alpha_input.text(),
                "Decay alpha",
            ),
            audio_noise_floor=self._parse_float(
                self._audio_noise_floor_input.text(),
                "Noise floor",
            ),
            audio_bass_gain=self._parse_float(
                self._audio_bass_gain_input.text(),
                "Bass gain",
            ),
            audio_mid_gain=self._parse_float(
                self._audio_mid_gain_input.text(),
                "Mid gain",
            ),
            audio_treble_gain=self._parse_float(
                self._audio_treble_gain_input.text(),
                "Treble gain",
            ),
            audio_palette=tuple(
                part.strip()
                for part in self._audio_palette_input.text().split(";")
                if part.strip()
            ),
        )
        validation_path = self._repo_root / "config" / "_validation_tmp.toml"
        try:
            defaults = load_live_command_defaults(
                write_live_defaults_toml(defaults, validation_path),
                must_exist=True,
            )
        finally:
            validation_path.unlink(missing_ok=True)
        return defaults

    def _save_settings(self, *, show_message: bool) -> bool:
        config_path = self._repo_root / "config" / "default.toml"
        try:
            defaults = self._collect_defaults_from_ui()
            write_live_defaults_toml(defaults, config_path)
        except ValueError as error:
            self._QtWidgets.QMessageBox.critical(self._window, "KeyLight", str(error))
            return False

        self._defaults = defaults
        if self._is_running():
            self._apply_hint_label.setText("Settings saved. Restart live to apply changes.")
        else:
            self._apply_hint_label.setText("Changes apply immediately when saved.")
        self._append_log(f"Saved settings to {config_path.resolve()}")
        if show_message:
            self._QtWidgets.QMessageBox.information(
                self._window,
                "KeyLight",
                (
                    "Settings saved. Restart live to apply changes."
                    if self._is_running()
                    else "Settings saved."
                ),
            )
        return True

    def _build_run_config(self) -> AppLiveRunConfig:
        output_name = f"live_report_gui_{datetime.now(tz=UTC).strftime('%Y%m%d_%H%M%S')}.json"
        output_path = (self._repo_root / "artifacts" / output_name).resolve()

        return AppLiveRunConfig(
            config_path=(self._repo_root / "config" / "default.toml").resolve(),
            output_path=output_path,
        )

    def _start_live(self) -> None:
        if self._is_running():
            self._QtWidgets.QMessageBox.information(
                self._window,
                "KeyLight",
                "Live session already running.",
            )
            return

        try:
            if not self._save_settings(show_message=False):
                return
            run_config = self._build_run_config()
            command = build_live_command(
                python_executable=sys.executable,
                config=run_config,
            )
        except ValueError as error:
            self._QtWidgets.QMessageBox.critical(self._window, "KeyLight", str(error))
            return

        self._append_log("")
        self._append_log("$ " + " ".join(command))

        process = self._QtCore.QProcess(self._window)
        process.setWorkingDirectory(str(self._repo_root))
        process.setProgram(command[0])
        process.setArguments(command[1:])
        process.setProcessChannelMode(self._QtCore.QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read_process_output)
        process.finished.connect(self._on_process_finished)

        process.start()
        if not process.waitForStarted(2500):
            error_text = process.errorString() or "Unknown process startup failure."
            self._QtWidgets.QMessageBox.critical(
                self._window,
                "KeyLight",
                f"Failed to start live session: {error_text}",
            )
            process.deleteLater()
            return

        self._process = process
        self._process_buffer = ""
        self._stop_in_progress = False
        self._set_running(True)
        self._set_status_text("Running")

    def _autostart_if_possible(self) -> None:
        if self._is_running():
            return

        if self._hid_path_input.text().strip() == "":
            self._detect_hid_path(silent=True)

        if self._defaults.backend == "msi-mystic-hid" and self._hid_path_input.text().strip() == "":
            self._append_log(
                "Autostart skipped: MSI HID path not detected. Click 'Detect MSI HID' and retry."
            )
            self._set_status_text("Idle (HID not detected)")
            return

        self._append_log("Autostart: starting live session.")
        self._start_live()

    def _stop_live(self) -> None:
        process = self._process
        if process is None:
            return
        if process.state() == self._QtCore.QProcess.ProcessState.NotRunning:
            return
        if self._stop_in_progress:
            return

        self._stop_in_progress = True
        self._append_log("Stopping live session...")
        self._set_running(True)
        process.terminate()

        timer = self._force_stop_timer
        if timer is not None:
            timer.stop()
            timer.deleteLater()

        force_timer = self._QtCore.QTimer(self._window)
        force_timer.setSingleShot(True)
        force_timer.timeout.connect(self._force_kill_if_needed)
        force_timer.start(STOP_FORCE_KILL_TIMEOUT_MS)
        self._force_stop_timer = force_timer

    def _force_kill_if_needed(self) -> None:
        process = self._process
        if process is None:
            return
        if process.state() == self._QtCore.QProcess.ProcessState.NotRunning:
            return
        self._append_log("Terminate timed out; forcing process kill.")
        process.kill()

    def _read_process_output(self) -> None:
        process = self._process
        if process is None:
            return

        chunk = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if chunk == "":
            return

        self._process_buffer += chunk
        while "\n" in self._process_buffer:
            line, self._process_buffer = self._process_buffer.split("\n", 1)
            self._append_log(line.rstrip("\r"))

    def _on_process_finished(self, exit_code: int, _status: Any) -> None:
        timer = self._force_stop_timer
        if timer is not None:
            timer.stop()
            timer.deleteLater()
            self._force_stop_timer = None
        self._stop_in_progress = False

        if self._process_buffer != "":
            self._append_log(self._process_buffer.rstrip("\r"))
            self._process_buffer = ""

        self._append_log(f"Live process exited with code {exit_code}.")
        self._set_running(False)

        if self._window_visible:
            self._set_status_text("Idle")
        else:
            self._set_status_text("Idle (Tray)")

        process = self._process
        self._process = None
        if process is not None:
            process.deleteLater()

    def _set_running(self, is_running: bool) -> None:
        self._start_button.setEnabled(not is_running)
        self._save_button.setEnabled(True)
        self._stop_button.setEnabled(is_running and not self._stop_in_progress)
        self._hide_button.setEnabled(self._tray_icon is not None)
        self._toggle_iterations_state()
        self._sync_status_badge()
        self._update_tray_state()
        if is_running:
            self._apply_hint_label.setText("Live run active. Restart live to apply saved changes.")
        else:
            self._apply_hint_label.setText("Changes apply immediately when saved.")

    def _toggle_iterations_state(self) -> None:
        self._iterations_input.setEnabled(not self._run_until_stop_check.isChecked())

    def _append_log(self, line: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._log_widget.appendPlainText(f"[{timestamp}] {line}")

    def _parse_int(self, raw: str, field_name: str) -> int:
        text = raw.strip()
        if text == "":
            raise ValueError(f"{field_name} is required.")
        try:
            value = int(text, 10)
        except ValueError as error:
            raise ValueError(f"{field_name} must be an integer.") from error
        if value <= 0:
            raise ValueError(f"{field_name} must be positive.")
        return value

    def _parse_float(self, raw: str, field_name: str) -> float:
        text = raw.strip()
        if text == "":
            raise ValueError(f"{field_name} is required.")
        try:
            return float(text)
        except ValueError as error:
            raise ValueError(f"{field_name} must be numeric.") from error

    def _exit_application(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._animations_enabled = False

        self._append_log("Exiting KeyLight...")

        process = self._process
        if process is not None and process.state() != self._QtCore.QProcess.ProcessState.NotRunning:
            self._append_log("Stopping live session...")
            process.terminate()
            if not process.waitForFinished(2000):
                process.kill()
                process.waitForFinished(1000)

        timer = self._force_stop_timer
        if timer is not None:
            timer.stop()
            timer.deleteLater()
            self._force_stop_timer = None

        tray_icon = self._tray_icon
        self._tray_icon = None
        if tray_icon is not None:
            tray_icon.hide()
            tray_icon.deleteLater()

        self._window.hide()
        self._app.quit()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KeyLight desktop app launcher")
    parser.add_argument(
        "--autostart",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Automatically detect HID and start live session on app launch",
    )
    parser.add_argument(
        "--tray",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable system tray icon and close-to-tray behavior",
    )
    parser.add_argument(
        "--start-hidden",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Start with window minimized to tray (requires --tray)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        qtcore = importlib.import_module("PySide6.QtCore")
        qtgui = importlib.import_module("PySide6.QtGui")
        qtwidgets = importlib.import_module("PySide6.QtWidgets")
    except ModuleNotFoundError:
        print(
            "Premium desktop UI dependencies are missing. "
            "Install with: pip install -e \".[ui-premium]\""
        )
        return 1

    qtsvg: Any | None = None
    try:
        qtsvg = importlib.import_module("PySide6.QtSvg")
    except ModuleNotFoundError:
        qtsvg = None

    qt_argv = sys.argv if argv is None else [sys.argv[0], *argv]
    app = qtwidgets.QApplication.instance()
    if app is None:
        app = qtwidgets.QApplication(qt_argv)

    app.setApplicationName("KeyLight")
    app.setApplicationDisplayName("KeyLight Studio")
    app.setStyle("Fusion")

    repo_root = Path.cwd().resolve()
    desktop_app = KeyLightDesktopApp(
        app=app,
        repo_root=repo_root,
        qtcore=qtcore,
        qtgui=qtgui,
        qtwidgets=qtwidgets,
        qtsvg=qtsvg,
        autostart=args.autostart,
        tray_enabled=args.tray,
        start_hidden=args.start_hidden,
    )
    app.setProperty("keylight_desktop", desktop_app)

    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
