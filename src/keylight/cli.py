from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from keylight.calibrate_zones import (
    CalibrateZonesReport,
    now_utc_iso,
    write_calibrate_zones_report,
    write_observed_order_template,
)
from keylight.calibration import (
    CalibratedDriver,
    identity_profile,
    load_calibration_profile,
    profile_from_observed_order,
    write_calibration_profile,
)
from keylight.capture.mock import MockGradientCapturer
from keylight.capture.windows_mss import WindowsMssCapturer, list_monitors
from keylight.drivers.hid_raw import list_hid_devices
from keylight.drivers.msi_mystic_hid import MsiMysticHidConfig, MsiMysticHidDriver
from keylight.drivers.probe import run_probe, write_probe_report
from keylight.drivers.simulated import SimulatedKeyboardDriver
from keylight.effect_verify import (
    EffectVerificationConfig,
    EffectVerificationStep,
    default_accepted_candidates,
    default_color_sequence,
    run_effect_verification,
    write_effect_verification_report,
)
from keylight.hid_discovery import (
    DiscoveryTemplate,
    HidDiscoveryConfig,
    run_hid_discovery,
    write_hid_discovery_report,
)
from keylight.interactive_calibration import capture_observed_order_interactive
from keylight.live import (
    LiveEventLogEntry,
    LiveRuntime,
    LiveRuntimeConfig,
    LiveWatchdogSnapshot,
    write_live_event_log_entry,
    write_live_runtime_report,
    write_live_watchdog_snapshot,
)
from keylight.live_analysis import (
    LiveQualityThresholds,
    analyze_live_run,
    write_live_analysis_report,
)
from keylight.mapping.calibrated_mapper import CalibratedZoneMapper, load_zone_geometry_profile
from keylight.mapping.grid_mapper import GridLayout, GridZoneMapper
from keylight.mapping.profile_builder import (
    ZoneProfileBuildConfig,
    build_zone_geometry_profile,
    write_zone_geometry_profile,
)
from keylight.models import RgbColor, ZoneColor
from keylight.pipeline import KeyLightPipeline, PipelineConfig
from keylight.processing import ColorProcessingConfig, ZoneColorProcessor
from keylight.readiness import ReadinessCheckConfig, run_readiness_check, write_readiness_report
from keylight.runtime_config import LiveCommandDefaults, load_live_command_defaults
from keylight.runtime_config_writer import write_live_defaults_toml
from keylight.sweep import SweepConfig, ZoneSweeper, write_sweep_report
from keylight.write_zone import (
    WriteZoneConfig,
    execute_write_zone,
    write_write_zone_report,
)
from keylight.zone_protocol_verify import (
    ZoneProtocolVerifyConfig,
    ZoneProtocolVerifyStep,
    default_zone_probe_offsets,
    run_zone_protocol_verify,
    write_zone_protocol_verify_report,
)


def _build_run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KeyLight CLI")
    parser.add_argument("--rows", type=int, default=2, help="Keyboard zone rows")
    parser.add_argument("--columns", type=int, default=12, help="Keyboard zone columns")
    parser.add_argument("--fps", type=int, default=30, help="Pipeline update rate")
    parser.add_argument("--iterations", type=int, default=1, help="Frame iterations to run")
    return parser


def _build_probe_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KeyLight hardware discovery probe")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/probe_report.json"),
        help="Path for probe JSON report",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print report JSON to stdout",
    )
    return parser


def _build_sweep_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KeyLight zone sweep calibration")
    parser.add_argument(
        "--backend",
        choices=["simulated", "msi-mystic-hid"],
        default="simulated",
        help="Driver backend for sweep execution",
    )
    parser.add_argument(
        "--zone-count",
        type=int,
        default=24,
        help="Number of keyboard lighting zones",
    )
    parser.add_argument(
        "--loops",
        type=int,
        default=1,
        help="How many complete 0..N-1 sweeps to run",
    )
    parser.add_argument("--delay-ms", type=int, default=350, help="Delay between zone steps")
    parser.add_argument("--reverse", action="store_true", help="Sweep in reverse (N-1 down to 0)")
    parser.add_argument(
        "--active-color",
        type=str,
        default="255,0,0",
        help="RGB for active zone, format: R,G,B",
    )
    parser.add_argument(
        "--inactive-color",
        type=str,
        default="0,0,0",
        help="RGB for inactive zones, format: R,G,B",
    )
    parser.add_argument(
        "--no-preflight",
        action="store_true",
        help="Skip scripts/preflight.ps1 before sweep",
    )
    parser.add_argument(
        "--strict-preflight",
        action="store_true",
        help="Fail startup if preflight reports unresolved conflicts",
    )
    parser.add_argument(
        "--aggressive-msi-close",
        action="store_true",
        help="Use aggressive MSI close mode in preflight",
    )
    parser.add_argument(
        "--hid-path",
        type=str,
        default=None,
        help="HID path for msi-mystic-hid backend",
    )
    parser.add_argument("--vendor-id", type=str, default=None, help="HID VID")
    parser.add_argument("--product-id", type=str, default=None, help="HID PID")
    parser.add_argument(
        "--report-id",
        type=int,
        default=1,
        help="HID report_id placeholder value",
    )
    parser.add_argument(
        "--write-method",
        choices=["output", "feature"],
        default="output",
        help="HID write method for msi-mystic-hid backend",
    )
    parser.add_argument(
        "--pad-length",
        type=int,
        default=64,
        help="Packet length for msi-mystic-hid backend",
    )
    parser.add_argument(
        "--packet-template",
        type=str,
        default="{report_id} {zone} {r} {g} {b}",
        help="Packet template for msi-mystic-hid backend",
    )
    parser.add_argument(
        "--calibration-profile",
        type=Path,
        default=None,
        help="Optional logical->hardware zone mapping JSON profile",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/sweep_report.json"),
        help="Path for sweep JSON report",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print report JSON to stdout",
    )
    return parser


def _build_write_zone_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KeyLight single-zone write probe")
    parser.add_argument(
        "--backend",
        choices=["simulated", "hid-raw", "msi-mystic-hid"],
        default="simulated",
        help="Driver backend for single-zone write",
    )
    parser.add_argument("--zone-index", type=int, default=0, help="Target zone index to set")
    parser.add_argument("--zone-count", type=int, default=24, help="Total zone count")
    parser.add_argument(
        "--color",
        type=str,
        default="255,0,0",
        help="Target color, format: R,G,B",
    )
    parser.add_argument(
        "--packet-template",
        type=str,
        default=None,
        help="HID packet template tokens (e.g. '{report_id} 0xAA {zone} {r} {g} {b}')",
    )
    parser.add_argument(
        "--calibration-profile",
        type=Path,
        default=None,
        help="Optional logical->hardware zone mapping JSON profile",
    )
    parser.add_argument("--report-id", type=int, default=0, help="Value used for {report_id}")
    parser.add_argument(
        "--write-method",
        choices=["output", "feature"],
        default="output",
        help="HID write method",
    )
    parser.add_argument(
        "--pad-to",
        type=int,
        default=None,
        help="Pad packet with trailing zeros up to this byte length",
    )
    parser.add_argument(
        "--hid-path",
        type=str,
        default=None,
        help="HID path returned by --list-hid",
    )
    parser.add_argument(
        "--vendor-id",
        type=str,
        default=None,
        help="Hex or decimal VID (e.g. 0x1462)",
    )
    parser.add_argument(
        "--product-id",
        type=str,
        default=None,
        help="Hex or decimal PID",
    )
    parser.add_argument(
        "--list-hid",
        action="store_true",
        help="List HID devices and exit",
    )
    parser.add_argument(
        "--no-preflight",
        action="store_true",
        help="Skip scripts/preflight.ps1 before write-zone",
    )
    parser.add_argument(
        "--strict-preflight",
        action="store_true",
        help="Fail startup if preflight reports unresolved conflicts",
    )
    parser.add_argument(
        "--aggressive-msi-close",
        action="store_true",
        help="Use aggressive MSI close mode in preflight",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/write_zone_report.json"),
        help="Path for write-zone JSON report",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print report JSON to stdout",
    )
    return parser


def _build_discover_hid_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KeyLight HID packet discovery")
    parser.add_argument("--hid-path", type=str, default=None, help="Target HID path")
    parser.add_argument("--vendor-id", type=str, default=None, help="Target VID")
    parser.add_argument("--product-id", type=str, default=None, help="Target PID")
    parser.add_argument("--zone-index", type=int, default=0, help="Zone index placeholder value")
    parser.add_argument("--color", type=str, default="255,0,0", help="Color placeholder value")
    parser.add_argument(
        "--write-methods",
        type=str,
        default="output,feature",
        help="Comma-separated write methods",
    )
    parser.add_argument(
        "--report-ids",
        type=str,
        default="0,1,2,3,4,5,10,16",
        help="Comma-separated report-id values",
    )
    parser.add_argument(
        "--pad-lengths",
        type=str,
        default="8,16,32,64,65",
        help="Comma-separated packet lengths",
    )
    parser.add_argument(
        "--template",
        action="append",
        dest="templates",
        help="Template to probe (repeatable). Uses placeholders from write-zone.",
    )
    parser.add_argument("--delay-ms", type=int, default=20, help="Delay between probe attempts")
    parser.add_argument(
        "--stop-on-first-success",
        action="store_true",
        help="Stop immediately after first successful write",
    )
    parser.add_argument(
        "--no-preflight",
        action="store_true",
        help="Skip scripts/preflight.ps1 before discovery",
    )
    parser.add_argument(
        "--strict-preflight",
        action="store_true",
        help="Fail startup if preflight reports unresolved conflicts",
    )
    parser.add_argument(
        "--aggressive-msi-close",
        action="store_true",
        help="Use aggressive MSI close mode in preflight",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/hid_discovery_report.json"),
        help="Path for HID discovery report",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print full discovery JSON",
    )
    return parser


def _build_discover_effects_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KeyLight HID effect verification runner")
    parser.add_argument("--hid-path", type=str, default=None, help="Target HID path")
    parser.add_argument("--vendor-id", type=str, default=None, help="Target VID")
    parser.add_argument("--product-id", type=str, default=None, help="Target PID")
    parser.add_argument(
        "--zone-sequence",
        type=str,
        default="0,5,11,17,23",
        help="Comma-separated zone indexes used across verification steps",
    )
    parser.add_argument(
        "--step-delay-ms",
        type=int,
        default=1200,
        help="Delay between visual verification steps",
    )
    parser.add_argument("--repeat", type=int, default=1, help="How many cycles of candidate set")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Optional cap on number of verification steps",
    )
    parser.add_argument(
        "--pad-length",
        type=int,
        default=64,
        help="Packet length for accepted verification candidates",
    )
    parser.add_argument(
        "--no-preflight",
        action="store_true",
        help="Skip scripts/preflight.ps1 before effect verification",
    )
    parser.add_argument(
        "--strict-preflight",
        action="store_true",
        help="Fail startup if preflight reports unresolved conflicts",
    )
    parser.add_argument(
        "--aggressive-msi-close",
        action="store_true",
        help="Use aggressive MSI close mode in preflight",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/effect_verify_report.json"),
        help="Path for effect verification report",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print full verification JSON",
    )
    return parser


def _build_discover_zone_protocol_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KeyLight MSI zone-protocol verifier")
    parser.add_argument("--hid-path", type=str, default=None, help="Target HID path")
    parser.add_argument("--vendor-id", type=str, default=None, help="Target VID")
    parser.add_argument("--product-id", type=str, default=None, help="Target PID")
    parser.add_argument(
        "--zone-sequence",
        type=str,
        default="0,5,11,17,23",
        help="Comma-separated zone indexes injected into candidate offsets",
    )
    parser.add_argument(
        "--offsets",
        type=str,
        default="3,4,5,6,7,8,9,10,14,18,19,20,21,22,23,24",
        help="Comma-separated color-packet byte offsets to inject with zone index",
    )
    parser.add_argument(
        "--step-delay-ms",
        type=int,
        default=1200,
        help="Delay between visual verification steps",
    )
    parser.add_argument("--repeat", type=int, default=1, help="How many cycles of offset set")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Optional cap on number of verification steps",
    )
    parser.add_argument(
        "--pad-length",
        type=int,
        default=64,
        help="Packet length for MSI feature reports",
    )
    parser.add_argument(
        "--brightness",
        type=int,
        default=0x64,
        help="Brightness byte used in the base MSI color packet",
    )
    parser.add_argument(
        "--transition",
        type=int,
        default=0x32,
        help="Transition byte used in the base MSI color packet",
    )
    parser.add_argument(
        "--profile-slot",
        type=int,
        default=0x58,
        help="Profile slot byte used in the base MSI color packet",
    )
    parser.add_argument(
        "--effect-code",
        type=int,
        default=0x08,
        help="Effect code byte used in the base MSI color packet",
    )
    parser.add_argument(
        "--default-offsets",
        action="store_true",
        help="Use built-in default offset list and ignore --offsets",
    )
    parser.add_argument(
        "--no-preflight",
        action="store_true",
        help="Skip scripts/preflight.ps1 before zone-protocol verification",
    )
    parser.add_argument(
        "--strict-preflight",
        action="store_true",
        help="Fail startup if preflight reports unresolved conflicts",
    )
    parser.add_argument(
        "--aggressive-msi-close",
        action="store_true",
        help="Use aggressive MSI close mode in preflight",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/zone_protocol_verify_report.json"),
        help="Path for zone protocol verification report",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print full verification JSON",
    )
    return parser


