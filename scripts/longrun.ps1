param(
  [string]$PythonExe = ".\\.venv\\Scripts\\python.exe",
  [string]$ConfigPath = "config/default.toml",
  [double]$DurationHours = 8.0,
  [string]$OutputDir = "artifacts",
  [switch]$RunReadinessCheck,
  [switch]$RunPreflightBeforeReadiness,
  [switch]$PreflightStrictForReadiness,
  [switch]$PreflightAggressiveMsiCloseForReadiness,
  [switch]$RequireHardwareBackend,
  [switch]$RequireCalibratedMapper,
  [switch]$RequireCalibrationProfile,
  [switch]$RequireCalibrationProfileGeneratedTimestamp,
  [switch]$RequireCalibrationProfileProvenance,
  [switch]$RequireCalibrationProfileProvenanceWorkflowMatch,
  [int]$MaxCalibrationProfileAgeSeconds = -1,
  [switch]$RequireCalibrationWorkflow,
  [switch]$RequireCalibrationVerifyExecuted,
  [switch]$RequireCalibrationLiveVerifyExecuted,
  [switch]$RequireCalibrationLiveVerifySuccess,
  [switch]$ForbidIdentityCalibration,
  [switch]$RequireHidPresent,
  [switch]$RequirePreflightCleanForReadiness,
  [switch]$RequirePreflightAdminForReadiness,
  [switch]$RequirePreflightStrictModeForReadiness,
  [switch]$RequirePreflightAccessDeniedClearForReadiness,
  [string]$CalibrationWorkflowReport = "",
  [int]$MaxCalibrationWorkflowAgeSeconds = -1,
  [int]$MaxPreflightAgeSeconds = -1,
  [int]$MaxLiveAnalysisAgeSeconds = -1,
  [int]$WatchdogInterval = 300,
  [int]$EventLogInterval = 30,
  [bool]$Analyze = $true,
  [double]$MaxErrorRatePercent = 1.0,
  [double]$MaxAvgTotalMs = 80.0,
  [double]$MaxP95TotalMs = 120.0,
  [double]$MinEffectiveFps = 0.0,
  [double]$MaxOverrunPercent = 100.0,
  [bool]$RequireNoAbort = $true,
  [int]$MinCompletedIterations = 1,
  [switch]$RestoreOnExit,
  [string]$RestoreColor = "0,0,0",
  [switch]$StrictPreflight,
  [switch]$NoPreflight,
  [switch]$UseMock,
  [string]$Backend = "",
  [string]$HidPath = "",
  [string]$CalibrationProfile = ""
)

$ErrorActionPreference = "Stop"

if ($DurationHours -le 0) {
  throw "DurationHours must be positive."
}

if ($WatchdogInterval -lt 0) {
  throw "WatchdogInterval must be >= 0."
}

if ($EventLogInterval -lt 0) {
  throw "EventLogInterval must be >= 0."
}

if ($MaxPreflightAgeSeconds -lt -1) {
  throw "MaxPreflightAgeSeconds must be >= -1."
}

if ($MaxLiveAnalysisAgeSeconds -lt -1) {
  throw "MaxLiveAnalysisAgeSeconds must be >= -1."
}

if ($MaxCalibrationWorkflowAgeSeconds -lt -1) {
  throw "MaxCalibrationWorkflowAgeSeconds must be >= -1."
}

if ($MaxCalibrationProfileAgeSeconds -lt -1) {
  throw "MaxCalibrationProfileAgeSeconds must be >= -1."
}

if ($MinEffectiveFps -lt 0) {
  throw "MinEffectiveFps must be >= 0."
}

if ($MaxOverrunPercent -lt 0 -or $MaxOverrunPercent -gt 100) {
  throw "MaxOverrunPercent must be in range 0..100."
}

$pythonPathResolved = Resolve-Path -Path $PythonExe -ErrorAction SilentlyContinue
if (-not $pythonPathResolved) {
  throw "Python executable not found: $PythonExe"
}

if (-not (Test-Path -Path $ConfigPath)) {
  throw "Config file not found: $ConfigPath"
}

