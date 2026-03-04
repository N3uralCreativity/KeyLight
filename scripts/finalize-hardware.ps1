param(
  [string]$PythonExe = ".\\.venv\\Scripts\\python.exe",
  [string]$Backend = "msi-mystic-hid",
  [string]$HidPath = "",
  [int]$ZoneCount = 24,
  [int]$DelayMs = 1200,
  [string]$TemplateOutput = "artifacts/observed_order_template.txt",
  [string]$ObservedOrderFile = "artifacts/observed_order_template_filled.txt",
  [string]$ProfileOutput = "config/calibration/final.json",
  [string]$WorkflowOutput = "artifacts/calibrate_report_final.json",
  [string]$VerifyOutput = "artifacts/calibrate_verify_sweep_report.json",
  [string]$LiveOutput = "artifacts/calibrate_verify_live_report.json",
  [string]$RuntimeConfigBase = "config/default.toml",
  [string]$RuntimeConfigOutput = "config/hardware-final.toml",
  [string]$RuntimeZoneProfile = "config/mapping/msi_vector16_2x12.json",
  [string]$ReadinessOutput = "artifacts/readiness_report_finalize.json",
  [string]$ReadinessCalibrationWorkflowReport = "artifacts/calibrate_report_final.json",
  [switch]$ReadinessRequireCalibrationWorkflow,
  [switch]$ReadinessRequireCalibrationVerifyExecuted,
  [switch]$ReadinessRequireCalibrationLiveVerifyExecuted,
  [switch]$ReadinessRequireCalibrationLiveVerifySuccess,
  [switch]$ReadinessRequireCalibrationProfileGeneratedTimestamp,
  [switch]$ReadinessRequireCalibrationProfileProvenance,
  [switch]$ReadinessRequireCalibrationProfileProvenanceWorkflowMatch,
  [int]$ReadinessMaxCalibrationProfileAgeSeconds = -1,
  [switch]$ReadinessRequirePreflightAdmin,
  [switch]$ReadinessRequirePreflightStrictMode,
  [switch]$ReadinessRequirePreflightAccessDeniedClear,
  [int]$ReadinessMaxCalibrationWorkflowAgeSeconds = -1,
  [int]$ReadinessMaxPreflightAgeSeconds = 900,
  [switch]$RunStrictReadiness,
  [switch]$ReadinessRunPreflight,
  [switch]$ReadinessPreflightStrictMode,
  [switch]$ReadinessPreflightAggressiveMsiClose,
  [int]$LiveRows = 2,
  [int]$LiveColumns = 12,
  [int]$LiveFps = 30,
  [int]$LiveIterations = 120,
  [switch]$TemplateOnly,
  [switch]$NoPreflight,
  [switch]$AggressiveMsiClose,
  [switch]$NoStrictPreflight,
  [switch]$SkipVerifyLive,
  [switch]$SkipRuntimeConfigBuild
)

$ErrorActionPreference = "Stop"

if ($ZoneCount -le 0) {
  throw "ZoneCount must be positive."
}

if ($DelayMs -lt 0) {
  throw "DelayMs must be >= 0."
}

if ($ReadinessMaxPreflightAgeSeconds -lt -1) {
  throw "ReadinessMaxPreflightAgeSeconds must be >= -1."
}

if ($ReadinessMaxCalibrationWorkflowAgeSeconds -lt -1) {
  throw "ReadinessMaxCalibrationWorkflowAgeSeconds must be >= -1."
}

if ($ReadinessMaxCalibrationProfileAgeSeconds -lt -1) {
  throw "ReadinessMaxCalibrationProfileAgeSeconds must be >= -1."
}

if (-not (Test-Path -Path $PythonExe)) {
  throw "Python executable not found: $PythonExe"
}

if ($Backend -eq "msi-mystic-hid" -and [string]::IsNullOrWhiteSpace($HidPath)) {
  throw "HidPath is required when Backend is msi-mystic-hid."
}

$strictPreflight = -not $NoStrictPreflight
$verifyLive = -not $SkipVerifyLive

Write-Host "Finalize hardware workflow:"
Write-Host "  backend=$Backend zone_count=$ZoneCount delay_ms=$DelayMs"
Write-Host "  template_only=$TemplateOnly no_preflight=$NoPreflight strict_preflight=$strictPreflight verify_live=$verifyLive"
if ($Backend -eq "msi-mystic-hid") {
  Write-Host "  hid_path=$HidPath"
}