def _build_init_calibration_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize an identity calibration profile")
    parser.add_argument("--zone-count", type=int, default=24, help="Profile zone count")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("config/calibration/default.json"),
        help="Output path for calibration profile",
    )
    return parser


def _build_build_calibration_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build calibration profile from observed sweep order"
    )
    parser.add_argument("--zone-count", type=int, default=24, help="Profile zone count")
    parser.add_argument(
        "--order",
        type=str,
        default=None,
        help="Observed order as comma/space separated hardware indexes",
    )
    parser.add_argument(
        "--order-file",
        type=Path,
        default=None,
        help="File containing observed order values",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("config/calibration/observed.json"),
        help="Output path for generated calibration profile",
    )
    return parser


def _build_calibrate_zones_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run sweep and build calibration profile from observed zone order"
    )
    parser.add_argument(
        "--backend",
        choices=["simulated", "msi-mystic-hid"],
        default="simulated",
        help="Driver backend for sweep execution",
    )
    parser.add_argument("--zone-count", type=int, default=24, help="Number of keyboard zones")
    parser.add_argument("--loops", type=int, default=1, help="Sweep loops")
    parser.add_argument("--delay-ms", type=int, default=800, help="Delay between sweep steps")
    parser.add_argument("--reverse", action="store_true", help="Sweep in reverse order")
    parser.add_argument(
        "--active-color",
        type=str,
        default="255,0,0",
        help="RGB for active zone, format: R,G,B",
    )
    parser.add_argument(
        "--inactive-color",
        type=str,
        default="0,0,0",
        help="RGB for inactive zones, format: R,G,B",
    )
    parser.add_argument(
        "--no-sweep",
        action="store_true",
        help="Skip sweep and only process observed-order/template output",
    )
    parser.add_argument(
        "--observed-order",
        type=str,
        default=None,
        help="Observed hardware indexes for logical zones 0..N-1",
    )
    parser.add_argument(
        "--observed-order-file",
        type=Path,
        default=None,
        help="File containing observed order values or observed_order=<values>",
    )
    parser.add_argument(
        "--template-output",
        type=Path,
        default=Path("artifacts/observed_order_template.txt"),
        help="Output path for observed-order template when order is not provided",
    )
    parser.add_argument(
        "--profile-output",
        type=Path,
        default=Path("config/calibration/final.json"),
        help="Output path for generated calibration profile",
    )
    parser.add_argument(
        "--sweep-output",
        type=Path,
        default=Path("artifacts/calibrate_sweep_report.json"),
        help="Output path for sweep report",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/calibrate_report.json"),
        help="Output path for calibration workflow report",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run verification sweep using resolved calibration profile",
    )
    parser.add_argument(
        "--verify-loops",
        type=int,
        default=1,
        help="Sweep loops for verification run",
    )
    parser.add_argument(
        "--verify-delay-ms",
        type=int,
        default=None,
        help="Delay between steps for verification run (defaults to --delay-ms)",
    )
    parser.add_argument(
        "--verify-reverse",
        action="store_true",
        help="Reverse verification sweep order",
    )
    parser.add_argument(
        "--verify-output",
        type=Path,
        default=Path("artifacts/calibrate_verify_sweep_report.json"),
        help="Output path for verification sweep report",
    )
    parser.add_argument(
        "--verify-live",
        action="store_true",
        help="Run a short live runtime with the resolved calibration profile",
    )
    parser.add_argument(
        "--live-capturer",
        choices=["windows-mss", "mock"],
        default="mock",
        help="Capturer backend for live verification",
    )
    parser.add_argument(
        "--live-monitor-index",
        type=int,
        default=1,
        help="Monitor index for windows-mss live verification",
    )
    parser.add_argument(
        "--live-capture-width",
        type=int,
        default=120,
        help="Capture width for live verification",
    )
    parser.add_argument(
        "--live-capture-height",
        type=int,
        default=20,
        help="Capture height for live verification",
    )
    parser.add_argument(
        "--live-mapper",
        choices=["grid", "calibrated"],
        default="grid",
        help="Mapper backend for live verification",
    )
    parser.add_argument(
        "--live-zone-profile",
        type=Path,
        default=None,
        help="Zone geometry profile used when --live-mapper=calibrated",
    )
    parser.add_argument("--live-rows", type=int, default=2, help="Grid rows for live verification")
    parser.add_argument(
        "--live-columns",
        type=int,
        default=12,
        help="Grid columns for live verification",
    )
    parser.add_argument("--live-fps", type=int, default=30, help="Live verification FPS")
    parser.add_argument(
        "--live-iterations",
        type=int,
        default=120,
        help="Live verification iterations",
    )
    parser.add_argument(
        "--live-output",
        type=Path,
        default=Path("artifacts/calibrate_verify_live_report.json"),
        help="Output path for live verification report",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print calibration workflow JSON report",
    )
    parser.add_argument("--hid-path", type=str, default=None, help="HID path for msi-mystic-hid")
    parser.add_argument("--vendor-id", type=str, default=None, help="HID VID")
    parser.add_argument("--product-id", type=str, default=None, help="HID PID")
    parser.add_argument(
        "--report-id",
        type=int,
        default=1,
        help="HID report_id placeholder value",
    )
    parser.add_argument(
        "--write-method",
        choices=["output", "feature"],
        default="output",
        help="HID write method for msi-mystic-hid backend",
    )
    parser.add_argument(
        "--pad-length",
        type=int,
        default=64,
        help="Packet length for msi-mystic-hid backend",
    )
    parser.add_argument(
        "--packet-template",
        type=str,
        default="{report_id} {zone} {r} {g} {b}",
        help="Packet template for msi-mystic-hid backend",
    )
    parser.add_argument(
        "--no-preflight",
        action="store_true",
        help="Skip scripts/preflight.ps1 before sweep",
    )
    parser.add_argument(
        "--strict-preflight",
        action="store_true",
        help="Fail startup if preflight reports unresolved conflicts",
    )
    parser.add_argument(
        "--aggressive-msi-close",
        action="store_true",
        help="Use aggressive MSI close mode in preflight",
    )
    return parser


def _build_build_zone_profile_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build calibrated zone geometry profile JSON")
    parser.add_argument("--rows", type=int, default=2, help="Zone rows")
    parser.add_argument("--columns", type=int, default=12, help="Zone columns")
    parser.add_argument(
        "--row-weights",
        type=str,
        default=None,
        help="Comma-separated row weights",
    )
    parser.add_argument(
        "--column-weights",
        type=str,
        default=None,
        help="Comma-separated column weights used for all rows",
    )
    parser.add_argument(
        "--row-column-weights",
        type=str,
        default=None,
        help=(
            "Per-row column weights with ';' row separators, e.g. "
            "'1,1,2;1,2,1' for 2 rows x 3 columns"
        ),
    )
    parser.add_argument("--x-start", type=float, default=0.0, help="Normalized x start")
    parser.add_argument("--x-end", type=float, default=1.0, help="Normalized x end")
    parser.add_argument("--y-start", type=float, default=0.0, help="Normalized y start")
    parser.add_argument("--y-end", type=float, default=1.0, help="Normalized y end")
    parser.add_argument(
        "--row-direction",
        choices=["top-to-bottom", "bottom-to-top"],
        default="top-to-bottom",
        help="Logical row traversal direction",
    )
    parser.add_argument(
        "--column-direction",
        choices=["left-to-right", "right-to-left"],
        default="left-to-right",
        help="Logical column traversal direction",
    )
    parser.add_argument(
        "--serpentine",
        action="store_true",
        help="Reverse column traversal every other row",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("config/mapping/generated.json"),
        help="Output path for zone geometry profile",
    )
    return parser


def _build_live_parser(defaults: LiveCommandDefaults) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KeyLight live screen-to-keyboard runtime")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/default.toml"),
        help="TOML runtime config file",
    )
    parser.add_argument(
        "--capturer",
        choices=["windows-mss", "mock"],
        default=defaults.capturer,
        help="Frame capturer backend",
    )
    parser.add_argument(
        "--monitor-index",
        type=int,
        default=defaults.monitor_index,
        help="Monitor index for windows-mss",
    )
    parser.add_argument(
        "--capture-width",
        type=int,
        default=defaults.capture_width,
        help="Capture downsample width",
    )
    parser.add_argument(
        "--capture-height",
        type=int,
        default=defaults.capture_height,
        help="Capture downsample height",
    )
    parser.add_argument(
        "--mapper",
        choices=["grid", "calibrated"],
        default=defaults.mapper,
        help="Zone mapper backend",
    )
    parser.add_argument(
        "--zone-profile",
        type=Path,
        default=defaults.zone_profile,
        help="JSON zone geometry profile for calibrated mapper",
    )
    parser.add_argument("--rows", type=int, default=defaults.rows, help="Zone mapper rows")
    parser.add_argument(
        "--columns",
        type=int,
        default=defaults.columns,
        help="Zone mapper columns",
    )
    parser.add_argument("--fps", type=int, default=defaults.fps, help="Target runtime FPS")
    parser.add_argument(
        "--iterations",
        type=int,
        default=defaults.iterations,
        help="Runtime loop iterations",
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=None,
        help="Run for fixed duration seconds (overrides --iterations)",
    )
    parser.add_argument(
        "--backend",
        choices=["simulated", "msi-mystic-hid"],
        default=defaults.backend,
        help="Keyboard backend",
    )
    parser.add_argument(
        "--hid-path",
        type=str,
        default=defaults.hid_path,
        help="HID path for msi-mystic-hid",
    )
    parser.add_argument("--vendor-id", type=str, default=defaults.vendor_id, help="HID VID")
    parser.add_argument("--product-id", type=str, default=defaults.product_id, help="HID PID")
    parser.add_argument(
        "--report-id",
        type=int,
        default=defaults.report_id,
        help="HID report_id placeholder",
    )
    parser.add_argument(
        "--write-method",
        choices=["output", "feature"],
        default=defaults.write_method,
        help="HID write method",
    )
    parser.add_argument(
        "--pad-length",
        type=int,
        default=defaults.pad_length,
        help="HID packet length",
    )
    parser.add_argument(
        "--packet-template",
        type=str,
        default=defaults.packet_template,
        help="HID packet template",
    )
    parser.add_argument(
        "--calibration-profile",
        type=Path,
        default=defaults.calibration_profile,
        help="Optional logical->hardware zone mapping profile",
    )
    parser.add_argument(
        "--smoothing-enabled",
        action=argparse.BooleanOptionalAction,
        default=defaults.smoothing_enabled,
        help="Enable temporal smoothing",
    )
    parser.add_argument(
        "--smoothing-alpha",
        type=float,
        default=defaults.smoothing_alpha,
        help="Smoothing alpha 0..1",
    )
    parser.add_argument(
        "--brightness-max-percent",
        type=int,
        default=defaults.brightness_max_percent,
        help="Global brightness cap percent",
    )
    parser.add_argument(
        "--max-consecutive-errors",
        type=int,
        default=defaults.max_consecutive_errors,
        help="Abort after this many frame errors in a row",
    )
    parser.add_argument(
        "--error-backoff-ms",
        type=int,
        default=defaults.error_backoff_ms,
        help="Backoff delay after frame errors",
    )
    parser.add_argument(
        "--stop-on-error",
        action=argparse.BooleanOptionalAction,
        default=defaults.stop_on_error,
        help="Stop runtime immediately on first frame error",
    )
    parser.add_argument(
        "--reconnect-on-error",
        action=argparse.BooleanOptionalAction,
        default=defaults.reconnect_on_error,
        help="Attempt driver recovery after frame errors",
    )
    parser.add_argument(
        "--reconnect-attempts",
        type=int,
        default=defaults.reconnect_attempts,
        help="Recovery attempts per frame error (0 disables)",
    )
    parser.add_argument(
        "--strict-preflight",
        action=argparse.BooleanOptionalAction,
        default=defaults.strict_preflight,
        help="Fail startup if preflight reports unresolved conflicts",
    )
    parser.add_argument(
        "--watchdog-interval",
        type=int,
        default=defaults.watchdog_interval_iterations,
        help="Write watchdog snapshot every N attempted iterations (0 disables)",
    )
    parser.add_argument(
        "--watchdog-output",
        type=Path,
        default=defaults.watchdog_output
        if defaults.watchdog_output is not None
        else Path("artifacts/live_watchdog.json"),
        help="Path for watchdog snapshot JSON output",
    )
    parser.add_argument(
        "--event-log-interval",
        type=int,
        default=defaults.event_log_interval_iterations,
        help="Append event log entry every N attempted iterations (0 disables)",
    )
    parser.add_argument(
        "--event-log-output",
        type=Path,
        default=defaults.event_log_output
        if defaults.event_log_output is not None
        else Path("artifacts/live_events.jsonl"),
        help="Path for event log JSONL output",
    )
    parser.add_argument(
        "--restore-on-exit",
        action=argparse.BooleanOptionalAction,
        default=defaults.restore_on_exit,
        help="Apply restore color to all zones after runtime exits",
    )
    parser.add_argument(
        "--restore-color",
        type=str,
        default=defaults.restore_color,
        help="Restore RGB color format R,G,B (used with --restore-on-exit)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/live_report.json"),
        help="Path for live runtime JSON report",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print live runtime JSON report to stdout",
    )
    parser.add_argument(
        "--no-preflight",
        action="store_true",
        help="Skip scripts/preflight.ps1 before runtime",
    )
    parser.add_argument(
        "--aggressive-msi-close",
        action="store_true",
        help="Use aggressive MSI close mode in preflight",
    )
    return parser


