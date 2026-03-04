param(
  [bool]$CloseConflicts = $true,
  [bool]$IncludeOverlayConflicts = $true,
  [switch]$AggressiveMsiClose,
  [switch]$StrictMode,
  [string]$ReportPath = "artifacts/preflight_report.json"
)

$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)

function Write-PreflightReport {
  param(
    [string]$ReportPath,
    [hashtable]$Payload
  )

  try {
    $resolvedPath = Resolve-PathForWrite -TargetPath $ReportPath
    $parent = Split-Path -Path $resolvedPath -Parent
    if ($parent -and -not (Test-Path -Path $parent)) {
      New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 8 | Set-Content -Path $resolvedPath -Encoding UTF8
    Write-Host "Preflight report: $resolvedPath"
  } catch {
    Write-Warning "Failed to write preflight report '$ReportPath': $($_.Exception.Message)"
  }
}

function Resolve-PathForWrite {
  param(
    [string]$TargetPath
  )

  if ([string]::IsNullOrWhiteSpace($TargetPath)) {
    return (Join-Path -Path (Get-Location) -ChildPath "artifacts/preflight_report.json")
  }
  if ([System.IO.Path]::IsPathRooted($TargetPath)) {
    return $TargetPath
  }
  return (Join-Path -Path (Get-Location) -ChildPath $TargetPath)
}

$rules = @(
  @{ Name = "LEDKeeper2"; Category = "RGB"; Reason = "MSI Mystic Light can override keyboard zones."; Mode = "Close" }
  @{ Name = "OpenRGB"; Category = "RGB"; Reason = "Direct device control conflict."; Mode = "Close" }
  @{ Name = "SignalRgb"; Category = "RGB"; Reason = "Competes for keyboard lighting ownership."; Mode = "Close" }
  @{ Name = "SteelSeriesGG"; Category = "RGB"; Reason = "Can control SteelSeries-compatible lighting paths."; Mode = "Close" }
  @{ Name = "SteelSeriesEngine"; Category = "RGB"; Reason = "Can control keyboard lighting zones."; Mode = "Close" }
  @{ Name = "iCUE"; Category = "RGB"; Reason = "Global RGB orchestration can interfere with writes."; Mode = "Close" }
  @{ Name = "Corsair.Service"; Category = "RGB"; Reason = "Background RGB service can hold lighting resources."; Mode = "Close" }
  @{ Name = "RzSynapse"; Category = "RGB"; Reason = "Vendor RGB controller process."; Mode = "Close" }
  @{ Name = "RazerAppEngine"; Category = "RGB"; Reason = "Vendor RGB controller process."; Mode = "Close" }
  @{ Name = "lghub"; Category = "RGB"; Reason = "Can drive lighting effects and ambient sync."; Mode = "Close" }
  @{ Name = "ghub"; Category = "RGB"; Reason = "Can drive lighting effects and ambient sync."; Mode = "Close" }
  @{ Name = "logi_lamparray_service"; Category = "RGB"; Reason = "Ambient lamparray effect service can conflict."; Mode = "Close" }
  @{ Name = "wallpaperservice32"; Category = "Overlay"; Reason = "Wallpaper Engine can inject ambient effects."; Mode = "Close" }
  @{ Name = "NVIDIA Overlay"; Category = "Overlay"; Reason = "Overlay/capture hooks can affect frame capture stability."; Mode = "Close" }
  @{ Name = "MSI.CentralServer"; Category = "MSI"; Reason = "MSI lighting stack may contend with direct writes."; Mode = "Warn" }
  @{ Name = "MSI.TerminalServer"; Category = "MSI"; Reason = "MSI lighting stack may contend with direct writes."; Mode = "Warn" }
  @{ Name = "MSI_AI_Engine"; Category = "MSI"; Reason = "MSI stack component may alter keyboard behavior."; Mode = "Warn" }
  @{ Name = "MSI_Central_Service"; Category = "MSI"; Reason = "MSI stack component may alter keyboard behavior."; Mode = "Warn" }
  @{ Name = "MSIAPService"; Category = "MSI"; Reason = "MSI stack component may alter keyboard behavior."; Mode = "Warn" }
  @{ Name = "MSIService"; Category = "MSI"; Reason = "MSI stack component may alter keyboard behavior."; Mode = "Warn" }
)

if (-not $IncludeOverlayConflicts) {
  $rules = $rules | Where-Object { $_.Category -ne "Overlay" }
}

if ($AggressiveMsiClose) {
  $rules = $rules | ForEach-Object {
    if ($_.Category -eq "MSI") {
      @{
        Name = $_.Name
        Category = $_.Category
        Reason = $_.Reason
        Mode = "Close"
      }
    } else {
      $_
    }
  }
}

$runningMatches = @()
$allProcesses = Get-Process
foreach ($rule in $rules) {
  $found = $allProcesses | Where-Object { $_.ProcessName -eq $rule.Name }
  foreach ($process in $found) {
    $runningMatches += [PSCustomObject]@{
      ProcessName = $process.ProcessName
      Id = $process.Id
      Category = $rule.Category
      Mode = $rule.Mode
      Reason = $rule.Reason
    }
  }
}

$resolutionRows = @()

if ($runningMatches.Count -eq 0) {
  Write-PreflightReport -ReportPath $ReportPath -Payload @{
    generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    is_admin = $isAdmin
    strict_mode = [bool]$StrictMode
    aggressive_msi_close = [bool]$AggressiveMsiClose
    close_conflicts = $CloseConflicts
    include_overlay_conflicts = $IncludeOverlayConflicts
    detected_count = 0
    closed_count = 0
    warn_count = 0
    access_denied_count = 0
    unresolved_count = 0
    detected = @()
    resolutions = @()
  }
  Write-Host "Preflight: no known conflicting processes detected."
  exit 0
}

Write-Host "Preflight: detected possible conflicts:"
$runningMatches | Sort-Object Category, ProcessName, Id | Format-Table -AutoSize

$closedCount = 0
$warnCount = 0
$accessDeniedCount = 0
$unresolvedCount = 0

foreach ($match in $runningMatches) {
  $status = "Unresolved"
  $note = ""
  if ($match.Mode -eq "Warn") {
    $warnCount += 1
    $unresolvedCount += 1
    $status = "WarnOnly"
    $note = "Warn-only MSI mode."
    $resolutionRows += [PSCustomObject]@{
      ProcessName = $match.ProcessName
      Id = $match.Id
      Category = $match.Category
      Mode = $match.Mode
      Status = $status
      Note = $note
    }
    continue
  }

  if (-not $CloseConflicts) {
    $unresolvedCount += 1
    $status = "Skipped"
    $note = "CloseConflicts is disabled."
    $resolutionRows += [PSCustomObject]@{
      ProcessName = $match.ProcessName
      Id = $match.Id
      Category = $match.Category
      Mode = $match.Mode
      Status = $status
      Note = $note
    }
    continue
  }

  try {
    Stop-Process -Id $match.Id -Force
    $closedCount += 1
    $status = "Closed"
    $note = "Process terminated."
    Write-Host "Closed: $($match.ProcessName) (PID $($match.Id))"
  } catch {
    $unresolvedCount += 1
    $status = "CloseFailed"
    $note = $_.Exception.Message
    if ($_.Exception.Message -match "Access is denied") {
      $accessDeniedCount += 1
    }
    Write-Warning "Failed to close $($match.ProcessName) (PID $($match.Id)): $($_.Exception.Message)"
  }

  $resolutionRows += [PSCustomObject]@{
    ProcessName = $match.ProcessName
    Id = $match.Id
    Category = $match.Category
    Mode = $match.Mode
    Status = $status
    Note = $note
  }
}

if ($CloseConflicts) {
  Write-Host "Preflight complete. Closed $closedCount process(es)."
} else {
  Write-Host "Preflight complete. CloseConflicts disabled; no process terminated."
}

if ($warnCount -gt 0) {
  Write-Warning "$warnCount MSI process(es) detected in warn-only mode."
  Write-Warning "If hardware writes fail, rerun preflight with -AggressiveMsiClose."
}

if ($accessDeniedCount -gt 0 -and -not $isAdmin) {
  Write-Warning "$accessDeniedCount process(es) could not be closed due permissions."
  Write-Warning "Run PowerShell as Administrator to force-close protected RGB services."
}

Write-PreflightReport -ReportPath $ReportPath -Payload @{
  generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
  is_admin = $isAdmin
  strict_mode = [bool]$StrictMode
  aggressive_msi_close = [bool]$AggressiveMsiClose
  close_conflicts = $CloseConflicts
  include_overlay_conflicts = $IncludeOverlayConflicts
  detected_count = $runningMatches.Count
  closed_count = $closedCount
  warn_count = $warnCount
  access_denied_count = $accessDeniedCount
  unresolved_count = $unresolvedCount
  detected = $runningMatches | Sort-Object Category, ProcessName, Id
  resolutions = $resolutionRows | Sort-Object Category, ProcessName, Id
}

if ($StrictMode -and $unresolvedCount -gt 0) {
  Write-Warning "Preflight strict mode failed: $unresolvedCount conflict process(es) remain unresolved."
  exit 2
}