function Invoke-KeylightCommand {
  param(
    [string[]]$CommandArgs
  )

  & $PythonExe @CommandArgs
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    throw "Command failed with exit code ${exitCode}: keylight.cli $($CommandArgs -join ' ')"
  }
}

function Add-CommonCalibrateArgs {
  param(
    [System.Collections.Generic.List[string]]$ArgsList
  )

  if ($Backend -eq "msi-mystic-hid") {
    $ArgsList.Add("--hid-path")
    $ArgsList.Add($HidPath)
  }
  if ($NoPreflight) {
    $ArgsList.Add("--no-preflight")
  }
  if ($AggressiveMsiClose) {
    $ArgsList.Add("--aggressive-msi-close")
  }
  if ($strictPreflight) {
    $ArgsList.Add("--strict-preflight")
  }
}

$needsTemplate = $TemplateOnly -or -not (Test-Path -Path $ObservedOrderFile)

if ($needsTemplate) {
  Write-Host "Step 1/2: generating observed-order template..."
  $argsList = [System.Collections.Generic.List[string]]::new()
  foreach ($item in @(
      "-m", "keylight.cli",
      "calibrate-zones",
      "--backend", $Backend,
      "--zone-count", "$ZoneCount",
      "--delay-ms", "$DelayMs",
      "--template-output", $TemplateOutput,
      "--output", $WorkflowOutput
    )) {
    $argsList.Add([string]$item)
  }
  Add-CommonCalibrateArgs -ArgsList $argsList
  Invoke-KeylightCommand -CommandArgs $argsList.ToArray()

  Write-Host "Template generated: $TemplateOutput"
  Write-Host "Fill observed_order in that file, save as: $ObservedOrderFile"
  Write-Host "Then rerun this script without -TemplateOnly."
  exit 0
}

Write-Host "Step 2/2: building and verifying final calibration profile..."
$finalArgs = [System.Collections.Generic.List[string]]::new()
foreach ($item in @(
    "-m", "keylight.cli",
    "calibrate-zones",
    "--backend", $Backend,
    "--zone-count", "$ZoneCount",
    "--no-sweep",
    "--observed-order-file", $ObservedOrderFile,
    "--profile-output", $ProfileOutput,
    "--verify",
    "--verify-delay-ms", "$DelayMs",
    "--verify-output", $VerifyOutput,
    "--output", $WorkflowOutput
  )) {
  $finalArgs.Add([string]$item)
}
if ($verifyLive) {
  foreach ($item in @(
      "--verify-live",
      "--live-capturer", "windows-mss",
      "--live-rows", "$LiveRows",
      "--live-columns", "$LiveColumns",
      "--live-fps", "$LiveFps",
      "--live-iterations", "$LiveIterations",
      "--live-output", $LiveOutput
    )) {
    $finalArgs.Add([string]$item)
  }
}
Add-CommonCalibrateArgs -ArgsList $finalArgs
Invoke-KeylightCommand -CommandArgs $finalArgs.ToArray()

Write-Host "Final profile: $ProfileOutput"
Write-Host "Workflow report: $WorkflowOutput"
Write-Host "Verify sweep report: $VerifyOutput"
if ($verifyLive) {
  Write-Host "Verify live report: $LiveOutput"
}

if (-not $SkipRuntimeConfigBuild) {
  Write-Host "Building hardware runtime config..."
  $runtimeArgs = [System.Collections.Generic.List[string]]::new()
  foreach ($item in @(
      "-m", "keylight.cli",
      "build-runtime-config",
      "--base", $RuntimeConfigBase,
      "--output", $RuntimeConfigOutput,
      "--set-hardware-mode",
      "--set-longrun-mode",
      "--backend", $Backend,
      "--zone-profile", $RuntimeZoneProfile,
      "--calibration-profile", $ProfileOutput
    )) {
    $runtimeArgs.Add([string]$item)
  }
  if ($Backend -eq "msi-mystic-hid") {
    $runtimeArgs.Add("--hid-path")
    $runtimeArgs.Add($HidPath)
  }
  Invoke-KeylightCommand -CommandArgs $runtimeArgs.ToArray()
  Write-Host "Hardware runtime config: $RuntimeConfigOutput"
}