def _resolve_live_defaults(argv: list[str]) -> LiveCommandDefaults:
    config_parser = argparse.ArgumentParser(add_help=False)
    config_parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/default.toml"),
    )
    config_args, _ = config_parser.parse_known_args(argv)
    return load_live_command_defaults(
        config_args.config,
        must_exist=_option_present(argv, "--config"),
    )


def _option_present(argv: list[str], option: str) -> bool:
    for arg in argv:
        if arg == option or arg.startswith(f"{option}="):
            return True
    return False


def _build_list_monitors_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="List Windows monitors visible to mss")


def _build_analyze_live_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze live runtime artifacts")
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Path to live runtime JSON report",
    )
    parser.add_argument(
        "--event-log",
        type=Path,
        default=None,
        help="Optional path to live event JSONL log",
    )
    parser.add_argument(
        "--max-error-rate-percent",
        type=float,
        default=1.0,
        help="Fail if error rate exceeds this percent",
    )
    parser.add_argument(
        "--max-avg-total-ms",
        type=float,
        default=80.0,
        help="Fail if avg_total_ms exceeds this threshold",
    )
    parser.add_argument(
        "--max-p95-total-ms",
        type=float,
        default=120.0,
        help="Fail if event-log p95 total_ms exceeds this threshold",
    )
    parser.add_argument(
        "--min-effective-fps",
        type=float,
        default=0.0,
        help="Fail if effective FPS is below this threshold",
    )
    parser.add_argument(
        "--max-overrun-percent",
        type=float,
        default=100.0,
        help="Fail if overrun iteration percent exceeds this threshold",
    )
    parser.add_argument(
        "--require-no-abort",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require report.aborted=false",
    )
    parser.add_argument(
        "--min-completed-iterations",
        type=int,
        default=1,
        help="Fail if completed iterations are below this count",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/live_analysis_report.json"),
        help="Output path for analysis JSON report",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print analysis JSON to stdout",
    )
    return parser


def _build_readiness_check_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate readiness for hardware long-runs")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/default.toml"),
        help="TOML runtime config file",
    )
    parser.add_argument(
        "--require-hardware-backend",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require driver.backend to be msi-mystic-hid",
    )
    parser.add_argument(
        "--require-calibrated-mapper",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require mapping.backend to be calibrated",
    )
    parser.add_argument(
        "--require-calibration-profile",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require driver.calibration_profile to be set and valid",
    )
    parser.add_argument(
        "--require-calibration-profile-generated-timestamp",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require calibration profile generated_at_utc metadata",
    )
    parser.add_argument(
        "--require-calibration-profile-provenance",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require calibration profile provenance metadata and observed-order match",
    )
    parser.add_argument(
        "--require-calibration-profile-provenance-workflow-match",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Require calibration profile provenance workflow_report_path "
            "matches configured workflow report"
        ),
    )
    parser.add_argument(
        "--max-calibration-profile-age-seconds",
        type=int,
        default=None,
        help="Optional max allowed calibration profile age in seconds",
    )
    parser.add_argument(
        "--forbid-identity-calibration",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Fail when calibration profile is identity 0..N-1 mapping",
    )
    parser.add_argument(
        "--require-calibration-workflow",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require calibrate-zones workflow report checks to pass",
    )
    parser.add_argument(
        "--calibration-workflow-report",
        type=Path,
        default=Path("artifacts/calibrate_report_final.json"),
        help="Path to calibrate-zones workflow report JSON",
    )
    parser.add_argument(
        "--max-calibration-workflow-age-seconds",
        type=int,
        default=None,
        help="Optional max allowed calibration workflow report age in seconds",
    )
    parser.add_argument(
        "--require-calibration-verify-executed",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require verify sweep to be executed in calibration workflow report",
    )
    parser.add_argument(
        "--require-calibration-live-verify-executed",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require live verify step to be executed in calibration workflow report",
    )
    parser.add_argument(
        "--require-calibration-live-verify-success",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require live verify step to complete without error in workflow report",
    )
    parser.add_argument(
        "--require-preflight-clean",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require unresolved_count==0 in preflight report",
    )
    parser.add_argument(
        "--require-preflight-admin",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require preflight report is_admin=true",
    )
    parser.add_argument(
        "--require-preflight-strict-mode",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require preflight report strict_mode=true",
    )
    parser.add_argument(
        "--require-preflight-access-denied-clear",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require preflight access_denied_count==0",
    )
    parser.add_argument(
        "--preflight-report",
        type=Path,
        default=Path("artifacts/preflight_report.json"),
        help="Path to preflight JSON report",
    )
    parser.add_argument(
        "--run-preflight",
        action="store_true",
        help="Run scripts/preflight.ps1 before readiness evaluation",
    )
    parser.add_argument(
        "--preflight-strict-mode",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use preflight strict mode when --run-preflight is enabled",
    )
    parser.add_argument(
        "--preflight-aggressive-msi-close",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use aggressive MSI close mode when --run-preflight is enabled",
    )
    parser.add_argument(
        "--max-preflight-age-seconds",
        type=int,
        default=None,
        help="Optional max allowed preflight report age in seconds",
    )
    parser.add_argument(
        "--require-live-analysis-pass",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require passed=true in live analysis report",
    )
    parser.add_argument(
        "--live-analysis-report",
        type=Path,
        default=Path("artifacts/live_analysis_report.json"),
        help="Path to live analysis JSON report",
    )
    parser.add_argument(
        "--max-live-analysis-age-seconds",
        type=int,
        default=None,
        help="Optional max allowed live analysis report age in seconds",
    )
    parser.add_argument(
        "--max-live-analysis-threshold-max-error-rate-percent",
        type=float,
        default=None,
        help="Require analysis threshold max_error_rate_percent <= this value",
    )
    parser.add_argument(
        "--max-live-analysis-threshold-max-avg-total-ms",
        type=float,
        default=None,
        help="Require analysis threshold max_avg_total_ms <= this value",
    )
    parser.add_argument(
        "--max-live-analysis-threshold-max-p95-total-ms",
        type=float,
        default=None,
        help="Require analysis threshold max_p95_total_ms <= this value",
    )
    parser.add_argument(
        "--min-live-analysis-threshold-min-effective-fps",
        type=float,
        default=None,
        help="Require analysis threshold min_effective_fps >= this value",
    )
    parser.add_argument(
        "--max-live-analysis-threshold-max-overrun-percent",
        type=float,
        default=None,
        help="Require analysis threshold max_overrun_percent <= this value",
    )
    parser.add_argument(
        "--require-hid-present",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require HID target to be present in current enumeration",
    )
    parser.add_argument(
        "--hid-path",
        type=str,
        default=None,
        help="Optional HID path override for presence check",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/readiness_report.json"),
        help="Path for readiness JSON report",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print readiness JSON report to stdout",
    )
    return parser


def _build_runtime_config_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build runtime TOML config from presets/overrides")
    parser.add_argument(
        "--base",
        type=Path,
        default=Path("config/default.toml"),
        help="Base TOML runtime config file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("config/hardware-final.toml"),
        help="Output TOML runtime config file",
    )
    parser.add_argument(
        "--set-hardware-mode",
        action="store_true",
        help="Preset: backend=msi-mystic-hid, mapper=calibrated, capturer=windows-mss",
    )
    parser.add_argument(
        "--set-longrun-mode",
        action="store_true",
        help="Preset: strict preflight, watchdog/event logs, restore-on-exit",
    )
    parser.add_argument("--backend", choices=["simulated", "msi-mystic-hid"], default=None)
    parser.add_argument("--mapper", choices=["grid", "calibrated"], default=None)
    parser.add_argument("--capturer", choices=["windows-mss", "mock"], default=None)
    parser.add_argument("--hid-path", type=str, default=None)
    parser.add_argument("--vendor-id", type=str, default=None)
    parser.add_argument("--product-id", type=str, default=None)
    parser.add_argument("--zone-profile", type=Path, default=None)
    parser.add_argument("--calibration-profile", type=Path, default=None)
    parser.add_argument("--rows", type=int, default=None)
    parser.add_argument("--columns", type=int, default=None)
    parser.add_argument("--fps", type=int, default=None)
    parser.add_argument("--iterations", type=int, default=None)
    parser.add_argument("--watchdog-interval", type=int, default=None)
    parser.add_argument("--event-log-interval", type=int, default=None)
    parser.add_argument(
        "--strict-preflight",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--restore-on-exit",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument("--restore-color", type=str, default=None)
    return parser


def _build_capture_observed_order_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interactively capture observed hardware order and build calibration profile"
    )
    parser.add_argument(
        "--backend",
        choices=["simulated", "msi-mystic-hid"],
        default="simulated",
        help="Driver backend for zone highlighting",
    )
    parser.add_argument("--zone-count", type=int, default=24, help="Number of keyboard zones")
    parser.add_argument(
        "--active-color",
        type=str,
        default="255,0,0",
        help="RGB for active zone, format: R,G,B",
    )
    parser.add_argument(
        "--inactive-color",
        type=str,
        default="0,0,0",
        help="RGB for inactive zones, format: R,G,B",
    )
    parser.add_argument("--hid-path", type=str, default=None, help="HID path for msi-mystic-hid")
    parser.add_argument("--vendor-id", type=str, default=None, help="HID VID")
    parser.add_argument("--product-id", type=str, default=None, help="HID PID")
    parser.add_argument("--report-id", type=int, default=1, help="HID report_id placeholder")
    parser.add_argument(
        "--write-method",
        choices=["output", "feature"],
        default="output",
        help="HID write method",
    )
    parser.add_argument("--pad-length", type=int, default=64, help="HID packet length")
    parser.add_argument(
        "--packet-template",
        type=str,
        default="{report_id} {zone} {r} {g} {b}",
        help="HID packet template",
    )
    parser.add_argument(
        "--profile-output",
        type=Path,
        default=Path("config/calibration/final.json"),
        help="Output path for generated calibration profile",
    )
    parser.add_argument(
        "--observed-output",
        type=Path,
        default=Path("artifacts/observed_order_interactive.txt"),
        help="Output path for observed order text",
    )
    parser.add_argument(
        "--no-preflight",
        action="store_true",
        help="Skip scripts/preflight.ps1 before interactive capture",
    )
    parser.add_argument(
        "--strict-preflight",
        action="store_true",
        help="Fail startup if preflight reports unresolved conflicts",
    )
    parser.add_argument(
        "--aggressive-msi-close",
        action="store_true",
        help="Use aggressive MSI close mode in preflight",
    )
    return parser


