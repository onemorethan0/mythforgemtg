$ErrorActionPreference = 'Stop'

$pythonExe = "C:\Users\rvn92\Documents\ComfyUI\.venv\Scripts\python.exe"
$mainPy    = "E:\Games\comfy\ComfyUI\resources\ComfyUI\main.py"
$baseDir   = "C:\Users\rvn92\Documents\ComfyUI"

# Sanity-check before spawning — otherwise start_app.bat's wait loop hangs forever
if (-not (Test-Path $pythonExe)) {
    Write-Host "  [launch_comfyui] ERROR: Python venv not found at $pythonExe" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $mainPy)) {
    Write-Host "  [launch_comfyui] ERROR: ComfyUI main.py not found at $mainPy" -ForegroundColor Red
    exit 1
}

# -WindowStyle Minimized + an explicit title makes the process discoverable by
# both `taskkill /FI WINDOWTITLE` and the WMI command-line filter in stop_app.bat.
$proc = Start-Process -FilePath $pythonExe `
    -ArgumentList @(
        $mainPy,
        "--port", "8188",
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
