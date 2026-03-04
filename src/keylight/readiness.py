from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from keylight.calibration import load_calibration_profile
from keylight.drivers.hid_raw import list_hid_devices
from keylight.mapping.calibrated_mapper import load_zone_geometry_profile
from keylight.runtime_config import LiveCommandDefaults, load_live_command_defaults


@dataclass(frozen=True, slots=True)
class ReadinessCheckConfig:
    config_path: Path
    require_hardware_backend: bool = False
    require_calibrated_mapper: bool = False
    require_calibration_profile: bool = False
    require_calibration_profile_generated_timestamp: bool = False
    require_calibration_profile_provenance: bool = False
    require_calibration_profile_provenance_workflow_match: bool = False
    max_calibration_profile_age_seconds: int | None = None
    forbid_identity_calibration: bool = False
    require_calibration_workflow: bool = False
    calibration_workflow_report_path: Path = Path("artifacts/calibrate_report_final.json")
    max_calibration_workflow_age_seconds: int | None = None
    require_calibration_verify_executed: bool = False
    require_calibration_live_verify_executed: bool = False
    require_calibration_live_verify_success: bool = False
    require_preflight_clean: bool = True
    require_preflight_admin: bool = False
    require_preflight_strict_mode: bool = False
    require_preflight_access_denied_clear: bool = False
    preflight_report_path: Path = Path("artifacts/preflight_report.json")
    max_preflight_age_seconds: int | None = None
    require_live_analysis_pass: bool = False
    live_analysis_report_path: Path = Path("artifacts/live_analysis_report.json")
    max_live_analysis_age_seconds: int | None = None
    max_live_analysis_threshold_max_error_rate_percent: float | None = None
    max_live_analysis_threshold_max_avg_total_ms: float | None = None
    max_live_analysis_threshold_max_p95_total_ms: float | None = None
    min_live_analysis_threshold_min_effective_fps: float | None = None
    max_live_analysis_threshold_max_overrun_percent: float | None = None
    require_hid_present: bool = False
    hid_path_override: str | None = None


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    generated_at_utc: str
    config_path: str
    backend: str
    mapper: str
    zone_count: int
    calibration_profile_path: str | None
    calibration_workflow_report_path: str
    preflight_report_path: str
    live_analysis_report_path: str
    hid_path_checked: str | None
    passed: bool
    pass_checks: list[str]
    failed_checks: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "config_path": self.config_path,
            "backend": self.backend,
            "mapper": self.mapper,
            "zone_count": self.zone_count,
            "calibration_profile_path": self.calibration_profile_path,
            "calibration_workflow_report_path": self.calibration_workflow_report_path,
            "preflight_report_path": self.preflight_report_path,
            "live_analysis_report_path": self.live_analysis_report_path,
            "hid_path_checked": self.hid_path_checked,
            "passed": self.passed,
            "pass_checks": self.pass_checks,
            "failed_checks": self.failed_checks,
        }