def _build_run_production_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run strict production workflow: readiness gate, live runtime, then analysis."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/hardware-generated.toml"),
        help="TOML runtime config file",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/production"),
        help="Directory for production workflow artifacts",
    )
    parser.add_argument(
        "--tag",
        type=str,
        default=None,
        help="Optional run tag used in artifact filenames",
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=None,
        help="Optional live runtime duration in seconds",
    )
    parser.add_argument(
        "--run-readiness",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run readiness gate before live runtime",
    )
    parser.add_argument(
        "--strict-readiness",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable strict readiness policy defaults",
    )
    parser.add_argument(
        "--run-preflight-for-readiness",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run preflight before readiness evaluation",
    )
    parser.add_argument(
        "--preflight-strict-mode",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use strict preflight mode",
    )
    parser.add_argument(
        "--preflight-aggressive-msi-close",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use aggressive MSI close mode in preflight",
    )
    parser.add_argument(
        "--calibration-workflow-report",
        type=Path,
        default=Path("artifacts/calibrate_report_final.json"),
        help="Path to calibration workflow report",
    )
    parser.add_argument(
        "--max-calibration-profile-age-seconds",
        type=int,
        default=None,
        help="Optional max age for calibration profile",
    )
    parser.add_argument(
        "--max-calibration-workflow-age-seconds",
        type=int,
        default=None,
        help="Optional max age for calibration workflow report",
    )
    parser.add_argument(
        "--max-preflight-age-seconds",
        type=int,
        default=900,
        help="Optional max age for preflight report",
    )
    parser.add_argument(
        "--run-live",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run live runtime stage",
    )
    parser.add_argument(
        "--run-live-preflight",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Run preflight again in live command",
    )
    parser.add_argument(
        "--watchdog-interval",
        type=int,
        default=300,
        help="Live watchdog interval iterations (0 disables)",
    )
    parser.add_argument(
        "--event-log-interval",
        type=int,
        default=30,
        help="Live event log interval iterations (0 disables)",
    )
    parser.add_argument(
        "--restore-on-exit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Restore keyboard color after live runtime",
    )
    parser.add_argument(
        "--restore-color",
        type=str,
        default="0,0,0",
        help="Restore RGB color as R,G,B",
    )
    parser.add_argument(
        "--run-analysis",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run live analysis after live runtime",
    )
    parser.add_argument(
        "--max-error-rate-percent",
        type=float,
        default=1.0,
        help="Analysis threshold max error rate percent",
    )
    parser.add_argument(
        "--max-avg-total-ms",
        type=float,
        default=80.0,
        help="Analysis threshold max avg total ms",
    )
    parser.add_argument(
        "--max-p95-total-ms",
        type=float,
        default=120.0,
        help="Analysis threshold max p95 total ms",
    )
    parser.add_argument(
        "--min-effective-fps",
        type=float,
        default=20.0,
        help="Analysis threshold min effective FPS",
    )
    parser.add_argument(
        "--max-overrun-percent",
        type=float,
        default=25.0,
        help="Analysis threshold max overrun percent",
    )
    parser.add_argument(
        "--require-no-abort",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require no abort in analysis",
    )
    parser.add_argument(
        "--min-completed-iterations",
        type=int,
        default=1,
        help="Analysis threshold min completed iterations",
    )
    return parser


def _run_command(argv: list[str]) -> int:
    args = _build_run_parser().parse_args(argv)

    capturer = MockGradientCapturer()
    mapper = GridZoneMapper(layout=GridLayout(rows=args.rows, columns=args.columns))
    driver = SimulatedKeyboardDriver()

    pipeline = KeyLightPipeline(
        capturer=capturer,
        mapper=mapper,
        driver=driver,
        config=PipelineConfig(fps=args.fps, iterations=args.iterations),
    )
    pipeline.run()

    print(f"Completed {args.iterations} iterations at {args.fps} FPS")
    print(f"Zone layout: {args.rows} rows x {args.columns} columns")
    return 0


def _probe_command(argv: list[str]) -> int:
    args = _build_probe_parser().parse_args(argv)
    report = run_probe()
    output_path = write_probe_report(report, args.output)

    print("Probe completed.")
    print(f"Admin context: {report.is_admin}")
    print(f"Candidate services: {len(report.candidate_services)}")
    print(f"Candidate devices: {len(report.candidate_devices)}")
    print("Likely control paths:")
    for path in report.likely_control_paths:
        print(f"- {path}")
    print("Recommendations:")
    for recommendation in report.recommendations:
        print(f"- {recommendation}")
    print(f"Report written to: {output_path.resolve()}")

    if args.print_json:
        print(json.dumps(report.to_dict(), indent=2))

    return 0


def _sweep_command(argv: list[str]) -> int:
    args = _build_sweep_parser().parse_args(argv)
    if not args.no_preflight:
        preflight_exit_code = _run_preflight_with_mode(
            aggressive_msi_close=args.aggressive_msi_close,
            strict_preflight=args.strict_preflight,
        )
        if preflight_exit_code != 0:
            print(f"Preflight failed with exit code {preflight_exit_code}.")
            return preflight_exit_code

    try:
        active_color = _parse_rgb_triplet(args.active_color)
        inactive_color = _parse_rgb_triplet(args.inactive_color)
        vendor_id = _parse_optional_int(args.vendor_id)
        product_id = _parse_optional_int(args.product_id)
        sweep_config = SweepConfig(
            zone_count=args.zone_count,
            loops=args.loops,
            step_delay_ms=args.delay_ms,
            reverse=args.reverse,
            active_color=active_color,
            inactive_color=inactive_color,
        )
        driver = _build_keyboard_driver(
            backend=args.backend,
            zone_count=args.zone_count,
            hid_path=args.hid_path,
            vendor_id=vendor_id,
            product_id=product_id,
            report_id=args.report_id,
            write_method=args.write_method,
            pad_length=args.pad_length,
            packet_template=args.packet_template,
            calibration_profile_path=args.calibration_profile,
        )
    except ValueError as error:
        print(f"Sweep configuration error: {error}")
        return 2

    sweeper = ZoneSweeper(driver)
    try:
        report = sweeper.run(sweep_config)
    except ValueError as error:
        print(f"Sweep execution error: {error}")
        return 2
    output_path = write_sweep_report(report, args.output)

    print("Sweep completed.")
    print(f"Steps executed: {len(report.steps)}")
    print(f"Zone count: {args.zone_count}")
    print(f"Loops: {args.loops}")
    print(f"Report written to: {output_path.resolve()}")
    print(f"Backend: {args.backend}")

    if args.print_json:
        print(json.dumps(report.to_dict(), indent=2))

    return 0


def _write_zone_command(argv: list[str]) -> int:
    args = _build_write_zone_parser().parse_args(argv)

    if args.list_hid:
        return _list_hid_command()

    if not args.no_preflight:
        preflight_exit_code = _run_preflight_with_mode(
            aggressive_msi_close=args.aggressive_msi_close,
            strict_preflight=args.strict_preflight,
        )
        if preflight_exit_code != 0:
            print(f"Preflight failed with exit code {preflight_exit_code}.")
            return preflight_exit_code

    try:
        color = _parse_rgb_triplet(args.color)
        vendor_id = _parse_optional_int(args.vendor_id)
        product_id = _parse_optional_int(args.product_id)
        effective_zone_index = args.zone_index
        if args.calibration_profile is not None:
            profile = load_calibration_profile(args.calibration_profile)
            if profile.zone_count != args.zone_count:
                raise ValueError(
                    f"calibration profile zone_count {profile.zone_count} does not match "
                    f"--zone-count {args.zone_count}"
                )
            if args.zone_index < 0 or args.zone_index >= profile.zone_count:
                raise ValueError(
                    f"zone-index {args.zone_index} is outside profile zone_count "
                    f"{profile.zone_count}"
                )
            effective_zone_index = profile.logical_to_hardware[args.zone_index]

        config = WriteZoneConfig(
            backend=args.backend,
            zone_index=effective_zone_index,
            zone_count=args.zone_count,
            color=color,
            packet_template=args.packet_template,
            report_id=args.report_id,
            pad_to=args.pad_to,
            write_method=args.write_method,
            hid_path=args.hid_path,
            vendor_id=vendor_id,
            product_id=product_id,
        )
        report = execute_write_zone(config)
    except ValueError as error:
        print(f"Write-zone configuration error: {error}")
        return 2
    except (RuntimeError, OSError) as error:
        print(f"Write-zone execution error: {error}")
        return 1

    output_path = write_write_zone_report(report, args.output)
    if report.success:
        print("Write-zone completed.")
        print(f"Backend: {report.backend}")
        if args.calibration_profile is not None:
            print(f"Logical zone index: {args.zone_index}")
            print(f"Hardware zone index: {report.zone_index}")
        else:
            print(f"Zone index: {report.zone_index}")
        print(f"Color: {report.color.r},{report.color.g},{report.color.b}")
        if report.report_bytes is not None:
            print(f"Packet bytes: {' '.join(f'{byte:02X}' for byte in report.report_bytes)}")
            print(f"Bytes written: {report.bytes_written}")
            print(f"Write method: {report.write_method}")
    else:
        print("Write-zone failed.")
        if report.error:
            print(f"Error: {report.error}")
    print(f"Report written to: {output_path.resolve()}")

    if args.print_json:
        print(json.dumps(report.to_dict(), indent=2))

    return 0 if report.success else 1


def _list_hid_command() -> int:
    try:
        devices = list_hid_devices()
    except RuntimeError as error:
        print(f"HID list failed: {error}")
        return 1

    if not devices:
        print("No HID devices returned by hidapi.")
        return 0

    print("HID devices:")
    for index, device in enumerate(devices):
        print(
            f"[{index}] VID=0x{device.vendor_id:04X} PID=0x{device.product_id:04X} "
            f"UsagePage=0x{device.usage_page:04X} Usage=0x{device.usage:04X} "
            f"Product='{device.product_string}' Path='{device.path}'"
        )
    return 0


def _discover_hid_command(argv: list[str]) -> int:
    args = _build_discover_hid_parser().parse_args(argv)
    if not args.no_preflight:
        preflight_exit_code = _run_preflight_with_mode(
            aggressive_msi_close=args.aggressive_msi_close,
            strict_preflight=args.strict_preflight,
        )
        if preflight_exit_code != 0:
            print(f"Preflight failed with exit code {preflight_exit_code}.")
            return preflight_exit_code

    try:
        color = _parse_rgb_triplet(args.color)
        vendor_id = _parse_optional_int(args.vendor_id)
        product_id = _parse_optional_int(args.product_id)
        write_methods = _parse_csv_str_list(args.write_methods)
        report_ids = _parse_csv_int_list(args.report_ids)
        pad_lengths = _parse_csv_int_list(args.pad_lengths)
        templates = _build_discovery_templates(args.templates)

        config = HidDiscoveryConfig(
            hid_path=args.hid_path,
            vendor_id=vendor_id,
            product_id=product_id,
            zone_index=args.zone_index,
            color=color,
            write_methods=write_methods,
            report_ids=report_ids,
            pad_lengths=pad_lengths,
            templates=templates,
            delay_ms=args.delay_ms,
            stop_on_first_success=args.stop_on_first_success,
        )
        report = run_hid_discovery(config)
    except ValueError as error:
        print(f"HID discovery configuration error: {error}")
        return 2

    output_path = write_hid_discovery_report(report, args.output)
    print("HID discovery completed.")
    print(f"Attempts: {report.total_attempts}")
    print(f"Successes: {report.success_count}")
    print(f"Report written to: {output_path.resolve()}")

    if report.success_count > 0:
        print("Successful attempts:")
        success_attempts = [attempt for attempt in report.attempts if attempt.success]
        for attempt in success_attempts[:10]:
            print(
                f"- idx={attempt.index} template={attempt.template_name} "
                f"method={attempt.write_method} "
                f"report_id={attempt.report_id} pad={attempt.pad_length} "
                f"bytes_written={attempt.bytes_written}"
            )

    if args.print_json:
        print(json.dumps(report.to_dict(), indent=2))

    return 0 if report.success_count > 0 else 1


