$ErrorActionPreference = 'Stop'

# Load configuration from paths_config.ps1
. (Join-Path $PSScriptRoot "paths_config.ps1")

$pythonExe = $global:ComfyPythonExe
$mainPy    = $global:ComfyMainPy
$baseDir   = $global:ComfyBaseDir
$port      = $global:ComfyPort

# Sanity-check before spawning — otherwise START.bat's wait loop hangs forever
if (-not (Test-Path $pythonExe)) {
    Write-Host "  [launch_comfyui] ERROR: Python venv not found at $pythonExe" -ForegroundColor Red
    Write-Host "                          Check paths_config.ps1" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $mainPy)) {
    Write-Host "  [launch_comfyui] ERROR: ComfyUI main.py not found at $mainPy" -ForegroundColor Red
    Write-Host "                          Check paths_config.ps1" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $baseDir)) {
    Write-Host "  [launch_comfyui] ERROR: ComfyUI base directory not found at $baseDir" -ForegroundColor Red
    Write-Host "                          Check paths_config.ps1" -ForegroundColor Red
    exit 1
}

# -WindowStyle Minimized + an explicit title makes the process discoverable by
# both `taskkill /FI WINDOWTITLE` and the WMI command-line filter in STOP.bat.
$proc = Start-Process -FilePath $pythonExe `
    -ArgumentList @(
        $mainPy,
        "--port", $port.ToString(),
        "--listen", "127.0.0.1",
        "--base-directory", $baseDir,
        "--disable-dynamic-vram"
    ) `
    -WorkingDirectory $baseDir `
    -WindowStyle Minimized `
    -PassThru

if ($proc) {
    Write-Host ("  [launch_comfyui] Spawned ComfyUI as PID {0}" -f $proc.Id)
} else {
    Write-Host "  [launch_comfyui] ERROR: Start-Process returned no handle" -ForegroundColor Red
    exit 1
}
