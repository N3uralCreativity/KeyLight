param(
  [bool]$WithHardware = $false,
  [bool]$WithCapture = $true,
  [bool]$WithAudio = $true,
  [bool]$WithUi = $true
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path .venv)) {
  python -m venv .venv
}

. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

$extras = @("dev")
if ($WithHardware) {
  $extras += "hw"
}
if ($WithCapture) {
  $extras += "capture"
}
if ($WithAudio) {
  $extras += "audio"
}
if ($WithUi) {
  $extras += "ui-premium"
}

$extraSpec = ($extras -join ",")
python -m pip install -e ".[${extraSpec}]"

Write-Host "Environment ready with extras: $extraSpec"
Write-Host "Activate with: . .\\.venv\\Scripts\\Activate.ps1"