def _discover_effects_command(argv: list[str]) -> int:
    args = _build_discover_effects_parser().parse_args(argv)
    if not args.no_preflight:
        preflight_exit_code = _run_preflight_with_mode(
            aggressive_msi_close=args.aggressive_msi_close,
            strict_preflight=args.strict_preflight,
        )
        if preflight_exit_code != 0:
            print(f"Preflight failed with exit code {preflight_exit_code}.")
            return preflight_exit_code

    try:
        vendor_id = _parse_optional_int(args.vendor_id)
        product_id = _parse_optional_int(args.product_id)
        zone_sequence = _parse_csv_int_list(args.zone_sequence)
        if any(zone < 0 for zone in zone_sequence):
            raise ValueError("zone-sequence values must be non-negative.")
        config = EffectVerificationConfig(
            hid_path=args.hid_path,
            vendor_id=vendor_id,
            product_id=product_id,
            zone_sequence=zone_sequence,
            color_sequence=default_color_sequence(),
            candidates=default_accepted_candidates(pad_length=args.pad_length),
            step_delay_ms=args.step_delay_ms,
            repeat=args.repeat,
            max_steps=args.max_steps,
        )
    except ValueError as error:
        print(f"Effect verification configuration error: {error}")
        return 2

    print("Effect verification starting. Watch keyboard and note step indexes with visible change.")

    def on_step(step: EffectVerificationStep) -> None:
        marker = "OK" if step.success else "FAIL"
        print(
            f"[{marker}] step={step.step_index} candidate={step.candidate_name} "
            f"method={step.write_method} rid={step.report_id} zone={step.zone_index} "
            f"color={step.color.r},{step.color.g},{step.color.b}"
        )

    report = run_effect_verification(config, on_step=on_step)
    output_path = write_effect_verification_report(report, args.output)

    print("Effect verification completed.")
    print(f"Total steps: {report.total_steps}")
    print(f"Successful writes: {report.success_count}")
    print(f"Report written to: {output_path.resolve()}")

    if args.print_json:
        print(json.dumps(report.to_dict(), indent=2))

    return 0 if report.success_count > 0 else 1


def _discover_zone_protocol_command(argv: list[str]) -> int:
    args = _build_discover_zone_protocol_parser().parse_args(argv)
    if not args.no_preflight:
        preflight_exit_code = _run_preflight_with_mode(
            aggressive_msi_close=args.aggressive_msi_close,
            strict_preflight=args.strict_preflight,
        )
        if preflight_exit_code != 0:
            print(f"Preflight failed with exit code {preflight_exit_code}.")
            return preflight_exit_code

    try:
        vendor_id = _parse_optional_int(args.vendor_id)
        product_id = _parse_optional_int(args.product_id)
        zone_sequence = _parse_csv_int_list(args.zone_sequence)
        if any(zone < 0 for zone in zone_sequence):
            raise ValueError("zone-sequence values must be non-negative.")
        if args.default_offsets:
            offsets = default_zone_probe_offsets()
        else:
            offsets = _parse_csv_int_list(args.offsets)
        config = ZoneProtocolVerifyConfig(
            hid_path=args.hid_path,
            vendor_id=vendor_id,
            product_id=product_id,
            zone_sequence=zone_sequence,
            color_sequence=default_color_sequence(),
            offsets=offsets,
            step_delay_ms=args.step_delay_ms,
            repeat=args.repeat,
            max_steps=args.max_steps,
            pad_length=args.pad_length,
            brightness=args.brightness,
            transition=args.transition,
            profile_slot=args.profile_slot,
            effect_code=args.effect_code,
        )
    except ValueError as error:
        print(f"Zone protocol verification configuration error: {error}")
        return 2

    print("Zone protocol verification starting.")
    print(
        "Watch keyboard and note step indexes where injected offset changes behavior "
        "(especially zone-localized effects)."
    )

    def on_step(step: ZoneProtocolVerifyStep) -> None:
        marker = "OK" if step.success else "FAIL"
        print(
            f"[{marker}] step={step.step_index} offset={step.offset} zone={step.zone_index} "
            f"orig={step.original_value} new={step.injected_value} "
            f"color={step.color.r},{step.color.g},{step.color.b}"
        )

    report = run_zone_protocol_verify(config, on_step=on_step)
    output_path = write_zone_protocol_verify_report(report, args.output)

    print("Zone protocol verification completed.")
    print(f"Total steps: {report.total_steps}")
    print(f"Successful writes: {report.success_count}")
    print(f"Report written to: {output_path.resolve()}")

    if args.print_json:
        print(json.dumps(report.to_dict(), indent=2))

    return 0 if report.success_count > 0 else 1


def _init_calibration_command(argv: list[str]) -> int:
    args = _build_init_calibration_parser().parse_args(argv)
    try:
        profile = identity_profile(args.zone_count, source_method="init-calibration")
        output_path = write_calibration_profile(profile, args.output)
    except ValueError as error:
        print(f"Calibration initialization error: {error}")
        return 2

    print("Calibration profile initialized.")
    print(f"Zone count: {profile.zone_count}")
    print(f"Output: {output_path.resolve()}")
    return 0


def _build_calibration_command(argv: list[str]) -> int:
    args = _build_build_calibration_parser().parse_args(argv)
    try:
        observed_order_text = _resolve_observed_order_text(args.order, args.order_file)
        observed_order = _parse_int_sequence(observed_order_text)
        profile = profile_from_observed_order(
            observed_order,
            args.zone_count,
            source_method="build-calibration",
        )
        output_path = write_calibration_profile(profile, args.output)
    except ValueError as error:
        print(f"Build calibration error: {error}")
        return 2

    print("Calibration profile built from observed order.")
    print(f"Zone count: {profile.zone_count}")
    print(f"Output: {output_path.resolve()}")
    return 0


def _calibrate_zones_command(argv: list[str]) -> int:
    args = _build_calibrate_zones_parser().parse_args(argv)

    started_at_utc = now_utc_iso()
    finished_at_utc = started_at_utc
    steps_executed = 0
    sweep_report_path: str | None = None
    template_output_path: str | None = None
    profile_output_path: str | None = None
    observed_order: list[int] | None = None
    profile_built = False
    verify_requested = args.verify
    verify_executed = False
    verify_steps_executed = 0
    verify_report_path: str | None = None
    live_verify_requested = args.verify_live
    live_verify_executed = False
    live_verify_report_path: str | None = None
    live_verify_error: str | None = None
    profile_path_obj: Path | None = None
    final_exit_code = 0

    should_run_hardware_step = (not args.no_sweep) or args.verify or args.verify_live
    if should_run_hardware_step and not args.no_preflight:
        preflight_exit_code = _run_preflight_with_mode(
            aggressive_msi_close=args.aggressive_msi_close,
            strict_preflight=args.strict_preflight,
        )
        if preflight_exit_code != 0:
            print(f"Preflight failed with exit code {preflight_exit_code}.")
            return preflight_exit_code

    try:
        active_color = _parse_rgb_triplet(args.active_color)
        inactive_color = _parse_rgb_triplet(args.inactive_color)
        vendor_id = _parse_optional_int(args.vendor_id)
        product_id = _parse_optional_int(args.product_id)
    except ValueError as error:
        print(f"Calibrate-zones configuration error: {error}")
        return 2

    if not args.no_sweep:
        try:
            sweep_config = SweepConfig(
                zone_count=args.zone_count,
                loops=args.loops,
                step_delay_ms=args.delay_ms,
                reverse=args.reverse,
                active_color=active_color,
                inactive_color=inactive_color,
            )
            driver = _build_keyboard_driver(
                backend=args.backend,
                zone_count=args.zone_count,
                hid_path=args.hid_path,
                vendor_id=vendor_id,
                product_id=product_id,
                report_id=args.report_id,
                write_method=args.write_method,
                pad_length=args.pad_length,
                packet_template=args.packet_template,
                calibration_profile_path=None,
            )
            sweep_report = ZoneSweeper(driver).run(sweep_config)
        except ValueError as error:
            print(f"Calibrate-zones execution error: {error}")
            return 2

        sweep_output_path = write_sweep_report(sweep_report, args.sweep_output)
        steps_executed = len(sweep_report.steps)
        sweep_report_path = str(sweep_output_path.resolve())
        print("Calibration sweep completed.")
        print(f"Steps executed: {steps_executed}")
        print(f"Sweep report: {sweep_report_path}")

    try:
        observed_order = _parse_optional_observed_order(
            order=args.observed_order,
            order_file=args.observed_order_file,
        )
    except ValueError as error:
        print(f"Calibrate-zones observed-order error: {error}")
        return 2

    if observed_order is None:
        if (args.verify or args.verify_live) and args.profile_output.exists():
            try:
                existing_profile = load_calibration_profile(args.profile_output)
            except ValueError as error:
                print(f"Calibrate-zones profile error: {error}")
                return 2
            if existing_profile.zone_count != args.zone_count:
                print(
                    "Calibrate-zones profile error: existing profile zone_count "
                    f"{existing_profile.zone_count} does not match --zone-count {args.zone_count}"
                )
                return 2
            profile_path_obj = args.profile_output
            profile_output_path = str(args.profile_output.resolve())
            print("Using existing calibration profile.")
            print(f"Profile output: {profile_output_path}")
        else:
            template_path = write_observed_order_template(args.zone_count, args.template_output)
            template_output_path = str(template_path.resolve())
            print("Observed order not provided.")
            print(f"Template written to: {template_output_path}")
            print(
                "Fill observed_order in the template, then rerun calibrate-zones with "
                "--observed-order-file or --observed-order."
            )
    else:
        try:
            profile = profile_from_observed_order(
                observed_order,
                args.zone_count,
                source_method="calibrate-zones",
                workflow_report_path=args.output.resolve(),
            )
            profile_path = write_calibration_profile(profile, args.profile_output)
        except ValueError as error:
            print(f"Calibrate-zones profile error: {error}")
            return 2
        profile_path_obj = profile_path
        profile_output_path = str(profile_path.resolve())
        profile_built = True
        print("Calibration profile generated.")
        print(f"Profile output: {profile_output_path}")

    if args.verify:
        if profile_path_obj is None:
            print(
                "Verification skipped: no calibration profile available. "
                "Provide observed order or existing --profile-output."
            )
        else:
            try:
                verify_delay_ms = (
                    args.delay_ms if args.verify_delay_ms is None else args.verify_delay_ms
                )
                verify_config = SweepConfig(
                    zone_count=args.zone_count,
                    loops=args.verify_loops,
                    step_delay_ms=verify_delay_ms,
                    reverse=args.verify_reverse,
                    active_color=active_color,
                    inactive_color=inactive_color,
                )
                verify_driver = _build_keyboard_driver(
                    backend=args.backend,
                    zone_count=args.zone_count,
                    hid_path=args.hid_path,
                    vendor_id=vendor_id,
                    product_id=product_id,
                    report_id=args.report_id,
                    write_method=args.write_method,
                    pad_length=args.pad_length,
                    packet_template=args.packet_template,
                    calibration_profile_path=profile_path_obj,
                )
                verify_report = ZoneSweeper(verify_driver).run(verify_config)
            except ValueError as error:
                print(f"Calibrate-zones verification error: {error}")
                return 2

            verify_output_path = write_sweep_report(verify_report, args.verify_output)
            verify_executed = True
            verify_steps_executed = len(verify_report.steps)
            verify_report_path = str(verify_output_path.resolve())
            print("Verification sweep completed.")
            print(f"Verification steps executed: {verify_steps_executed}")
            print(f"Verification report: {verify_report_path}")

    if args.verify_live:
        if profile_path_obj is None:
            print(
                "Live verification skipped: no calibration profile available. "
                "Provide observed order or existing --profile-output."
            )
            live_verify_error = "no calibration profile available"
        else:
            try:
                capturer = _build_capturer(
                    capturer_name=args.live_capturer,
                    monitor_index=args.live_monitor_index,
                    capture_width=args.live_capture_width,
                    capture_height=args.live_capture_height,
                )
                mapper = _build_mapper(
                    mapper_name=args.live_mapper,
                    rows=args.live_rows,
                    columns=args.live_columns,
                    zone_profile_path=args.live_zone_profile,
                )
                mapper_zone_count = _mapper_zone_count(mapper)
                if mapper_zone_count != args.zone_count:
                    raise ValueError(
                        f"live mapper zone_count {mapper_zone_count} must match "
                        f"--zone-count {args.zone_count}"
                    )
                driver = _build_keyboard_driver(
                    backend=args.backend,
                    zone_count=args.zone_count,
                    hid_path=args.hid_path,
                    vendor_id=vendor_id,
                    product_id=product_id,
                    report_id=args.report_id,
                    write_method=args.write_method,
                    pad_length=args.pad_length,
                    packet_template=args.packet_template,
                    calibration_profile_path=profile_path_obj,
                )
                processor = ZoneColorProcessor(
                    config=ColorProcessingConfig(
                        smoothing_enabled=False,
                        smoothing_alpha=0.25,
                        brightness_max_percent=100,
                    )
                )
                live_runtime = LiveRuntime(
                    capturer=capturer,
                    mapper=mapper,
                    processor=processor,
                    driver=driver,
                    config=LiveRuntimeConfig(
                        fps=args.live_fps,
                        iterations=args.live_iterations,
                        max_consecutive_errors=3,
                        error_backoff_ms=250,
                        stop_on_error=False,
                    ),
                )
            except (ValueError, RuntimeError) as error:
                print(f"Calibrate-zones live verification error: {error}")
                return 2

            try:
                live_report = live_runtime.run()
            except Exception as error:
                print(f"Calibrate-zones live verification failed: {error}")
                return 1

            live_verify_output = write_live_runtime_report(live_report, args.live_output)
            live_verify_executed = True
            live_verify_report_path = str(live_verify_output.resolve())
            if live_report.aborted:
                live_verify_error = "live runtime aborted due to consecutive errors"
                final_exit_code = 1
            print("Live verification runtime completed.")
            print(f"Live verification report: {live_verify_report_path}")

    finished_at_utc = now_utc_iso()
    workflow_report = CalibrateZonesReport(
        started_at_utc=started_at_utc,
        finished_at_utc=finished_at_utc,
        zone_count=args.zone_count,
        steps_executed=steps_executed,
        sweep_report_path=sweep_report_path,
        template_output_path=template_output_path,
        profile_output_path=profile_output_path,
        observed_order=observed_order,
        profile_built=profile_built,
        verify_requested=verify_requested,
        verify_executed=verify_executed,
        verify_steps_executed=verify_steps_executed,
        verify_report_path=verify_report_path,
        live_verify_requested=live_verify_requested,
        live_verify_executed=live_verify_executed,
        live_verify_report_path=live_verify_report_path,
        live_verify_error=live_verify_error,
    )
    workflow_output_path = write_calibrate_zones_report(workflow_report, args.output)
    print(f"Calibration workflow report: {workflow_output_path.resolve()}")

    if args.print_json:
        print(json.dumps(workflow_report.to_dict(), indent=2))

    return final_exit_code


