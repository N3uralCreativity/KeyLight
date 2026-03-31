param(
    [switch]$NoAutoStart,
    [switch]$NoAdmin,
    [switch]$NoTray,
    [switch]$ShowWindow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path

if (-not $NoAdmin -and -not (Test-IsAdministrator)) {
    $elevatedArgs = @(
        "-NoProfile",
        "-WindowStyle", "Hidden",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"{0}"' -f $PSCommandPath)
    )
    if ($NoAutoStart) {
        $elevatedArgs += "-NoAutoStart"
    }
    if ($NoTray) {
        $elevatedArgs += "-NoTray"
    }
    if ($ShowWindow) {
        $elevatedArgs += "-ShowWindow"
    }
    Start-Process `
        -FilePath "powershell" `
        -Verb RunAs `
        -WindowStyle Hidden `
        -ArgumentList ($elevatedArgs -join " ")
    exit 0
}

Set-Location $repoRoot

$pythonCliPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonCliPath)) {
    Write-Host "Virtual environment missing. Bootstrapping..."
    $bootstrapScript = Join-Path $repoRoot "scripts/bootstrap.ps1"
    powershell -ExecutionPolicy Bypass -File $bootstrapScript -WithHardware $true -WithCapture $true -WithAudio $true
    if (-not (Test-Path $pythonCliPath)) {
        throw "Bootstrap did not produce .venv\\Scripts\\python.exe"
    }
}

$pythonGuiPath = Join-Path $repoRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonGuiPath)) {
    $pythonGuiPath = $pythonCliPath
}

$depsCheck = @'
import importlib.util

modules = ['hid', 'mss', 'PySide6', 'numpy', 'soundcard']
missing = [name for name in modules if importlib.util.find_spec(name) is None]
print(','.join(missing))
'@
$missingModulesRaw = & $pythonCliPath -c $depsCheck
$missingModules = "$missingModulesRaw".Trim()
if ($missingModules -ne "") {
    Write-Host "Missing modules: $missingModules"
    Write-Host "Installing required app dependencies (hw,capture,audio,ui-premium)..."
    & $pythonCliPath -m pip install -e ".[hw,capture,audio,ui-premium]"
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed."
    }
}

$appArgs = @("-m", "keylight.app")
if ($NoAutoStart) {
    $appArgs += "--no-autostart"
} else {
    $appArgs += "--autostart"
}
if ($NoTray) {
    $appArgs += "--no-tray"
} else {
    $appArgs += "--tray"
}
if ($ShowWindow -or $NoTray) {
    $appArgs += "--no-start-hidden"
} else {
    $appArgs += "--start-hidden"
}

& $pythonGuiPath @appArgs
if ($LASTEXITCODE -ne 0) {
    $errorLog = Join-Path $repoRoot "artifacts\launcher_error.log"
    New-Item -ItemType Directory -Path (Split-Path -Parent $errorLog) -Force | Out-Null
    "[{0}] KeyLight app exited with code {1}" -f (Get-Date -Format o), $LASTEXITCODE |
        Out-File -FilePath $errorLog -Encoding utf8 -Append
    if ($ShowWindow) {
        Write-Host "KeyLight app exited with error code $LASTEXITCODE"
        Write-Host "See: $errorLog"
        Read-Host "Press Enter to close"
    }
}
exit $LASTEXITCODE
