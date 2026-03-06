from __future__ import annotations

import argparse
import importlib
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from keylight.drivers.hid_raw import HidDeviceInfo, list_hid_devices
from keylight.runtime_config import load_live_command_defaults

RUN_UNTIL_STOP_ITERATIONS = 2_000_000_000
TRAY_ICON_SIZE = 64


@dataclass(frozen=True, slots=True)
class AppLiveRunConfig:
    hid_path: str
    rows: int
    columns: int
    fps: int
    iterations: int
    run_until_stopped: bool
    monitor_index: int
    strict_preflight: bool
    aggressive_msi_close: bool
    output_path: Path

    def validate(self) -> None:
        if self.hid_path.strip() == "":
            raise ValueError("HID path is required.")
        if self.rows <= 0:
            raise ValueError("Rows must be positive.")
        if self.columns <= 0:
            raise ValueError("Columns must be positive.")
        if self.fps <= 0:
            raise ValueError("FPS must be positive.")
        if not self.run_until_stopped and self.iterations <= 0:
            raise ValueError("Iterations must be positive.")
        if self.monitor_index <= 0:
            raise ValueError("Monitor index must be >= 1.")


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
    effective_iterations = (
        RUN_UNTIL_STOP_ITERATIONS if config.run_until_stopped else config.iterations
    )
    command = [
        python_executable,
        "-m",
        "keylight.cli",
        "live",
        "--capturer",
        "windows-mss",
        "--backend",
        "msi-mystic-hid",
        "--hid-path",
        config.hid_path,
        "--rows",
        str(config.rows),
        "--columns",
        str(config.columns),
        "--fps",
        str(config.fps),
        "--iterations",
        str(effective_iterations),
        "--monitor-index",
        str(config.monitor_index),
        "--output",
        str(config.output_path),
    ]
    if config.strict_preflight:
        command.append("--strict-preflight")
    else:
        command.append("--no-strict-preflight")
    if config.aggressive_msi_close:
        command.append("--aggressive-msi-close")
    return command