def _build_zone_profile_command(argv: list[str]) -> int:
    args = _build_build_zone_profile_parser().parse_args(argv)
    try:
        row_weights = _parse_csv_float_list(args.row_weights) if args.row_weights else None
        column_weights = _parse_csv_float_list(args.column_weights) if args.column_weights else None
        row_column_weights = (
            _parse_row_column_weights(args.row_column_weights)
            if args.row_column_weights
            else None
        )
        config = ZoneProfileBuildConfig(
            rows=args.rows,
            columns=args.columns,
            row_weights=row_weights,
            column_weights=column_weights,
            row_column_weights=row_column_weights,
            x_start=args.x_start,
            x_end=args.x_end,
            y_start=args.y_start,
            y_end=args.y_end,
            row_direction=args.row_direction,
            column_direction=args.column_direction,
            serpentine=args.serpentine,
        )
        profile = build_zone_geometry_profile(config)
        output_path = write_zone_geometry_profile(profile, args.output)
    except ValueError as error:
        print(f"Build zone profile error: {error}")
        return 2

    print("Zone geometry profile built.")
    print(f"Rows: {args.rows}")
    print(f"Columns: {args.columns}")
    print(f"Zone count: {profile.zone_count}")
    print(f"Output: {output_path.resolve()}")
    return 0


def _live_command(argv: list[str]) -> int:
    try:
        parser_defaults = _resolve_live_defaults(argv)
        args = _build_live_parser(parser_defaults).parse_args(argv)
    except ValueError as error:
        print(f"Live runtime configuration error: {error}")
        return 2

    if not args.no_preflight:
        preflight_exit_code = _run_preflight_with_mode(
            aggressive_msi_close=args.aggressive_msi_close,
            strict_preflight=args.strict_preflight,
        )
        if preflight_exit_code != 0:
            print(f"Preflight failed with exit code {preflight_exit_code}.")
            return preflight_exit_code

    try:
        vendor_id = _parse_optional_int(args.vendor_id)
        product_id = _parse_optional_int(args.product_id)
        runtime_iterations = args.iterations
        restore_color = None
        if args.duration_seconds is not None:
            if args.duration_seconds <= 0:
                raise ValueError("duration-seconds must be positive.")
            runtime_iterations = max(1, math.ceil(args.duration_seconds * args.fps))
        if args.restore_on_exit:
            restore_color = _parse_rgb_triplet(args.restore_color)

        watchdog_callback = None
        if args.watchdog_interval > 0:
            watchdog_output = args.watchdog_output

            def watchdog_callback(snapshot: LiveWatchdogSnapshot) -> None:
                write_live_watchdog_snapshot(snapshot, watchdog_output)

        event_log_callback = None
        if args.event_log_interval > 0:
            event_log_output = args.event_log_output

            def event_log_callback(entry: LiveEventLogEntry) -> None:
                write_live_event_log_entry(entry, event_log_output)

        capturer = _build_capturer(
            capturer_name=args.capturer,
            monitor_index=args.monitor_index,
            capture_width=args.capture_width,
            capture_height=args.capture_height,
        )
        mapper = _build_mapper(
            mapper_name=args.mapper,
            rows=args.rows,
            columns=args.columns,
            zone_profile_path=args.zone_profile,
        )
        driver = _build_keyboard_driver(
            backend=args.backend,
            zone_count=_mapper_zone_count(mapper),
            hid_path=args.hid_path,
            vendor_id=vendor_id,
            product_id=product_id,
            report_id=args.report_id,
            write_method=args.write_method,
            pad_length=args.pad_length,
            packet_template=args.packet_template,
            calibration_profile_path=args.calibration_profile,
        )
        processor = ZoneColorProcessor(
            config=ColorProcessingConfig(
                smoothing_enabled=args.smoothing_enabled,
                smoothing_alpha=args.smoothing_alpha,
                brightness_max_percent=args.brightness_max_percent,
            )
        )
        runtime = LiveRuntime(
            capturer=capturer,
            mapper=mapper,
            processor=processor,
            driver=driver,
            config=LiveRuntimeConfig(
                fps=args.fps,
                iterations=runtime_iterations,
                max_consecutive_errors=args.max_consecutive_errors,
                error_backoff_ms=args.error_backoff_ms,
                stop_on_error=args.stop_on_error,
                reconnect_on_error=args.reconnect_on_error,
                reconnect_attempts=args.reconnect_attempts,
                watchdog_interval_iterations=args.watchdog_interval,
                event_log_interval_iterations=args.event_log_interval,
            ),
            watchdog_callback=watchdog_callback,
            event_log_callback=event_log_callback,
        )
    except (ValueError, RuntimeError) as error:
        print(f"Live runtime configuration error: {error}")
        return 2

    runtime_error: Exception | None = None
    report = None
    try:
        report = runtime.run()
    except Exception as error:
        runtime_error = error

    restore_applied = False
    restore_error: str | None = None
    if args.restore_on_exit:
        try:
            assert restore_color is not None
            restore_zone_count = _mapper_zone_count(mapper)
            restore_payload = [
                ZoneColor(zone_index=index, color=restore_color)
                for index in range(restore_zone_count)
            ]
            driver.apply_zone_colors(restore_payload)
            restore_applied = True
        except Exception as error:
            restore_error = str(error)

    if runtime_error is not None:
        print(f"Live runtime failed: {runtime_error}")
        if args.restore_on_exit:
            print(f"Restore-on-exit: applied={restore_applied}")
            if restore_error is not None:
                print(f"Restore-on-exit error: {restore_error}")
        return 1

    assert report is not None
    report = replace(
        report,
        restore_requested=args.restore_on_exit,
        restore_applied=restore_applied,
        restore_error=restore_error,
    )

    output_path = write_live_runtime_report(report, args.output)
    print("Live runtime completed.")
    if args.duration_seconds is not None:
        print(
            f"Duration mode: seconds={args.duration_seconds} "
            f"computed_iterations={report.iterations}"
        )
    print(
        f"Iterations: target={report.iterations} "
        f"attempted={report.attempted_iterations} completed={report.completed_iterations}"
    )
    print(f"Errors: total={report.error_count} max_consecutive={report.max_consecutive_errors}")
    if report.last_error is not None:
        print(f"Last error: {report.last_error}")
    if report.aborted:
        print("Runtime aborted after reaching max consecutive errors.")
    print(
        "Recovery: "
        f"attempts={report.recovery_attempts} successes={report.recovery_successes}"
    )
    print(f"avg_capture_ms={report.avg_capture_ms:.2f}")
    print(f"avg_map_ms={report.avg_map_ms:.2f}")
    print(f"avg_process_ms={report.avg_process_ms:.2f}")
    print(f"avg_send_ms={report.avg_send_ms:.2f}")
    print(f"avg_total_ms={report.avg_total_ms:.2f}")
    print(f"effective_fps={report.effective_fps:.2f}")
    print(f"overrun_iterations={report.overrun_iterations}")
    print(f"avg_overrun_ms={report.avg_overrun_ms:.2f}")
    print(f"watchdog_emits={report.watchdog_emits}")
    print(f"event_log_emits={report.event_log_emits}")
    if args.watchdog_interval > 0:
        print(f"Watchdog snapshot: {args.watchdog_output.resolve()}")
    if args.event_log_interval > 0:
        print(f"Event log: {args.event_log_output.resolve()}")
    if args.restore_on_exit:
        print(f"Restore-on-exit: applied={report.restore_applied}")
        if report.restore_error is not None:
            print(f"Restore-on-exit error: {report.restore_error}")
    print(f"Report written to: {output_path.resolve()}")

    if args.print_json:
        print(json.dumps(report.to_dict(), indent=2))

    return 1 if report.aborted or report.restore_error is not None else 0


def _list_monitors_command(argv: list[str]) -> int:
    _build_list_monitors_parser().parse_args(argv)
    try:
        monitors = list_monitors()
    except RuntimeError as error:
        print(f"List monitors failed: {error}")
        return 1

    if len(monitors) <= 1:
        print("No individual monitors detected.")
        return 0

    print("Monitors:")
    for monitor in monitors[1:]:
        print(
            f"- index={monitor.index} size={monitor.width}x{monitor.height} "
            f"pos=({monitor.left},{monitor.top})"
        )
    return 0


def _analyze_live_command(argv: list[str]) -> int:
    args = _build_analyze_live_parser().parse_args(argv)
    try:
        thresholds = LiveQualityThresholds(
            max_error_rate_percent=args.max_error_rate_percent,
            max_avg_total_ms=args.max_avg_total_ms,
            max_p95_total_ms=args.max_p95_total_ms,
            min_effective_fps=args.min_effective_fps,
            max_overrun_percent=args.max_overrun_percent,
            require_no_abort=args.require_no_abort,
            min_completed_iterations=args.min_completed_iterations,
        )
        analysis = analyze_live_run(
            report_path=args.report,
            event_log_path=args.event_log,
            thresholds=thresholds,
        )
        output_path = write_live_analysis_report(analysis, args.output)
    except ValueError as error:
        print(f"Analyze-live error: {error}")
        return 2

    print("Live analysis completed.")
    print(
        f"passed={analysis.passed} "
        f"attempted={analysis.attempted_iterations} "
        f"completed={analysis.completed_iterations} "
        f"errors={analysis.error_count}"
    )
    print(f"error_rate_percent={analysis.error_rate_percent:.3f}")
    print(f"avg_total_ms={analysis.avg_total_ms:.3f}")
    print(f"effective_fps={analysis.effective_fps:.3f}")
    print(f"overrun_iterations={analysis.overrun_iterations}")
    print(f"overrun_percent={analysis.overrun_percent:.3f}")
    if analysis.p95_total_ms is not None:
        print(f"p95_total_ms={analysis.p95_total_ms:.3f}")
    else:
        print("p95_total_ms=skipped (no event samples)")
    if analysis.failed_checks:
        print("Failed checks:")
        for check in analysis.failed_checks:
            print(f"- {check}")
    print(f"Report written to: {output_path.resolve()}")

    if args.print_json:
        print(json.dumps(analysis.to_dict(), indent=2))

    return 0 if analysis.passed else 1


