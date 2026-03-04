from __future__ import annotations

import ctypes
import json
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONFLICT_PROCESS_NAMES: tuple[str, ...] = (
    "LEDKeeper2",
    "OpenRGB",
    "SignalRgb",
    "SteelSeriesGG",
    "SteelSeriesEngine",
    "iCUE",
    "Corsair.Service",
    "RzSynapse",
    "RazerAppEngine",
    "lghub",
    "ghub",
    "logi_lamparray_service",
    "wallpaperservice32",
    "NVIDIA Overlay",
)


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    process_name: str
    pid: int


@dataclass(frozen=True, slots=True)
class ServiceInfo:
    name: str
    display_name: str
    state: str
    start_mode: str


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    friendly_name: str
    instance_id: str
    device_class: str
    status: str


@dataclass(frozen=True, slots=True)
class ProbeReport:
    generated_at_utc: str
    platform_name: str
    python_version: str
    is_admin: bool
    conflict_processes: list[ProcessInfo]
    candidate_services: list[ServiceInfo]
    candidate_devices: list[DeviceInfo]
    likely_control_paths: list[str]
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_probe() -> ProbeReport:
    platform_name = platform.platform()
    is_admin = _is_admin()

    if platform.system() != "Windows":
        return ProbeReport(
            generated_at_utc=_now_utc_iso(),
            platform_name=platform_name,
            python_version=sys.version.split()[0],
            is_admin=is_admin,
            conflict_processes=[],
            candidate_services=[],
            candidate_devices=[],
            likely_control_paths=["Windows-only target hardware path required."],
            recommendations=[
                "Run probe on Windows hardware (MSI Vector 16 HX AI A2XW).",
            ],
        )

    conflict_processes = _query_conflict_processes()
    services = _query_candidate_services()
    devices = _query_candidate_devices()
    likely_paths = infer_likely_control_paths(services, devices)
    recommendations = build_recommendations(
        is_admin=is_admin,
        conflict_processes=conflict_processes,
        services=services,
        devices=devices,
    )

    return ProbeReport(
        generated_at_utc=_now_utc_iso(),
        platform_name=platform_name,
        python_version=sys.version.split()[0],
        is_admin=is_admin,
        conflict_processes=conflict_processes,
        candidate_services=services,
        candidate_devices=devices,
        likely_control_paths=likely_paths,
        recommendations=recommendations,
    )


def write_probe_report(report: ProbeReport, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return output_path


def infer_likely_control_paths(
    services: list[ServiceInfo],
    devices: list[DeviceInfo],
) -> list[str]:
    joined_service_text = " ".join(
        f"{service.name} {service.display_name}" for service in services
    ).lower()
    joined_device_text = " ".join(device.friendly_name for device in devices).lower()

    candidates: list[str] = []
    if "steelseries" in joined_service_text or "steelseries" in joined_device_text:
        candidates.append("SteelSeries GG/Engine integration path")
    if "msi" in joined_service_text or "msi" in joined_device_text:
        candidates.append("MSI Center service bridge path")

    candidates.append("Direct HID vendor protocol path")
    return _unique_preserving_order(candidates)


def build_recommendations(
    *,
    is_admin: bool,
    conflict_processes: list[ProcessInfo],
    services: list[ServiceInfo],
    devices: list[DeviceInfo],
) -> list[str]:
    recommendations: list[str] = []
    if conflict_processes:
        recommendations.append(
            "Run scripts/preflight.ps1 (ideally as Administrator) before hardware tests."
        )

    if not is_admin:
        recommendations.append(
            "Run terminal as Administrator for stronger process/service/device access."
        )

    if not services:
        recommendations.append("No MSI/SteelSeries services found. Verify vendor software install.")

    if not devices:
        recommendations.append(
            "No candidate keyboard/HID devices matched. Verify chipset/keyboard drivers."
        )

    recommendations.append("Next: implement zone write probe and run 0..23 sweep calibration.")
    return _unique_preserving_order(recommendations)


def _query_conflict_processes() -> list[ProcessInfo]:
    targets = _powershell_string_array(CONFLICT_PROCESS_NAMES)
    command = (
        f"$targets=@({targets});"
        "Get-Process | "
        "Where-Object { $targets -contains $_.ProcessName } | "
        "Select-Object ProcessName,Id | "
        "ConvertTo-Json -Compress"
    )
    rows = _run_powershell_json(command)
    results: list[ProcessInfo] = []
    for row in rows:
        process_name = str(row.get("ProcessName", "")).strip()
        pid = _to_int(row.get("Id"))
        if process_name and pid > 0:
            results.append(ProcessInfo(process_name=process_name, pid=pid))
    return sorted(results, key=lambda item: (item.process_name, item.pid))


def _query_candidate_services() -> list[ServiceInfo]:
    command = (
        "Get-CimInstance Win32_Service | "
        "Where-Object { "
        "$_.Name -match 'MSI|SteelSeries' -or $_.DisplayName -match 'MSI|SteelSeries' "
        "} | "
        "Select-Object Name,DisplayName,State,StartMode | "
        "ConvertTo-Json -Compress"
    )
    rows = _run_powershell_json(command)
    excluded_names = {"msiserver", "msiscsi"}
    results: list[ServiceInfo] = []
    for row in rows:
        name = str(row.get("Name", "")).strip()
        display_name = str(row.get("DisplayName", "")).strip()
        state = str(row.get("State", "")).strip()
        start_mode = str(row.get("StartMode", "")).strip()
        if name and name.lower() not in excluded_names:
            results.append(
                ServiceInfo(
                    name=name,
                    display_name=display_name,
                    state=state,
                    start_mode=start_mode,
                )
            )
    return sorted(results, key=lambda item: item.name.lower())


def _query_candidate_devices() -> list[DeviceInfo]:
    command = (
        "Get-PnpDevice -PresentOnly | "
        "Where-Object { "
        "($_.Class -eq 'Keyboard' -or $_.Class -eq 'HIDClass') -and "
        "($_.FriendlyName -match 'MSI|SteelSeries|Keyboard') "
        "} | "
        "Select-Object FriendlyName,InstanceId,Class,Status | "
        "ConvertTo-Json -Compress"
    )
    rows = _run_powershell_json(command)
    results: list[DeviceInfo] = []
    for row in rows:
        friendly_name = str(row.get("FriendlyName", "")).strip()
        instance_id = str(row.get("InstanceId", "")).strip()
        device_class = str(row.get("Class", "")).strip()
        status = str(row.get("Status", "")).strip()
        if friendly_name:
            results.append(
                DeviceInfo(
                    friendly_name=friendly_name,
                    instance_id=instance_id,
                    device_class=device_class,
                    status=status,
                )
            )
    return sorted(results, key=lambda item: item.friendly_name.lower())


def _run_powershell_json(command: str) -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return []

    output = completed.stdout.strip()
    if not output:
        return []

    try:
        parsed: Any = json.loads(output)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _powershell_string_array(values: tuple[str, ...]) -> str:
    escaped_values = [f"'{value.replace(chr(39), chr(39) * 2)}'" for value in values]
    return ",".join(escaped_values)


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _now_utc_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _is_admin() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False