class KeyLightDesktopApp:
    def __init__(
        self,
        *,
        root: Any,
        repo_root: Path,
        tk_module: Any,
        ttk_module: Any,
        messagebox_module: Any,
        pystray_module: Any | None,
        image_module: Any | None,
        image_draw_module: Any | None,
        autostart: bool = True,
        tray_enabled: bool = True,
        start_hidden: bool = True,
    ) -> None:
        self._root = root
        self._repo_root = repo_root
        self._tk = tk_module
        self._ttk = ttk_module
        self._messagebox = messagebox_module
        self._pystray = pystray_module
        self._image = image_module
        self._image_draw = image_draw_module
        self._tray_enabled = tray_enabled
        self._process: subprocess.Popen[str] | None = None
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._stdout_thread: threading.Thread | None = None
        self._tray_icon: Any | None = None
        self._tray_thread: threading.Thread | None = None
        self._window_visible = True
        self._shutting_down = False

        defaults = self._load_defaults(repo_root / "config" / "default.toml")

        self._hid_path_var = tk_module.StringVar(value=defaults["hid_path"])
        self._rows_var = tk_module.StringVar(value=str(defaults["rows"]))
        self._columns_var = tk_module.StringVar(value=str(defaults["columns"]))
        self._fps_var = tk_module.StringVar(value=str(defaults["fps"]))
        self._iterations_var = tk_module.StringVar(value=str(defaults["iterations"]))
        self._monitor_var = tk_module.StringVar(value=str(defaults["monitor_index"]))
        self._strict_var = tk_module.BooleanVar(value=defaults["strict_preflight"])
        self._aggressive_var = tk_module.BooleanVar(value=True)
        self._run_until_stop_var = tk_module.BooleanVar(value=True)

        self._start_button: Any
        self._stop_button: Any
        self._hide_button: Any
        self._status_var = tk_module.StringVar(value="Idle")
        self._log_widget: Any
        self._iterations_entry: Any

        self._build_ui()
        self._setup_tray_if_available()
        if start_hidden and self._tray_icon is not None:
            self._root.after(220, self._hide_to_tray)
        self._set_running(False)
        self._root.after(120, self._drain_log_queue)
        if autostart:
            self._root.after(450, self._autostart_if_possible)

    def _load_defaults(self, config_path: Path) -> dict[str, object]:
        defaults = load_live_command_defaults(config_path)
        return {
            "hid_path": defaults.hid_path or "",
            "rows": defaults.rows,
            "columns": defaults.columns,
            "fps": defaults.fps,
            "iterations": defaults.iterations,
            "monitor_index": defaults.monitor_index,
            "strict_preflight": defaults.strict_preflight,
        }

    def _build_ui(self) -> None:
        self._root.title("KeyLight Desktop")
        self._root.geometry("880x620")

        main_frame = self._ttk.Frame(self._root, padding=12)
        main_frame.pack(fill=self._tk.BOTH, expand=True)

        controls = self._ttk.LabelFrame(main_frame, text="Session", padding=10)
        controls.pack(fill=self._tk.X, expand=False)

        self._add_label_entry(controls, 0, "HID Path", self._hid_path_var, width=84)
        detect_button = self._ttk.Button(
            controls,
            text="Detect MSI HID",
            command=self._detect_hid_path,
        )
        detect_button.grid(row=0, column=2, padx=(8, 0), pady=4, sticky=self._tk.W)

        self._add_label_entry(controls, 1, "Rows", self._rows_var, width=8)
        self._add_label_entry(controls, 1, "Columns", self._columns_var, width=8, col=2)
        self._add_label_entry(controls, 1, "FPS", self._fps_var, width=8, col=4)
        iterations_label = self._ttk.Label(controls, text="Iterations")
        iterations_label.grid(row=1, column=6, sticky=self._tk.W, padx=4, pady=4)
        self._iterations_entry = self._ttk.Entry(
            controls,
            textvariable=self._iterations_var,
            width=10,
        )
        self._iterations_entry.grid(row=1, column=7, sticky=self._tk.W, padx=4, pady=4)
        self._add_label_entry(controls, 1, "Monitor", self._monitor_var, width=8, col=8)

        strict_check = self._ttk.Checkbutton(
            controls,
            text="Strict Preflight",
            variable=self._strict_var,
        )
        strict_check.grid(row=2, column=0, padx=4, pady=6, sticky=self._tk.W)

        aggressive_check = self._ttk.Checkbutton(
            controls,
            text="Aggressive MSI Close",
            variable=self._aggressive_var,
        )
        aggressive_check.grid(row=2, column=1, padx=4, pady=6, sticky=self._tk.W)

        run_until_stop_check = self._ttk.Checkbutton(
            controls,
            text="Run Until Stopped",
            variable=self._run_until_stop_var,
            command=self._toggle_iterations_state,
        )
        run_until_stop_check.grid(row=2, column=2, padx=4, pady=6, sticky=self._tk.W)

        buttons = self._ttk.Frame(controls)
        buttons.grid(row=3, column=0, columnspan=10, sticky=self._tk.W, pady=(6, 2))

        self._start_button = self._ttk.Button(buttons, text="Start Live", command=self._start_live)
        self._start_button.pack(side=self._tk.LEFT, padx=(0, 8))

        self._stop_button = self._ttk.Button(buttons, text="Stop", command=self._stop_live)
        self._stop_button.pack(side=self._tk.LEFT, padx=(0, 8))

        self._hide_button = self._ttk.Button(
            buttons,
            text="Minimize To Tray",
            command=self._hide_to_tray,
        )
        self._hide_button.pack(side=self._tk.LEFT)

        status_label = self._ttk.Label(main_frame, textvariable=self._status_var)
        status_label.pack(fill=self._tk.X, pady=(8, 4))

        log_frame = self._ttk.LabelFrame(main_frame, text="Runtime Log", padding=6)
        log_frame.pack(fill=self._tk.BOTH, expand=True)

        scrollbar = self._ttk.Scrollbar(log_frame, orient=self._tk.VERTICAL)
        scrollbar.pack(side=self._tk.RIGHT, fill=self._tk.Y)

        self._log_widget = self._tk.Text(
            log_frame,
            wrap=self._tk.WORD,
            yscrollcommand=scrollbar.set,
            height=24,
        )
        self._log_widget.pack(fill=self._tk.BOTH, expand=True)
        scrollbar.config(command=self._log_widget.yview)

        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._toggle_iterations_state()

    def _setup_tray_if_available(self) -> None:
        if not self._tray_enabled:
            self._append_log("Tray disabled by launch option.")
            return
        if self._pystray is None or self._image is None or self._image_draw is None:
            self._append_log("Tray unavailable (install optional UI dependencies).")
            return
        if self._tray_icon is not None:
            return

        menu = self._pystray.Menu(
            self._pystray.MenuItem(
                "Pause",
                self._on_tray_pause,
                enabled=lambda _item: self._is_running(),
            ),
            self._pystray.MenuItem(
                "Resume",
                self._on_tray_resume,
                enabled=lambda _item: not self._is_running(),
            ),
            self._pystray.MenuItem("Open Settings", self._on_tray_open_settings),
            self._pystray.MenuItem("Exit", self._on_tray_exit),
        )
        icon_image = self._create_tray_image(is_running=False)
        self._tray_icon = self._pystray.Icon(
            "keylight",
            icon_image,
            "KeyLight (Idle)",
            menu,
        )
        self._tray_thread = threading.Thread(
            target=self._tray_icon.run,
            daemon=True,
        )
        self._tray_thread.start()
        self._append_log("Tray icon initialized.")

    def _create_tray_image(self, *, is_running: bool) -> Any:
        if self._image is None or self._image_draw is None:
            raise RuntimeError("Tray image module is unavailable.")
        background = (30, 170, 90) if is_running else (70, 70, 70)
        image = self._image.new(
            "RGB",
            (TRAY_ICON_SIZE, TRAY_ICON_SIZE),
            background,
        )
        draw = self._image_draw.Draw(image)
        draw.rectangle((10, 10, 54, 54), outline=(245, 245, 245), width=3)
        draw.rectangle((18, 18, 46, 46), fill=(245, 245, 245))
        draw.rectangle((24, 24, 40, 40), fill=background)
        return image

    def _update_tray_state(self) -> None:
        if self._tray_icon is None:
            return
        running = self._is_running()
        self._tray_icon.icon = self._create_tray_image(is_running=running)
        visibility = "Hidden" if not self._window_visible else "Visible"
        if running:
            self._tray_icon.title = f"KeyLight (Running, {visibility})"
        else:
            self._tray_icon.title = f"KeyLight (Idle, {visibility})"
        if hasattr(self._tray_icon, "update_menu"):
            self._tray_icon.update_menu()

    def _is_running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def _on_tray_pause(self, _icon: Any, _item: Any) -> None:
        self._root.after(0, self._stop_live)

    def _on_tray_resume(self, _icon: Any, _item: Any) -> None:
        self._root.after(0, self._start_live)

    def _on_tray_open_settings(self, _icon: Any, _item: Any) -> None:
        self._root.after(0, self._show_window)

    def _on_tray_exit(self, _icon: Any, _item: Any) -> None:
        self._root.after(0, self._exit_application)

    def _show_window(self) -> None:
        self._window_visible = True
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()
        self._status_var.set("Running" if self._is_running() else "Idle")
        self._append_log("Window restored from tray.")
        self._update_tray_state()

    def _hide_to_tray(self) -> bool:
        if self._tray_icon is None:
            return False
        self._window_visible = False
        self._root.withdraw()
        if self._is_running():
            self._status_var.set("Running (Tray)")
        else:
            self._status_var.set("Idle (Tray)")
        self._append_log("Window minimized to tray.")
        self._update_tray_state()
        return True

    def _add_label_entry(
        self,
        parent: Any,
        row: int,
        label: str,
        variable: Any,
        *,
        width: int,
        col: int = 0,
    ) -> None:
        text = self._ttk.Label(parent, text=label)
        text.grid(row=row, column=col, sticky=self._tk.W, padx=4, pady=4)
        entry = self._ttk.Entry(parent, textvariable=variable, width=width)
        entry.grid(row=row, column=col + 1, sticky=self._tk.W, padx=4, pady=4)

    def _detect_hid_path(self, *, silent: bool = False) -> None:
        try:
            devices = list_hid_devices()
        except RuntimeError as error:
            if not silent:
                self._messagebox.showerror("KeyLight", f"HID enumerate failed: {error}")
            self._append_log(f"HID enumerate failed: {error}")
            return
        selected = select_preferred_msi_hid_path(devices)
        if selected is None:
            if not silent:
                self._messagebox.showwarning(
                    "KeyLight",
                    "No MSI VID=1462 PID=1603 HID path found.",
                )
            return
        self._hid_path_var.set(selected)
        self._append_log(f"Detected HID path: {selected}")

    def _build_run_config(self) -> AppLiveRunConfig:
        rows = self._parse_int(self._rows_var.get(), "Rows")
        columns = self._parse_int(self._columns_var.get(), "Columns")
        fps = self._parse_int(self._fps_var.get(), "FPS")
        run_until_stopped = bool(self._run_until_stop_var.get())
        iterations = 1
        if not run_until_stopped:
            iterations = self._parse_int(self._iterations_var.get(), "Iterations")
        monitor_index = self._parse_int(self._monitor_var.get(), "Monitor index")
        output_name = f"live_report_gui_{datetime.now(tz=UTC).strftime('%Y%m%d_%H%M%S')}.json"
        output_path = (self._repo_root / "artifacts" / output_name).resolve()
        return AppLiveRunConfig(
            hid_path=self._hid_path_var.get().strip(),
            rows=rows,
            columns=columns,
            fps=fps,
            iterations=iterations,
            run_until_stopped=run_until_stopped,
            monitor_index=monitor_index,
            strict_preflight=bool(self._strict_var.get()),
            aggressive_msi_close=bool(self._aggressive_var.get()),
            output_path=output_path,
        )

    def _start_live(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._messagebox.showinfo("KeyLight", "Live session already running.")
            return
        try:
            run_config = self._build_run_config()
            command = build_live_command(
                python_executable=sys.executable,
                config=run_config,
            )
        except ValueError as error:
            self._messagebox.showerror("KeyLight", str(error))
            return

        self._append_log("")
        self._append_log("$ " + " ".join(command))
        try:
            self._process = subprocess.Popen(
                command,
                cwd=str(self._repo_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as error:
            self._messagebox.showerror("KeyLight", f"Failed to start live session: {error}")
            self._process = None
            return

        self._stdout_thread = threading.Thread(target=self._read_process_output, daemon=True)
        self._stdout_thread.start()
        self._set_running(True)
        self._status_var.set("Running")

    def _autostart_if_possible(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        if self._hid_path_var.get().strip() == "":
            self._detect_hid_path(silent=True)
        if self._hid_path_var.get().strip() == "":
            self._append_log(
                "Autostart skipped: MSI HID path not detected. Click 'Detect MSI HID' and retry."
            )
            self._status_var.set("Idle (HID not detected)")
            return
        self._append_log("Autostart: starting live session.")
        self._start_live()

    def _stop_live(self) -> None:
        if self._process is None or self._process.poll() is not None:
            return
        self._append_log("Stopping live session...")
        self._process.terminate()

    def _read_process_output(self) -> None:
        process = self._process
        if process is None:
            return
        output = process.stdout
        if output is None:
            return
        for line in output:
            self._log_queue.put(line.rstrip("\n"))

    def _drain_log_queue(self) -> None:
        while True:
            try:
                line = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(line)

        process = self._process
        if process is not None:
            exit_code = process.poll()
            if exit_code is not None:
                self._append_log(f"Live process exited with code {exit_code}.")
                self._set_running(False)
                if self._window_visible:
                    self._status_var.set("Idle")
                else:
                    self._status_var.set("Idle (Tray)")
                self._process = None

        self._root.after(120, self._drain_log_queue)

    def _set_running(self, is_running: bool) -> None:
        self._start_button.config(state=self._tk.DISABLED if is_running else self._tk.NORMAL)
        self._stop_button.config(state=self._tk.NORMAL if is_running else self._tk.DISABLED)
        if self._tray_icon is None:
            self._hide_button.config(state=self._tk.DISABLED)
        else:
            self._hide_button.config(state=self._tk.NORMAL)
        self._toggle_iterations_state()
        self._update_tray_state()

    def _toggle_iterations_state(self) -> None:
        state = self._tk.NORMAL
        if bool(self._run_until_stop_var.get()):
            state = self._tk.DISABLED
        self._iterations_entry.config(state=state)

    def _append_log(self, line: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._log_widget.insert(self._tk.END, f"[{timestamp}] {line}\n")
        self._log_widget.see(self._tk.END)

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

    def _on_close(self) -> None:
        if self._hide_to_tray():
            return
        self._exit_application()

    def _exit_application(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._append_log("Exiting KeyLight...")
        process = self._process
        if process is not None and process.poll() is None:
            self._append_log("Stopping live session...")
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        tray_icon = self._tray_icon
        if tray_icon is not None:
            self._tray_icon = None
            try:
                tray_icon.stop()
            except Exception:
                pass
        self._root.after(200, self._root.destroy)


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
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ModuleNotFoundError:
        print("Tkinter is not available in this Python installation.")
        return 1

    pystray_module: Any | None = None
    image_module: Any | None = None
    image_draw_module: Any | None = None
    if args.tray:
        try:
            pystray_module = importlib.import_module("pystray")
            image_module = importlib.import_module("PIL.Image")
            image_draw_module = importlib.import_module("PIL.ImageDraw")
        except ModuleNotFoundError:
            print(
                "Tray dependencies missing; running without tray. "
                "Install with: pip install -e \".[ui]\""
            )

    repo_root = Path.cwd().resolve()
    root = tk.Tk()
    KeyLightDesktopApp(
        root=root,
        repo_root=repo_root,
        tk_module=tk,
        ttk_module=ttk,
        messagebox_module=messagebox,
        pystray_module=pystray_module,
        image_module=image_module,
        image_draw_module=image_draw_module,
        autostart=args.autostart,
        tray_enabled=args.tray,
        start_hidden=args.start_hidden,
    )
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