def _readiness_check_command(argv: list[str]) -> int:
    args = _build_readiness_check_parser().parse_args(argv)
    if args.run_preflight:
        preflight_exit_code = _run_preflight_with_mode(
            aggressive_msi_close=args.preflight_aggressive_msi_close,
            strict_preflight=args.preflight_strict_mode,
            report_path=args.preflight_report,
        )
        if preflight_exit_code != 0:
            print(
                "Preflight for readiness-check "
                f"exited with code {preflight_exit_code}; proceeding with report evaluation."
            )

    try:
        report = run_readiness_check(
            ReadinessCheckConfig(
                config_path=args.config,
                require_hardware_backend=args.require_hardware_backend,
                require_calibrated_mapper=args.require_calibrated_mapper,
                require_calibration_profile=args.require_calibration_profile,
                require_calibration_profile_generated_timestamp=(
                    args.require_calibration_profile_generated_timestamp
                ),
                require_calibration_profile_provenance=(
                    args.require_calibration_profile_provenance
                ),
                require_calibration_profile_provenance_workflow_match=(
                    args.require_calibration_profile_provenance_workflow_match
                ),
                max_calibration_profile_age_seconds=args.max_calibration_profile_age_seconds,
                forbid_identity_calibration=args.forbid_identity_calibration,
                require_calibration_workflow=args.require_calibration_workflow,
                calibration_workflow_report_path=args.calibration_workflow_report,
                max_calibration_workflow_age_seconds=(
                    args.max_calibration_workflow_age_seconds
                ),
                require_calibration_verify_executed=(
                    args.require_calibration_verify_executed
                ),
                require_calibration_live_verify_executed=(
                    args.require_calibration_live_verify_executed
                ),
                require_calibration_live_verify_success=(
                    args.require_calibration_live_verify_success
                ),
                require_preflight_clean=args.require_preflight_clean,
                require_preflight_admin=args.require_preflight_admin,
                require_preflight_strict_mode=args.require_preflight_strict_mode,
                require_preflight_access_denied_clear=(
                    args.require_preflight_access_denied_clear
                ),
                preflight_report_path=args.preflight_report,
                max_preflight_age_seconds=args.max_preflight_age_seconds,
                require_live_analysis_pass=args.require_live_analysis_pass,
                live_analysis_report_path=args.live_analysis_report,
                max_live_analysis_age_seconds=args.max_live_analysis_age_seconds,
                max_live_analysis_threshold_max_error_rate_percent=(
                    args.max_live_analysis_threshold_max_error_rate_percent
                ),
                max_live_analysis_threshold_max_avg_total_ms=(
                    args.max_live_analysis_threshold_max_avg_total_ms
                ),
                max_live_analysis_threshold_max_p95_total_ms=(
                    args.max_live_analysis_threshold_max_p95_total_ms
                ),
                min_live_analysis_threshold_min_effective_fps=(
                    args.min_live_analysis_threshold_min_effective_fps
                ),
                max_live_analysis_threshold_max_overrun_percent=(
                    args.max_live_analysis_threshold_max_overrun_percent
                ),
                require_hid_present=args.require_hid_present,
                hid_path_override=args.hid_path,
            )
        )
        output_path = write_readiness_report(report, args.output)
    except ValueError as error:
        print(f"Readiness-check error: {error}")
        return 2

    print("Readiness check completed.")
    print(f"passed={report.passed} backend={report.backend} mapper={report.mapper}")
    print(f"zone_count={report.zone_count}")
    if report.failed_checks:
        print("Failed checks:")
        for check in report.failed_checks:
            print(f"- {check}")
    print(f"Report written to: {output_path.resolve()}")

    if args.print_json:
        print(json.dumps(report.to_dict(), indent=2))

    return 0 if report.passed else 1


def _runtime_config_command(argv: list[str]) -> int:
    args = _build_runtime_config_parser().parse_args(argv)
    try:
        defaults = load_live_command_defaults(args.base, must_exist=True)

        if args.set_hardware_mode:
            defaults = replace(
                defaults,
                backend="msi-mystic-hid",
                mapper="calibrated",
                capturer="windows-mss",
                strict_preflight=True,
                write_method="feature",
                pad_length=64,
            )
        if args.set_longrun_mode:
            defaults = replace(
                defaults,
                strict_preflight=True,
                watchdog_interval_iterations=300,
                watchdog_output=Path("artifacts/live_watchdog.json"),
                event_log_interval_iterations=30,
                event_log_output=Path("artifacts/live_events.jsonl"),
                restore_on_exit=True,
                restore_color="0,0,0",
            )

        if args.backend is not None:
            defaults = replace(defaults, backend=args.backend)
        if args.mapper is not None:
            defaults = replace(defaults, mapper=args.mapper)
        if args.capturer is not None:
            defaults = replace(defaults, capturer=args.capturer)
        if args.hid_path is not None:
            defaults = replace(defaults, hid_path=args.hid_path.strip() or None)
        if args.vendor_id is not None:
            defaults = replace(defaults, vendor_id=args.vendor_id.strip() or None)
        if args.product_id is not None:
            defaults = replace(defaults, product_id=args.product_id.strip() or None)
        if args.zone_profile is not None:
            defaults = replace(defaults, zone_profile=args.zone_profile.resolve())
        if args.calibration_profile is not None:
            defaults = replace(defaults, calibration_profile=args.calibration_profile.resolve())
        if args.rows is not None:
            defaults = replace(defaults, rows=args.rows)
        if args.columns is not None:
            defaults = replace(defaults, columns=args.columns)
        if args.fps is not None:
            defaults = replace(defaults, fps=args.fps)
        if args.iterations is not None:
            defaults = replace(defaults, iterations=args.iterations)
        if args.watchdog_interval is not None:
            defaults = replace(defaults, watchdog_interval_iterations=args.watchdog_interval)
        if args.event_log_interval is not None:
            defaults = replace(defaults, event_log_interval_iterations=args.event_log_interval)
        if args.strict_preflight is not None:
            defaults = replace(defaults, strict_preflight=args.strict_preflight)
        if args.restore_on_exit is not None:
            defaults = replace(defaults, restore_on_exit=args.restore_on_exit)
        if args.restore_color is not None:
            defaults = replace(defaults, restore_color=args.restore_color)

        output_path = write_live_defaults_toml(defaults, args.output)
        validated = load_live_command_defaults(output_path, must_exist=True)
    except ValueError as error:
        print(f"Build-runtime-config error: {error}")
        return 2

    print("Runtime config built.")
    print(f"Output: {output_path.resolve()}")
    print(
        f"backend={validated.backend} mapper={validated.mapper} "
        f"capturer={validated.capturer} strict_preflight={validated.strict_preflight}"
    )
    return 0


def _run_production_command(argv: list[str]) -> int:
    args = _build_run_production_parser().parse_args(argv)

    if not args.config.exists():
        print(f"Run-production configuration error: config not found: {args.config}")
        return 2
    if args.duration_seconds is not None and args.duration_seconds <= 0:
        print("Run-production configuration error: --duration-seconds must be positive.")
        return 2
    if args.watchdog_interval < 0:
        print("Run-production configuration error: --watchdog-interval must be >= 0.")
        return 2
    if args.event_log_interval < 0:
        print("Run-production configuration error: --event-log-interval must be >= 0.")
        return 2

    run_tag = args.tag.strip() if args.tag is not None else ""
    if run_tag == "":
        run_tag = _utc_now_tag()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    readiness_output = output_dir / f"readiness_{run_tag}.json"
    live_output = output_dir / f"live_{run_tag}.json"
    watchdog_output = output_dir / f"live_watchdog_{run_tag}.json"
    event_log_output = output_dir / f"live_events_{run_tag}.jsonl"
    analysis_output = output_dir / f"live_analysis_{run_tag}.json"

    print("Production workflow started.")
    print(f"tag={run_tag}")
    print(f"config={args.config.resolve()}")
    print(f"output_dir={output_dir}")

    if args.run_readiness:
        readiness_args = [
            "--config",
            str(args.config),
            "--calibration-workflow-report",
            str(args.calibration_workflow_report),
            "--output",
            str(readiness_output),
        ]
        if args.strict_readiness:
            readiness_args.extend(
                [
                    "--require-hardware-backend",
                    "--require-calibrated-mapper",
                    "--require-calibration-profile",
                    "--require-calibration-profile-generated-timestamp",
                    "--require-calibration-profile-provenance",
                    "--require-calibration-profile-provenance-workflow-match",
                    "--forbid-identity-calibration",
                    "--require-calibration-workflow",
                    "--require-calibration-verify-executed",
                    "--require-calibration-live-verify-executed",
                    "--require-calibration-live-verify-success",
                    "--require-preflight-clean",
                    "--require-preflight-admin",
                    "--require-preflight-strict-mode",
                    "--require-preflight-access-denied-clear",
                ]
            )
        if args.run_preflight_for_readiness:
            readiness_args.append("--run-preflight")
            if args.preflight_strict_mode:
                readiness_args.append("--preflight-strict-mode")
            else:
                readiness_args.append("--no-preflight-strict-mode")
            if args.preflight_aggressive_msi_close:
                readiness_args.append("--preflight-aggressive-msi-close")
            else:
                readiness_args.append("--no-preflight-aggressive-msi-close")
        if args.max_preflight_age_seconds is not None:
            readiness_args.extend(
                ["--max-preflight-age-seconds", str(args.max_preflight_age_seconds)]
            )
        if args.max_calibration_profile_age_seconds is not None:
            readiness_args.extend(
                [
                    "--max-calibration-profile-age-seconds",
                    str(args.max_calibration_profile_age_seconds),
                ]
            )
        if args.max_calibration_workflow_age_seconds is not None:
            readiness_args.extend(
                [
                    "--max-calibration-workflow-age-seconds",
                    str(args.max_calibration_workflow_age_seconds),
                ]
            )
        readiness_exit = _readiness_check_command(readiness_args)
        if readiness_exit != 0:
            print("Production workflow stopped: readiness gate failed.")
            return readiness_exit
        print(f"Readiness report: {readiness_output}")
    else:
        print("Readiness stage skipped.")

    if args.run_live:
        live_args = [
            "--config",
            str(args.config),
            "--watchdog-interval",
            str(args.watchdog_interval),
            "--watchdog-output",
            str(watchdog_output),
            "--event-log-interval",
            str(args.event_log_interval),
            "--event-log-output",
            str(event_log_output),
            "--output",
            str(live_output),
        ]
        if args.duration_seconds is not None:
            live_args.extend(["--duration-seconds", str(args.duration_seconds)])
        if args.restore_on_exit:
            live_args.extend(["--restore-on-exit", "--restore-color", args.restore_color])
        else:
            live_args.append("--no-restore-on-exit")
        if args.run_live_preflight:
            if args.preflight_strict_mode:
                live_args.append("--strict-preflight")
            else:
                live_args.append("--no-strict-preflight")
            if args.preflight_aggressive_msi_close:
                live_args.append("--aggressive-msi-close")
        else:
            live_args.append("--no-preflight")

        live_exit = _live_command(live_args)
        if live_exit != 0:
            print("Production workflow stopped: live runtime failed.")
            return live_exit
        print(f"Live report: {live_output}")
    else:
        print("Live stage skipped.")

    if args.run_analysis and args.run_live:
        analyze_args = [
            "--report",
            str(live_output),
            "--output",
            str(analysis_output),
            "--max-error-rate-percent",
            str(args.max_error_rate_percent),
            "--max-avg-total-ms",
            str(args.max_avg_total_ms),
            "--max-p95-total-ms",
            str(args.max_p95_total_ms),
            "--min-effective-fps",
            str(args.min_effective_fps),
            "--max-overrun-percent",
            str(args.max_overrun_percent),
            "--min-completed-iterations",
            str(args.min_completed_iterations),
        ]
        if args.event_log_interval > 0:
            analyze_args.extend(["--event-log", str(event_log_output)])
        if args.require_no_abort:
            analyze_args.append("--require-no-abort")
        else:
            analyze_args.append("--no-require-no-abort")

        analyze_exit = _analyze_live_command(analyze_args)
        if analyze_exit != 0:
            print("Production workflow finished with failed analysis gate.")
            return analyze_exit
        print(f"Analysis report: {analysis_output}")
    elif args.run_analysis:
        print("Analysis stage skipped because live stage was skipped.")
    else:
        print("Analysis stage skipped.")

    print("Production workflow completed successfully.")
    return 0