if ($RunStrictReadiness) {
  $readinessConfig = $RuntimeConfigOutput
  if ($SkipRuntimeConfigBuild) {
    $readinessConfig = $RuntimeConfigBase
  }
  Write-Host "Running strict readiness gate..."
  $readinessArgs = [System.Collections.Generic.List[string]]::new()
  foreach ($item in @(
      "-m", "keylight.cli",
      "readiness-check",
      "--config", $readinessConfig,
      "--require-hardware-backend",
      "--require-calibrated-mapper",
      "--require-calibration-profile",
      "--forbid-identity-calibration",
      "--require-preflight-clean",
      "--output", $ReadinessOutput
    )) {
    $readinessArgs.Add([string]$item)
  }
  if ($ReadinessMaxPreflightAgeSeconds -ge 0) {
    $readinessArgs.Add("--max-preflight-age-seconds")
    $readinessArgs.Add("$ReadinessMaxPreflightAgeSeconds")
  }
  if ($ReadinessRequireCalibrationProfileGeneratedTimestamp) {
    $readinessArgs.Add("--require-calibration-profile-generated-timestamp")
  } else {
    $readinessArgs.Add("--no-require-calibration-profile-generated-timestamp")
  }
  if ($ReadinessRequireCalibrationProfileProvenance) {
    $readinessArgs.Add("--require-calibration-profile-provenance")
  } else {
    $readinessArgs.Add("--no-require-calibration-profile-provenance")
  }
  if ($ReadinessRequireCalibrationProfileProvenanceWorkflowMatch) {
    $readinessArgs.Add("--require-calibration-profile-provenance-workflow-match")
  } else {
    $readinessArgs.Add("--no-require-calibration-profile-provenance-workflow-match")
  }
  if ($ReadinessRequirePreflightAdmin) {
    $readinessArgs.Add("--require-preflight-admin")
  } else {
    $readinessArgs.Add("--no-require-preflight-admin")
  }
  if ($ReadinessRequirePreflightStrictMode) {
    $readinessArgs.Add("--require-preflight-strict-mode")
  } else {
    $readinessArgs.Add("--no-require-preflight-strict-mode")
  }
  if ($ReadinessRequirePreflightAccessDeniedClear) {
    $readinessArgs.Add("--require-preflight-access-denied-clear")
  } else {
    $readinessArgs.Add("--no-require-preflight-access-denied-clear")
  }
  if ($ReadinessRequireCalibrationWorkflow) {
    $readinessArgs.Add("--require-calibration-workflow")
  } else {
    $readinessArgs.Add("--no-require-calibration-workflow")
  }
  if ($ReadinessMaxCalibrationProfileAgeSeconds -ge 0) {
    $readinessArgs.Add("--max-calibration-profile-age-seconds")
    $readinessArgs.Add("$ReadinessMaxCalibrationProfileAgeSeconds")
  }
  if ($ReadinessRequireCalibrationVerifyExecuted) {
    $readinessArgs.Add("--require-calibration-verify-executed")
  } else {
    $readinessArgs.Add("--no-require-calibration-verify-executed")
  }
  if ($ReadinessRequireCalibrationLiveVerifyExecuted) {
    $readinessArgs.Add("--require-calibration-live-verify-executed")
  } else {
    $readinessArgs.Add("--no-require-calibration-live-verify-executed")
  }
  if ($ReadinessRequireCalibrationLiveVerifySuccess) {
    $readinessArgs.Add("--require-calibration-live-verify-success")
  } else {
    $readinessArgs.Add("--no-require-calibration-live-verify-success")
  }
  if (-not [string]::IsNullOrWhiteSpace($ReadinessCalibrationWorkflowReport)) {
    $readinessArgs.Add("--calibration-workflow-report")
    $readinessArgs.Add($ReadinessCalibrationWorkflowReport)
  }
  if ($ReadinessMaxCalibrationWorkflowAgeSeconds -ge 0) {
    $readinessArgs.Add("--max-calibration-workflow-age-seconds")
    $readinessArgs.Add("$ReadinessMaxCalibrationWorkflowAgeSeconds")
  }
  if ($ReadinessRunPreflight) {
    $readinessArgs.Add("--run-preflight")
    if ($ReadinessPreflightStrictMode) {
      $readinessArgs.Add("--preflight-strict-mode")
    }
    if ($ReadinessPreflightAggressiveMsiClose) {
      $readinessArgs.Add("--preflight-aggressive-msi-close")
    }
  }
  Invoke-KeylightCommand -CommandArgs $readinessArgs.ToArray()
  Write-Host "Readiness report: $ReadinessOutput"
}