def run_readiness_check(config: ReadinessCheckConfig) -> ReadinessReport:
    pass_checks: list[str] = []
    failed_checks: list[str] = []

    _validate_optional_non_negative(
        "max_calibration_profile_age_seconds",
        config.max_calibration_profile_age_seconds,
    )
    _validate_optional_non_negative(
        "max_calibration_workflow_age_seconds",
        config.max_calibration_workflow_age_seconds,
    )
    _validate_optional_non_negative_float(
        "max_live_analysis_threshold_max_error_rate_percent",
        config.max_live_analysis_threshold_max_error_rate_percent,
    )
    _validate_optional_non_negative_float(
        "max_live_analysis_threshold_max_avg_total_ms",
        config.max_live_analysis_threshold_max_avg_total_ms,
    )
    _validate_optional_non_negative_float(
        "max_live_analysis_threshold_max_p95_total_ms",
        config.max_live_analysis_threshold_max_p95_total_ms,
    )
    _validate_optional_non_negative_float(
        "min_live_analysis_threshold_min_effective_fps",
        config.min_live_analysis_threshold_min_effective_fps,
    )
    _validate_optional_percent_float(
        "max_live_analysis_threshold_max_overrun_percent",
        config.max_live_analysis_threshold_max_overrun_percent,
    )
    _validate_optional_non_negative(
        "max_preflight_age_seconds",
        config.max_preflight_age_seconds,
    )
    _validate_optional_non_negative(
        "max_live_analysis_age_seconds",
        config.max_live_analysis_age_seconds,
    )

    defaults = load_live_command_defaults(config.config_path, must_exist=True)

    if config.require_hardware_backend:
        if defaults.backend == "msi-mystic-hid":
            pass_checks.append("hardware_backend_configured")
        else:
            failed_checks.append(f"backend_is_not_hardware:{defaults.backend}")

    if config.require_calibrated_mapper:
        if defaults.mapper == "calibrated":
            pass_checks.append("calibrated_mapper_configured")
        else:
            failed_checks.append(f"mapper_is_not_calibrated:{defaults.mapper}")

    zone_count = _resolve_zone_count(defaults)
    pass_checks.append(f"zone_count_resolved={zone_count}")

    calibration_profile_path = defaults.calibration_profile
    calibration_profile = None
    calibration_profile_root: dict[str, object] | None = None
    calibration_profile_root_load_error: ValueError | None = None
    calibration_profile_provenance_workflow_path: str | None = None
    should_load_calibration_profile_root = (
        config.max_calibration_profile_age_seconds is not None
        or config.require_calibration_profile_generated_timestamp
        or config.require_calibration_profile_provenance
        or config.require_calibration_profile_provenance_workflow_match
    )
    if calibration_profile_path is None:
        if config.require_calibration_profile or config.forbid_identity_calibration:
            failed_checks.append("calibration_profile_missing")
        pass_checks.append("calibration_profile_not_set")
    else:
        calibration_profile = load_calibration_profile(calibration_profile_path)
        if calibration_profile.zone_count == zone_count:
            pass_checks.append("calibration_profile_zone_count_matches_mapper")
        else:
            failed_checks.append(
                "calibration_profile_zone_count_mismatch: "
                f"profile={calibration_profile.zone_count} mapper={zone_count}"
            )
        if config.forbid_identity_calibration:
            identity = list(range(calibration_profile.zone_count))
            if calibration_profile.logical_to_hardware == identity:
                failed_checks.append("calibration_profile_is_identity")
            else:
                pass_checks.append("calibration_profile_not_identity")
        if should_load_calibration_profile_root:
            try:
                calibration_profile_root = _load_json_object(calibration_profile_path)
            except ValueError as error:
                calibration_profile_root_load_error = error

    if config.max_calibration_profile_age_seconds is not None:
        if calibration_profile_path is None:
            failed_checks.append("calibration_profile_age_error=calibration_profile_missing")
        elif calibration_profile_root_load_error is not None:
            failed_checks.append(
                "calibration_profile_age_error="
                f"{calibration_profile_root_load_error}"
            )
        else:
            assert calibration_profile_root is not None
            try:
                age_seconds = _artifact_age_seconds(
                    path=calibration_profile_path,
                    root=calibration_profile_root,
                    timestamp_field="generated_at_utc",
                )
            except ValueError as error:
                failed_checks.append(f"calibration_profile_age_error={error}")
            else:
                if age_seconds <= config.max_calibration_profile_age_seconds:
                    pass_checks.append(
                        "calibration_profile_age_seconds<="
                        f"{config.max_calibration_profile_age_seconds}:{age_seconds}"
                    )
                else:
                    failed_checks.append(
                        "calibration_profile_too_old:"
                        f"age_seconds={age_seconds} "
                        f"max={config.max_calibration_profile_age_seconds}"
                    )
    else:
        pass_checks.append("calibration_profile_age_check_skipped")

    if config.require_calibration_profile_generated_timestamp:
        if calibration_profile_path is None:
            failed_checks.append(
                "calibration_profile_generated_timestamp_error=calibration_profile_missing"
            )
        elif calibration_profile_root_load_error is not None:
            failed_checks.append(
                "calibration_profile_generated_timestamp_error="
                f"{calibration_profile_root_load_error}"
            )
        else:
            assert calibration_profile_root is not None
            try:
                timestamp_value = _required_string_field(
                    calibration_profile_root,
                    "generated_at_utc",
                )
                _parse_iso_datetime(timestamp_value)
            except ValueError as error:
                failed_checks.append(
                    f"calibration_profile_generated_timestamp_error={error}"
                )
            else:
                pass_checks.append("calibration_profile_generated_timestamp_present")
    else:
        pass_checks.append("calibration_profile_generated_timestamp_check_skipped")

    if (
        config.require_calibration_profile_provenance
        or config.require_calibration_profile_provenance_workflow_match
    ):
        if calibration_profile_path is None:
            provenance_error: ValueError | None = ValueError("calibration_profile_missing")
        elif calibration_profile_root_load_error is not None:
            provenance_error = calibration_profile_root_load_error
        else:
            assert calibration_profile_root is not None
            try:
                provenance_root = _dict_field(calibration_profile_root, "provenance")
                provenance_method = _required_string_field(provenance_root, "method")
                provenance_observed_order = _int_list_field(
                    provenance_root,
                    "observed_order",
                )
                calibration_profile_provenance_workflow_path = _string_or_none_field(
                    provenance_root,
                    "workflow_report_path",
                )
                if not _is_full_permutation(provenance_observed_order, zone_count):
                    raise ValueError(
                        "invalid_observed_order_permutation:provenance.observed_order"
                    )
                if calibration_profile is not None and (
                    provenance_observed_order != calibration_profile.logical_to_hardware
                ):
                    raise ValueError("observed_order_mismatch_profile")
            except ValueError as error:
                provenance_error = error
            else:
                provenance_error = None
                pass_checks.append(
                    f"calibration_profile_provenance_method={provenance_method}"
                )
                pass_checks.append(
                    "calibration_profile_provenance_observed_order_matches_profile"
                )

        if config.require_calibration_profile_provenance:
            if provenance_error is None:
                pass_checks.append("calibration_profile_provenance_valid")
            else:
                failed_checks.append(f"calibration_profile_provenance_error={provenance_error}")

        if config.require_calibration_profile_provenance_workflow_match:
            if provenance_error is not None:
                failed_checks.append(
                    "calibration_profile_provenance_workflow_match_error="
                    f"{provenance_error}"
                )
            elif calibration_profile_provenance_workflow_path is None:
                failed_checks.append(
                    "calibration_profile_provenance_workflow_match_error="
                    "missing_workflow_report_path"
                )
            else:
                assert calibration_profile_path is not None
                profile_workflow_resolved = _resolve_profile_path(
                    raw_path=calibration_profile_provenance_workflow_path,
                    profile_path=calibration_profile_path,
                )
                if profile_workflow_resolved == config.calibration_workflow_report_path.resolve():
                    pass_checks.append("calibration_profile_provenance_workflow_matches_config")
                else:
                    failed_checks.append(
                        "calibration_profile_provenance_workflow_mismatch:"
                        f"profile={profile_workflow_resolved} "
                        f"config={config.calibration_workflow_report_path.resolve()}"
                    )
    else:
        pass_checks.append("calibration_profile_provenance_check_skipped")
        pass_checks.append("calibration_profile_provenance_workflow_match_check_skipped")

    calibration_workflow_resolved = config.calibration_workflow_report_path.resolve()
    workflow_root: dict[str, object] | None = None
    workflow_load_error: ValueError | None = None
    if (
        config.require_calibration_workflow
        or config.require_calibration_verify_executed
        or config.require_calibration_live_verify_executed
        or config.require_calibration_live_verify_success
        or config.max_calibration_workflow_age_seconds is not None
    ):
        try:
            workflow_root = _load_json_object(config.calibration_workflow_report_path)
        except ValueError as error:
            workflow_load_error = error

    if config.require_calibration_workflow:
        if workflow_load_error is not None:
            failed_checks.append(f"calibration_workflow_report_error={workflow_load_error}")
        else:
            assert workflow_root is not None
            try:
                workflow_zone_count = _int_field(workflow_root, "zone_count")
                profile_built = _bool_field(workflow_root, "profile_built")
                observed_order = _int_list_field(workflow_root, "observed_order")
                profile_output_path = _required_string_field(workflow_root, "profile_output_path")
            except ValueError as error:
                failed_checks.append(f"calibration_workflow_report_error={error}")
            else:
                if workflow_zone_count == zone_count:
                    pass_checks.append("calibration_workflow_zone_count_matches_mapper")
                else:
                    failed_checks.append(
                        "calibration_workflow_zone_count_mismatch:"
                        f"report={workflow_zone_count} mapper={zone_count}"
                    )
                if profile_built:
                    pass_checks.append("calibration_workflow_profile_built")
                else:
                    failed_checks.append("calibration_workflow_profile_not_built")
                if _is_full_permutation(observed_order, workflow_zone_count):
                    pass_checks.append("calibration_workflow_observed_order_valid")
                else:
                    failed_checks.append("calibration_workflow_observed_order_invalid")
                if calibration_profile is not None:
                    if observed_order == calibration_profile.logical_to_hardware:
                        pass_checks.append("calibration_workflow_observed_order_matches_profile")
                    else:
                        failed_checks.append(
                            "calibration_workflow_observed_order_mismatch_profile"
                        )
                else:
                    pass_checks.append("calibration_workflow_observed_order_match_skipped")
                if calibration_profile_path is not None:
                    report_profile_resolved = _resolve_report_path(
                        raw_path=profile_output_path,
                        report_path=config.calibration_workflow_report_path,
                    )
                    if report_profile_resolved == calibration_profile_path.resolve():
                        pass_checks.append("calibration_workflow_profile_matches_config")
                    else:
                        failed_checks.append(
                            "calibration_workflow_profile_mismatch:"
                            f"report={report_profile_resolved} "
                            f"config={calibration_profile_path.resolve()}"
                        )
                else:
                    pass_checks.append("calibration_workflow_profile_match_skipped")
    else:
        pass_checks.append("calibration_workflow_check_skipped")

    if config.require_calibration_verify_executed:
        if workflow_load_error is not None:
            failed_checks.append(f"calibration_workflow_verify_error={workflow_load_error}")
        else:
            assert workflow_root is not None
            try:
                verify_executed = _bool_field(workflow_root, "verify_executed")
                verify_steps_executed = _int_field(workflow_root, "verify_steps_executed")
                workflow_zone_count = _int_field(workflow_root, "zone_count")
            except ValueError as error:
                failed_checks.append(f"calibration_workflow_verify_error={error}")
            else:
                if verify_executed and verify_steps_executed >= workflow_zone_count:
                    pass_checks.append("calibration_workflow_verify_executed")
                else:
                    failed_checks.append(
                        "calibration_workflow_verify_not_executed:"
                        f"verify_executed={verify_executed} "
                        f"verify_steps_executed={verify_steps_executed}"
                    )
    else:
        pass_checks.append("calibration_workflow_verify_check_skipped")

    if config.require_calibration_live_verify_executed:
        if workflow_load_error is not None:
            failed_checks.append(
                f"calibration_workflow_live_verify_error={workflow_load_error}"
            )
        else:
            assert workflow_root is not None
            try:
                live_verify_executed = _bool_field(workflow_root, "live_verify_executed")
            except ValueError as error:
                failed_checks.append(f"calibration_workflow_live_verify_error={error}")
            else:
                if live_verify_executed:
                    pass_checks.append("calibration_workflow_live_verify_executed")
                else:
                    failed_checks.append("calibration_workflow_live_verify_not_executed")
    else:
        pass_checks.append("calibration_workflow_live_verify_check_skipped")

    if config.require_calibration_live_verify_success:
        if workflow_load_error is not None:
            failed_checks.append(
                f"calibration_workflow_live_verify_success_error={workflow_load_error}"
            )
        else:
            assert workflow_root is not None
            try:
                live_verify_executed = _bool_field(workflow_root, "live_verify_executed")
                live_verify_error = _string_or_none_field(workflow_root, "live_verify_error")
            except ValueError as error:
                failed_checks.append(
                    f"calibration_workflow_live_verify_success_error={error}"
                )
            else:
                if live_verify_executed and live_verify_error is None:
                    pass_checks.append("calibration_workflow_live_verify_success")
                else:
                    failed_checks.append(
                        "calibration_workflow_live_verify_failed:"
                        f"live_verify_executed={live_verify_executed} "
                        f"live_verify_error={live_verify_error}"
                    )
    else:
        pass_checks.append("calibration_workflow_live_verify_success_check_skipped")

    if config.max_calibration_workflow_age_seconds is not None:
        if workflow_load_error is not None:
            failed_checks.append(f"calibration_workflow_age_error={workflow_load_error}")
        else:
            assert workflow_root is not None
            try:
                age_seconds = _artifact_age_seconds(
                    path=config.calibration_workflow_report_path,
                    root=workflow_root,
                    timestamp_field="finished_at_utc",
                )
            except ValueError as error:
                failed_checks.append(f"calibration_workflow_age_error={error}")
            else:
                if age_seconds <= config.max_calibration_workflow_age_seconds:
                    pass_checks.append(
                        "calibration_workflow_age_seconds<="
                        f"{config.max_calibration_workflow_age_seconds}:{age_seconds}"
                    )
                else:
                    failed_checks.append(
                        "calibration_workflow_too_old:"
                        f"age_seconds={age_seconds} "
                        f"max={config.max_calibration_workflow_age_seconds}"
                    )
    else:
        pass_checks.append("calibration_workflow_age_check_skipped")

    preflight_resolved = config.preflight_report_path.resolve()
    preflight_root: dict[str, object] | None = None
    preflight_load_error: ValueError | None = None
    if (
        config.require_preflight_clean
        or config.require_preflight_admin
        or config.require_preflight_strict_mode
        or config.require_preflight_access_denied_clear
        or config.max_preflight_age_seconds is not None
    ):
        try:
            preflight_root = _load_json_object(config.preflight_report_path)
        except ValueError as error:
            preflight_load_error = error

    if config.require_preflight_clean:
        if preflight_load_error is not None:
            failed_checks.append(f"preflight_report_error={preflight_load_error}")
        else:
            assert preflight_root is not None
            try:
                unresolved = _int_field(preflight_root, "unresolved_count")
            except ValueError as error:
                failed_checks.append(f"preflight_report_error={error}")
            else:
                if unresolved == 0:
                    pass_checks.append("preflight_unresolved_count==0")
                else:
                    failed_checks.append(f"preflight_unresolved_count={unresolved}")
    else:
        pass_checks.append("preflight_clean_check_skipped")

    if config.require_preflight_admin:
        if preflight_load_error is not None:
            failed_checks.append(f"preflight_admin_check_error={preflight_load_error}")
        else:
            assert preflight_root is not None
            try:
                is_admin = _bool_field(preflight_root, "is_admin")
            except ValueError as error:
                failed_checks.append(f"preflight_admin_check_error={error}")
            else:
                if is_admin:
                    pass_checks.append("preflight_is_admin")
                else:
                    failed_checks.append("preflight_is_not_admin")
    else:
        pass_checks.append("preflight_admin_check_skipped")

    if config.require_preflight_strict_mode:
        if preflight_load_error is not None:
            failed_checks.append(f"preflight_strict_mode_error={preflight_load_error}")
        else:
            assert preflight_root is not None
            try:
                strict_mode = _bool_field(preflight_root, "strict_mode")
            except ValueError as error:
                failed_checks.append(f"preflight_strict_mode_error={error}")
            else:
                if strict_mode:
                    pass_checks.append("preflight_strict_mode=true")
                else:
                    failed_checks.append("preflight_strict_mode=false")
    else:
        pass_checks.append("preflight_strict_mode_check_skipped")

    if config.require_preflight_access_denied_clear:
        if preflight_load_error is not None:
            failed_checks.append(
                f"preflight_access_denied_check_error={preflight_load_error}"
            )
        else:
            assert preflight_root is not None
            try:
                access_denied_count = _int_field(preflight_root, "access_denied_count")
            except ValueError as error:
                failed_checks.append(f"preflight_access_denied_check_error={error}")
            else:
                if access_denied_count == 0:
                    pass_checks.append("preflight_access_denied_count==0")
                else:
                    failed_checks.append(f"preflight_access_denied_count={access_denied_count}")
    else:
        pass_checks.append("preflight_access_denied_check_skipped")

    if config.max_preflight_age_seconds is not None:
        if preflight_load_error is not None:
            failed_checks.append(f"preflight_report_age_error={preflight_load_error}")
        else:
            assert preflight_root is not None
            try:
                age_seconds = _artifact_age_seconds(
                    path=config.preflight_report_path,
                    root=preflight_root,
                    timestamp_field="generated_at_utc",
                )
            except ValueError as error:
                failed_checks.append(f"preflight_report_age_error={error}")
            else:
                if age_seconds <= config.max_preflight_age_seconds:
                    pass_checks.append(
                        f"preflight_report_age_seconds<={config.max_preflight_age_seconds}:"
                        f"{age_seconds}"
                    )
                else:
                    failed_checks.append(
                        "preflight_report_too_old:"
                        f"age_seconds={age_seconds} max={config.max_preflight_age_seconds}"
                    )
    else:
        pass_checks.append("preflight_age_check_skipped")

    live_analysis_resolved = config.live_analysis_report_path.resolve()
    live_analysis_root: dict[str, object] | None = None
    live_analysis_load_error: ValueError | None = None
    if (
        config.require_live_analysis_pass
        or config.max_live_analysis_age_seconds is not None
        or _has_live_analysis_threshold_policy(config)
    ):
        try:
            live_analysis_root = _load_json_object(config.live_analysis_report_path)
        except ValueError as error:
            live_analysis_load_error = error

    if config.require_live_analysis_pass:
        if live_analysis_load_error is not None:
            failed_checks.append(f"live_analysis_report_error={live_analysis_load_error}")
        else:
            assert live_analysis_root is not None
            try:
                analysis_passed = _bool_field(live_analysis_root, "passed")
            except ValueError as error:
                failed_checks.append(f"live_analysis_report_error={error}")
            else:
                if analysis_passed:
                    pass_checks.append("live_analysis_passed")
                else:
                    failed_checks.append("live_analysis_passed=false")
    else:
        pass_checks.append("live_analysis_check_skipped")

    if _has_live_analysis_threshold_policy(config):
        if live_analysis_load_error is not None:
            failed_checks.append(f"live_analysis_threshold_policy_error={live_analysis_load_error}")
        else:
            assert live_analysis_root is not None
            try:
                thresholds_root = _dict_field(live_analysis_root, "thresholds")
                report_max_error_rate_percent = _float_field(
                    thresholds_root,
                    "max_error_rate_percent",
                )
                report_max_avg_total_ms = _float_field(
                    thresholds_root,
                    "max_avg_total_ms",
                )
                report_max_p95_total_ms = _float_field(
                    thresholds_root,
                    "max_p95_total_ms",
                )
                report_min_effective_fps = _float_field(
                    thresholds_root,
                    "min_effective_fps",
                )
                report_max_overrun_percent = _float_field(
                    thresholds_root,
                    "max_overrun_percent",
                )
            except ValueError as error:
                failed_checks.append(f"live_analysis_threshold_policy_error={error}")
            else:
                _check_max_threshold(
                    config_value=config.max_live_analysis_threshold_max_error_rate_percent,
                    report_value=report_max_error_rate_percent,
                    key="max_error_rate_percent",
                    pass_checks=pass_checks,
                    failed_checks=failed_checks,
                )
                _check_max_threshold(
                    config_value=config.max_live_analysis_threshold_max_avg_total_ms,
                    report_value=report_max_avg_total_ms,
                    key="max_avg_total_ms",
                    pass_checks=pass_checks,
                    failed_checks=failed_checks,
                )
                _check_max_threshold(
                    config_value=config.max_live_analysis_threshold_max_p95_total_ms,
                    report_value=report_max_p95_total_ms,
                    key="max_p95_total_ms",
                    pass_checks=pass_checks,
                    failed_checks=failed_checks,
                )
                _check_min_threshold(
                    config_value=config.min_live_analysis_threshold_min_effective_fps,
                    report_value=report_min_effective_fps,
                    key="min_effective_fps",
                    pass_checks=pass_checks,
                    failed_checks=failed_checks,
                )
                _check_max_threshold(
                    config_value=config.max_live_analysis_threshold_max_overrun_percent,
                    report_value=report_max_overrun_percent,
                    key="max_overrun_percent",
                    pass_checks=pass_checks,
                    failed_checks=failed_checks,
                )
    else:
        pass_checks.append("live_analysis_threshold_policy_check_skipped")

    if config.max_live_analysis_age_seconds is not None:
        if live_analysis_load_error is not None:
            failed_checks.append(f"live_analysis_age_error={live_analysis_load_error}")
        else:
            assert live_analysis_root is not None
            try:
                age_seconds = _artifact_age_seconds(
                    path=config.live_analysis_report_path,
                    root=live_analysis_root,
                    timestamp_field="generated_at_utc",
                )
            except ValueError as error:
                failed_checks.append(f"live_analysis_age_error={error}")
            else:
                if age_seconds <= config.max_live_analysis_age_seconds:
                    pass_checks.append(
                        f"live_analysis_age_seconds<={config.max_live_analysis_age_seconds}:"
                        f"{age_seconds}"
                    )
                else:
                    failed_checks.append(
                        "live_analysis_report_too_old:"
                        f"age_seconds={age_seconds} max={config.max_live_analysis_age_seconds}"
                    )
    else:
        pass_checks.append("live_analysis_age_check_skipped")

    hid_path_checked = config.hid_path_override or defaults.hid_path
    if config.require_hid_present:
        hid_ok, hid_detail = _check_hid_presence(defaults=defaults, hid_path=hid_path_checked)
        if hid_ok:
            pass_checks.append(hid_detail)
        else:
            failed_checks.append(hid_detail)
    else:
        pass_checks.append("hid_presence_check_skipped")

    passed = len(failed_checks) == 0
    return ReadinessReport(
        generated_at_utc=_utc_now_iso(),
        config_path=str(config.config_path.resolve()),
        backend=defaults.backend,
        mapper=defaults.mapper,
        zone_count=zone_count,
        calibration_profile_path=(
            str(calibration_profile_path.resolve()) if calibration_profile_path else None
        ),
        calibration_workflow_report_path=str(calibration_workflow_resolved),
        preflight_report_path=str(preflight_resolved),
        live_analysis_report_path=str(live_analysis_resolved),
        hid_path_checked=hid_path_checked,
        passed=passed,
        pass_checks=pass_checks,
        failed_checks=failed_checks,
    )