def _capture_observed_order_command(argv: list[str]) -> int:
    args = _build_capture_observed_order_parser().parse_args(argv)

    if not args.no_preflight:
        preflight_exit_code = _run_preflight_with_mode(
            aggressive_msi_close=args.aggressive_msi_close,
            strict_preflight=args.strict_preflight,
        )
        if preflight_exit_code != 0:
            print(f"Preflight failed with exit code {preflight_exit_code}.")
            return preflight_exit_code

    try:
        active_color = _parse_rgb_triplet(args.active_color)
        inactive_color = _parse_rgb_triplet(args.inactive_color)
        vendor_id = _parse_optional_int(args.vendor_id)
        product_id = _parse_optional_int(args.product_id)
        driver = _build_keyboard_driver(
            backend=args.backend,
            zone_count=args.zone_count,
            hid_path=args.hid_path,
            vendor_id=vendor_id,
            product_id=product_id,
            report_id=args.report_id,
            write_method=args.write_method,
            pad_length=args.pad_length,
            packet_template=args.packet_template,
            calibration_profile_path=None,
        )
    except (ValueError, RuntimeError) as error:
        print(f"Capture-observed-order configuration error: {error}")
        return 2

    print("Interactive observed-order capture started.")
    print(
        f"For each logical zone, observe the lit zone on keyboard and enter "
        f"its hardware index in range 0..{args.zone_count - 1}."
    )
    try:
        observed_order = capture_observed_order_interactive(
            driver=driver,
            zone_count=args.zone_count,
            active_color=active_color,
            inactive_color=inactive_color,
            prompt_fn=input,
            print_fn=print,
        )
    except KeyboardInterrupt:
        print("Interactive capture cancelled.")
        return 130
    except Exception as error:
        print(f"Interactive capture failed: {error}")
        return 1

    try:
        profile = profile_from_observed_order(
            observed_order,
            zone_count=args.zone_count,
            source_method="capture-observed-order",
        )
        profile_path = write_calibration_profile(profile, args.profile_output)
        observed_path = args.observed_output
        observed_path.parent.mkdir(parents=True, exist_ok=True)
        observed_path.write_text(
            "\n".join(
                [
                    f"# zone_count={args.zone_count}",
                    f"observed_order={','.join(str(value) for value in observed_order)}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
    except ValueError as error:
        print(f"Interactive capture profile error: {error}")
        return 2

    print("Interactive capture completed.")
    print(f"Observed order output: {observed_path.resolve()}")
    print(f"Calibration profile output: {profile_path.resolve()}")
    return 0


def _run_preflight_with_mode(
    *,
    aggressive_msi_close: bool,
    strict_preflight: bool,
    report_path: Path | None = None,
) -> int:
    if strict_preflight:
        if report_path is None:
            return _run_preflight(aggressive_msi_close, strict_mode=True)
        return _run_preflight(
            aggressive_msi_close,
            strict_mode=True,
            report_path=report_path,
        )
    if report_path is None:
        return _run_preflight(aggressive_msi_close)
    return _run_preflight(aggressive_msi_close, report_path=report_path)


def _run_preflight(
    aggressive_msi_close: bool,
    strict_mode: bool = False,
    report_path: Path | None = None,
) -> int:
    preflight_script = Path("scripts/preflight.ps1")
    if not preflight_script.exists():
        print("Preflight script not found at scripts/preflight.ps1; continuing without it.")
        return 0

    resolved_report_path = (
        report_path if report_path is not None else Path("artifacts/preflight_report.json")
    )
    command = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(preflight_script),
        "-ReportPath",
        str(resolved_report_path),
    ]
    if aggressive_msi_close:
        command.append("-AggressiveMsiClose")
    if strict_mode:
        command.append("-StrictMode")
    result = subprocess.run(command, check=False)
    return result.returncode


def _parse_rgb_triplet(value: str) -> RgbColor:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 3:
        raise ValueError(f"Invalid RGB triplet '{value}'. Expected format: R,G,B")
    try:
        red, green, blue = (int(part) for part in parts)
    except ValueError as error:
        raise ValueError(f"Invalid RGB triplet '{value}'. Channels must be integers.") from error
    return RgbColor(red, green, blue).clamped()


def _parse_optional_int(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    try:
        return int(value, 0)
    except ValueError as error:
        raise ValueError(
            f"Invalid integer value '{value}'. Use decimal or 0x-prefixed hex."
        ) from error


def _build_capturer(
    *,
    capturer_name: str,
    monitor_index: int,
    capture_width: int,
    capture_height: int,
) -> MockGradientCapturer | WindowsMssCapturer:
    if capturer_name == "mock":
        return MockGradientCapturer(width=capture_width, height=capture_height)
    if capturer_name == "windows-mss":
        return WindowsMssCapturer(
            monitor_index=monitor_index,
            target_width=capture_width,
            target_height=capture_height,
        )
    raise ValueError(f"Unsupported capturer '{capturer_name}'")


def _build_mapper(
    *,
    mapper_name: str,
    rows: int,
    columns: int,
    zone_profile_path: Path | None,
) -> GridZoneMapper | CalibratedZoneMapper:
    if mapper_name == "grid":
        return GridZoneMapper(layout=GridLayout(rows=rows, columns=columns))
    if mapper_name == "calibrated":
        if zone_profile_path is None:
            raise ValueError("calibrated mapper requires --zone-profile.")
        profile = load_zone_geometry_profile(zone_profile_path)
        return CalibratedZoneMapper(profile)
    raise ValueError(f"Unsupported mapper '{mapper_name}'")


def _mapper_zone_count(mapper: GridZoneMapper | CalibratedZoneMapper) -> int:
    zone_count = getattr(mapper, "zone_count", None)
    if not isinstance(zone_count, int) or zone_count <= 0:
        raise ValueError("mapper zone_count is invalid.")
    return zone_count


def _build_keyboard_driver(
    *,
    backend: str,
    zone_count: int,
    hid_path: str | None,
    vendor_id: int | None,
    product_id: int | None,
    report_id: int,
    write_method: str,
    pad_length: int,
    packet_template: str,
    calibration_profile_path: Path | None = None,
) -> SimulatedKeyboardDriver | MsiMysticHidDriver | CalibratedDriver:
    if backend == "simulated":
        base_driver: SimulatedKeyboardDriver | MsiMysticHidDriver = SimulatedKeyboardDriver()
    elif backend == "msi-mystic-hid":
        base_driver = MsiMysticHidDriver(
            config=MsiMysticHidConfig(
                hid_path=hid_path,
                vendor_id=vendor_id if vendor_id is not None else 0x1462,
                product_id=product_id if product_id is not None else 0x1603,
                packet_template=packet_template,
                report_id=report_id,
                write_method=write_method,
                pad_length=pad_length,
                zone_count=zone_count,
            )
        )
    else:
        raise ValueError(f"Unsupported backend '{backend}'")

    if calibration_profile_path is None:
        return base_driver

    profile = load_calibration_profile(calibration_profile_path)
    if profile.zone_count != zone_count:
        raise ValueError(
            f"calibration profile zone_count {profile.zone_count} does not match "
            f"zone_count {zone_count}"
        )
    return CalibratedDriver(base_driver=base_driver, profile=profile)


def _parse_csv_str_list(value: str) -> list[str]:
    parsed = [item.strip() for item in value.split(",") if item.strip()]
    if not parsed:
        raise ValueError("Expected at least one comma-separated string value.")
    return parsed


def _parse_csv_int_list(value: str) -> list[int]:
    parts = [item.strip() for item in value.split(",") if item.strip()]
    if not parts:
        raise ValueError("Expected at least one comma-separated integer value.")
    values: list[int] = []
    for part in parts:
        try:
            values.append(int(part, 0))
        except ValueError as error:
            raise ValueError(f"Invalid integer value '{part}' in comma-separated list.") from error
    return values


def _parse_csv_float_list(value: str) -> list[float]:
    parts = [item.strip() for item in value.split(",") if item.strip()]
    if not parts:
        raise ValueError("Expected at least one comma-separated float value.")
    values: list[float] = []
    for part in parts:
        try:
            parsed = float(part)
        except ValueError as error:
            raise ValueError(f"Invalid float value '{part}' in comma-separated list.") from error
        values.append(parsed)
    return values


def _parse_row_column_weights(value: str) -> list[list[float]]:
    rows_raw = [item.strip() for item in value.split(";") if item.strip()]
    if not rows_raw:
        raise ValueError("Expected at least one ';' separated row of column weights.")
    return [_parse_csv_float_list(row_text) for row_text in rows_raw]


def _build_discovery_templates(values: list[str] | None) -> list[DiscoveryTemplate]:
    if values:
        return [
            DiscoveryTemplate(name=f"user-template-{index + 1}", template=value)
            for index, value in enumerate(values)
        ]

    defaults = [
        ("base", "{report_id} {zone} {r} {g} {b}"),
        ("aa-prefix", "{report_id} 0xAA {zone} {r} {g} {b}"),
        ("51-prefix", "{report_id} 0x51 {zone} {r} {g} {b}"),
        ("1b-prefix", "{report_id} 0x1B {zone} {r} {g} {b}"),
    ]
    return [DiscoveryTemplate(name=name, template=template) for name, template in defaults]


def _resolve_observed_order_text(order: str | None, order_file: Path | None) -> str:
    if order is not None and order_file is not None:
        raise ValueError("Provide either --order or --order-file, not both.")
    if order is not None:
        return order
    if order_file is not None:
        return order_file.read_text(encoding="utf-8")
    raise ValueError("Missing observed order input. Provide --order or --order-file.")


def _parse_optional_observed_order(order: str | None, order_file: Path | None) -> list[int] | None:
    if order is None and order_file is None:
        return None
    if order is not None and order_file is not None:
        raise ValueError("Provide either --observed-order or --observed-order-file, not both.")

    raw_text = _resolve_observed_order_text(order, order_file)
    trimmed = raw_text.strip()
    if trimmed == "":
        raise ValueError("Observed order input is empty.")

    if "observed_order" in raw_text:
        match = re.search(r"observed_order\s*=\s*(.*)", raw_text)
        if match is None:
            raise ValueError("Could not parse observed_order from file.")
        extracted = match.group(1).strip()
        if extracted == "":
            raise ValueError("observed_order is blank in observed-order file.")
        return _parse_int_sequence(extracted)

    return _parse_int_sequence(raw_text)


def _parse_int_sequence(value: str) -> list[int]:
    raw_parts = [part for part in re.split(r"[\s,]+", value.strip()) if part]
    if not raw_parts:
        raise ValueError("Observed order is empty.")
    parsed: list[int] = []
    for part in raw_parts:
        try:
            parsed.append(int(part, 10))
        except ValueError as error:
            raise ValueError(f"Invalid integer '{part}' in observed order.") from error
    return parsed


def _utc_now_tag() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")


def main(argv: list[str] | None = None) -> int:
    raw_args = sys.argv[1:] if argv is None else argv
    if raw_args:
        if raw_args[0] == "probe":
            return _probe_command(raw_args[1:])
        if raw_args[0] == "sweep":
            return _sweep_command(raw_args[1:])
        if raw_args[0] == "write-zone":
            return _write_zone_command(raw_args[1:])
        if raw_args[0] == "discover-hid":
            return _discover_hid_command(raw_args[1:])
        if raw_args[0] == "discover-effects":
            return _discover_effects_command(raw_args[1:])
        if raw_args[0] == "discover-zone-protocol":
            return _discover_zone_protocol_command(raw_args[1:])
        if raw_args[0] == "init-calibration":
            return _init_calibration_command(raw_args[1:])
        if raw_args[0] == "build-calibration":
            return _build_calibration_command(raw_args[1:])
        if raw_args[0] == "calibrate-zones":
            return _calibrate_zones_command(raw_args[1:])
        if raw_args[0] == "build-zone-profile":
            return _build_zone_profile_command(raw_args[1:])
        if raw_args[0] == "live":
            return _live_command(raw_args[1:])
        if raw_args[0] == "list-monitors":
            return _list_monitors_command(raw_args[1:])
        if raw_args[0] == "analyze-live":
            return _analyze_live_command(raw_args[1:])
        if raw_args[0] == "readiness-check":
            return _readiness_check_command(raw_args[1:])
        if raw_args[0] == "build-runtime-config":
            return _runtime_config_command(raw_args[1:])
        if raw_args[0] == "capture-observed-order":
            return _capture_observed_order_command(raw_args[1:])
        if raw_args[0] == "run-production":
            return _run_production_command(raw_args[1:])

    return _run_command(raw_args)


if __name__ == "__main__":
    raise SystemExit(main())