if (-not (Test-Path -Path $OutputDir)) {
  New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$durationSeconds = [int][Math]::Ceiling($DurationHours * 3600.0)
$reportPath = Join-Path -Path $OutputDir -ChildPath "live_report_$timestamp.json"
$watchdogPath = Join-Path -Path $OutputDir -ChildPath "live_watchdog_$timestamp.json"
$eventLogPath = Join-Path -Path $OutputDir -ChildPath "live_events_$timestamp.jsonl"
$analysisPath = Join-Path -Path $OutputDir -ChildPath "live_analysis_$timestamp.json"
$readinessPath = Join-Path -Path $OutputDir -ChildPath "readiness_$timestamp.json"

$args = @(
  "-m", "keylight.cli",
  "live",
  "--config", $ConfigPath,
  "--duration-seconds", "$durationSeconds",
  "--output", $reportPath
)

if ($WatchdogInterval -gt 0) {
  $args += @(
    "--watchdog-interval", "$WatchdogInterval",
    "--watchdog-output", $watchdogPath
  )
}

if ($EventLogInterval -gt 0) {
  $args += @(
    "--event-log-interval", "$EventLogInterval",
    "--event-log-output", $eventLogPath
  )
}

if ($RestoreOnExit) {
  $args += @(
    "--restore-on-exit",
    "--restore-color", $RestoreColor
  )
}

if ($StrictPreflight) {
  $args += "--strict-preflight"
}

if ($NoPreflight) {
  $args += "--no-preflight"
}

if ($UseMock) {
  $args += @("--capturer", "mock", "--backend", "simulated")
}

if (-not [string]::IsNullOrWhiteSpace($Backend)) {
  $args += @("--backend", $Backend)
}

if (-not [string]::IsNullOrWhiteSpace($HidPath)) {
  $args += @("--hid-path", $HidPath)
}

if (-not [string]::IsNullOrWhiteSpace($CalibrationProfile)) {
  $args += @("--calibration-profile", $CalibrationProfile)
}

Write-Host "Starting long-run validation..."
Write-Host "DurationHours: $DurationHours"
Write-Host "DurationSeconds: $durationSeconds"
Write-Host "ConfigPath: $ConfigPath"
Write-Host "ReportPath: $reportPath"
if ($WatchdogInterval -gt 0) {
  Write-Host "WatchdogPath: $watchdogPath"
}
if ($EventLogInterval -gt 0) {
  Write-Host "EventLogPath: $eventLogPath"
}
Write-Host "RestoreOnExit: $RestoreOnExit"
if ($RestoreOnExit) {
  Write-Host "RestoreColor: $RestoreColor"
}
if ($Analyze) {
  Write-Host "AnalysisPath: $analysisPath"
}
if ($RunReadinessCheck) {
  Write-Host "ReadinessPath: $readinessPath"
  Write-Host "RunPreflightBeforeReadiness: $RunPreflightBeforeReadiness"
}

if ($RunReadinessCheck) {
  $readinessArgs = @(
    "-m", "keylight.cli",
    "readiness-check",
    "--config", $ConfigPath,
    "--output", $readinessPath
  )
  if ($RunPreflightBeforeReadiness) {
    $readinessArgs += "--run-preflight"
    if ($PreflightStrictForReadiness) {
      $readinessArgs += "--preflight-strict-mode"
    }
    if ($PreflightAggressiveMsiCloseForReadiness) {
      $readinessArgs += "--preflight-aggressive-msi-close"
    }
  }
  if ($RequireHardwareBackend) {
    $readinessArgs += "--require-hardware-backend"
  } else {
    $readinessArgs += "--no-require-hardware-backend"
  }
  if ($RequireCalibratedMapper) {
    $readinessArgs += "--require-calibrated-mapper"
  } else {
    $readinessArgs += "--no-require-calibrated-mapper"
  }
  if ($RequireCalibrationProfile) {
    $readinessArgs += "--require-calibration-profile"
  } else {
    $readinessArgs += "--no-require-calibration-profile"
  }
  if ($RequireCalibrationProfileGeneratedTimestamp) {
    $readinessArgs += "--require-calibration-profile-generated-timestamp"
  } else {
    $readinessArgs += "--no-require-calibration-profile-generated-timestamp"
  }
  if ($RequireCalibrationProfileProvenance) {
    $readinessArgs += "--require-calibration-profile-provenance"
  } else {
    $readinessArgs += "--no-require-calibration-profile-provenance"
  }
  if ($RequireCalibrationProfileProvenanceWorkflowMatch) {
    $readinessArgs += "--require-calibration-profile-provenance-workflow-match"
  } else {
    $readinessArgs += "--no-require-calibration-profile-provenance-workflow-match"
  }
  if ($MaxCalibrationProfileAgeSeconds -ge 0) {
    $readinessArgs += @(
      "--max-calibration-profile-age-seconds",
      "$MaxCalibrationProfileAgeSeconds"
    )
  }
  if ($RequireCalibrationWorkflow) {
    $readinessArgs += "--require-calibration-workflow"
  } else {
    $readinessArgs += "--no-require-calibration-workflow"
  }
  if ($RequireCalibrationVerifyExecuted) {
    $readinessArgs += "--require-calibration-verify-executed"
  } else {
    $readinessArgs += "--no-require-calibration-verify-executed"
  }
  if ($RequireCalibrationLiveVerifyExecuted) {
    $readinessArgs += "--require-calibration-live-verify-executed"
  } else {
    $readinessArgs += "--no-require-calibration-live-verify-executed"
  }
  if ($RequireCalibrationLiveVerifySuccess) {
    $readinessArgs += "--require-calibration-live-verify-success"
  } else {
    $readinessArgs += "--no-require-calibration-live-verify-success"
  }
  if ($ForbidIdentityCalibration) {
    $readinessArgs += "--forbid-identity-calibration"
  } else {
    $readinessArgs += "--no-forbid-identity-calibration"
  }
  if ($RequireHidPresent) {
    $readinessArgs += "--require-hid-present"
    if (-not [string]::IsNullOrWhiteSpace($HidPath)) {
      $readinessArgs += @("--hid-path", $HidPath)
    }
  } else {
    $readinessArgs += "--no-require-hid-present"
  }
  if ($RequirePreflightCleanForReadiness) {
    $readinessArgs += "--require-preflight-clean"
  } else {
    $readinessArgs += "--no-require-preflight-clean"
  }
  if ($RequirePreflightAdminForReadiness) {
    $readinessArgs += "--require-preflight-admin"
  } else {
    $readinessArgs += "--no-require-preflight-admin"
  }
  if ($RequirePreflightStrictModeForReadiness) {
    $readinessArgs += "--require-preflight-strict-mode"
  } else {
    $readinessArgs += "--no-require-preflight-strict-mode"
  }
  if ($RequirePreflightAccessDeniedClearForReadiness) {
    $readinessArgs += "--require-preflight-access-denied-clear"
  } else {
    $readinessArgs += "--no-require-preflight-access-denied-clear"
  }
  if ($MaxPreflightAgeSeconds -ge 0) {
    $readinessArgs += @("--max-preflight-age-seconds", "$MaxPreflightAgeSeconds")
  }
  if ($MaxLiveAnalysisAgeSeconds -ge 0) {
    $readinessArgs += @("--max-live-analysis-age-seconds", "$MaxLiveAnalysisAgeSeconds")
  }
  if (-not [string]::IsNullOrWhiteSpace($CalibrationWorkflowReport)) {
    $readinessArgs += @("--calibration-workflow-report", $CalibrationWorkflowReport)
  }
  if ($MaxCalibrationWorkflowAgeSeconds -ge 0) {
    $readinessArgs += @(
      "--max-calibration-workflow-age-seconds",
      "$MaxCalibrationWorkflowAgeSeconds"
    )
  }

  & $PythonExe @readinessArgs
  $readinessExitCode = $LASTEXITCODE
  if ($readinessExitCode -ne 0) {
    throw "Readiness check failed with exit code $readinessExitCode."
  }
}

& $PythonExe @args
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
  throw "Live runtime failed with exit code $exitCode."
}

if ($Analyze) {
  $analysisArgs = @(
    "-m", "keylight.cli",
    "analyze-live",
    "--report", $reportPath,
    "--output", $analysisPath,
    "--max-error-rate-percent", "$MaxErrorRatePercent",
    "--max-avg-total-ms", "$MaxAvgTotalMs",
    "--max-p95-total-ms", "$MaxP95TotalMs",
    "--min-effective-fps", "$MinEffectiveFps",
    "--max-overrun-percent", "$MaxOverrunPercent",
    "--min-completed-iterations", "$MinCompletedIterations"
  )
  if ($RequireNoAbort) {
    $analysisArgs += "--require-no-abort"
  } else {
    $analysisArgs += "--no-require-no-abort"
  }
  if ((Test-Path -Path $eventLogPath) -and $EventLogInterval -gt 0) {
    $analysisArgs += @("--event-log", $eventLogPath)
  }

  & $PythonExe @analysisArgs
  $analysisExitCode = $LASTEXITCODE
  if ($analysisExitCode -ne 0) {
    throw "Live analysis failed with exit code $analysisExitCode."
  }
}

Write-Host "Long-run validation command completed successfully."