def write_readiness_report(report: ReadinessReport, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return output_path


def _resolve_zone_count(defaults: LiveCommandDefaults) -> int:
    if defaults.mapper == "grid":
        return defaults.rows * defaults.columns
    if defaults.mapper == "calibrated":
        if defaults.zone_profile is None:
            raise ValueError("mapping.zone_profile is required for calibrated mapper.")
        profile = load_zone_geometry_profile(defaults.zone_profile)
        return profile.zone_count
    raise ValueError(f"Unsupported mapper '{defaults.mapper}' in defaults.")


def _check_hid_presence(*, defaults: LiveCommandDefaults, hid_path: str | None) -> tuple[bool, str]:
    if defaults.backend != "msi-mystic-hid":
        return (True, "hid_presence_not_required_for_backend")

    try:
        devices = list_hid_devices()
    except RuntimeError as error:
        return (False, f"hid_enumeration_error={error}")

    if hid_path:
        exists = any(device.path == hid_path for device in devices)
        if exists:
            return (True, "hid_path_present")
        return (False, "hid_path_not_found")

    vendor_id = _parse_optional_int(defaults.vendor_id)
    product_id = _parse_optional_int(defaults.product_id)
    if vendor_id is None or product_id is None:
        return (False, "hid_target_missing_path_and_vid_pid")
    exists = any(
        device.vendor_id == vendor_id and device.product_id == product_id for device in devices
    )
    if exists:
        return (True, "hid_vid_pid_present")
    return (False, "hid_vid_pid_not_found")


def _parse_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    text = value.strip()
    if text == "":
        return None
    try:
        return int(text, 0)
    except ValueError:
        return None


def _load_json_object(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ValueError(f"file_not_found:{path}")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid_json:{path}") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"invalid_root_object:{path}")
    return parsed


def _int_field(data: dict[str, object], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise ValueError(f"invalid_int_field:{key}")
    return value


def _bool_field(data: dict[str, object], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"invalid_bool_field:{key}")
    return value


def _dict_field(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"invalid_object_field:{key}")
    return value


def _float_field(data: dict[str, object], key: str) -> float:
    value = data.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"invalid_float_field:{key}")
    return float(value)


def _required_string_field(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError(f"invalid_string_field:{key}")
    text = value.strip()
    if text == "":
        raise ValueError(f"empty_string_field:{key}")
    return text


def _string_or_none_field(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"invalid_string_field:{key}")
    return value


def _int_list_field(data: dict[str, object], key: str) -> list[int]:
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError(f"invalid_list_field:{key}")
    items: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"invalid_int_list_item:{key}")
        items.append(item)
    return items


def _is_full_permutation(values: list[int], zone_count: int) -> bool:
    if len(values) != zone_count:
        return False
    return set(values) == set(range(zone_count))


def _resolve_report_path(*, raw_path: str, report_path: Path) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate.resolve()
    return (report_path.parent / candidate).resolve()


def _resolve_profile_path(*, raw_path: str, profile_path: Path) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate.resolve()
    return (profile_path.parent / candidate).resolve()


def _has_live_analysis_threshold_policy(config: ReadinessCheckConfig) -> bool:
    return (
        config.max_live_analysis_threshold_max_error_rate_percent is not None
        or config.max_live_analysis_threshold_max_avg_total_ms is not None
        or config.max_live_analysis_threshold_max_p95_total_ms is not None
        or config.min_live_analysis_threshold_min_effective_fps is not None
        or config.max_live_analysis_threshold_max_overrun_percent is not None
    )


def _check_max_threshold(
    *,
    config_value: float | None,
    report_value: float,
    key: str,
    pass_checks: list[str],
    failed_checks: list[str],
) -> None:
    if config_value is None:
        return
    if report_value <= config_value:
        pass_checks.append(
            f"live_analysis_threshold_{key}<={config_value:.3f}:report={report_value:.3f}"
        )
    else:
        failed_checks.append(
            f"live_analysis_threshold_{key}_too_weak:report={report_value:.3f} "
            f"required<={config_value:.3f}"
        )


def _check_min_threshold(
    *,
    config_value: float | None,
    report_value: float,
    key: str,
    pass_checks: list[str],
    failed_checks: list[str],
) -> None:
    if config_value is None:
        return
    if report_value >= config_value:
        pass_checks.append(
            f"live_analysis_threshold_{key}>={config_value:.3f}:report={report_value:.3f}"
        )
    else:
        failed_checks.append(
            f"live_analysis_threshold_{key}_too_weak:report={report_value:.3f} "
            f"required>={config_value:.3f}"
        )


def _artifact_age_seconds(*, path: Path, root: dict[str, object], timestamp_field: str) -> int:
    timestamp_value = root.get(timestamp_field)
    if timestamp_value is None:
        timestamp = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    elif isinstance(timestamp_value, str):
        timestamp = _parse_iso_datetime(timestamp_value)
    else:
        raise ValueError(f"invalid_timestamp_field:{timestamp_field}")

    age = _utc_now() - timestamp
    return max(0, int(age.total_seconds()))


def _parse_iso_datetime(value: str) -> datetime:
    text = value.strip()
    if text == "":
        raise ValueError("invalid_timestamp_value:empty")

    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    if "." in text:
        head, tail = text.split(".", maxsplit=1)
        tz_part = ""
        fraction = tail
        plus_index = tail.find("+")
        minus_index = tail.find("-")
        tz_index = -1
        if plus_index >= 0 and minus_index >= 0:
            tz_index = min(plus_index, minus_index)
        elif plus_index >= 0:
            tz_index = plus_index
        elif minus_index >= 0:
            tz_index = minus_index
        if tz_index >= 0:
            fraction = tail[:tz_index]
            tz_part = tail[tz_index:]
        if len(fraction) > 6:
            fraction = fraction[:6]
        text = f"{head}.{fraction}{tz_part}" if fraction else f"{head}{tz_part}"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError("invalid_timestamp_value") from error

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _validate_optional_non_negative(name: str, value: int | None) -> None:
    if value is not None and value < 0:
        raise ValueError(f"{name}_must_be_non_negative")


def _validate_optional_non_negative_float(name: str, value: float | None) -> None:
    if value is not None and value < 0:
        raise ValueError(f"{name}_must_be_non_negative")


def _validate_optional_percent_float(name: str, value: float | None) -> None:
    if value is None:
        return
    if value < 0 or value > 100:
        raise ValueError(f"{name}_must_be_in_range_0_100")


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _utc_now_iso() -> str:
    return _utc_now().isoformat(timespec="seconds")
