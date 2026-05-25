<#
  Run this after Chrome finishes the LoRA downloads.
  Moves files from your Downloads folder → ComfyUI loras folder,
  then notifies ComfyUI to rescan.
#>
$src  = "$env:USERPROFILE\Downloads"
$dest = "C:\Users\rvn92\Documents\ComfyUI\models\loras"

$expected = @(
  "Dark_Haunted_Fantasy_v5.safetensors",
  "Dark_Gothic_Horror_Eerie_Shadows_of_Macabre_Fantasy_Worlds.safetensors",
  "WATERCOLOR-lora.TA_trained.safetensors",
  "SteampunkIllustration_v1.safetensors",
  "Pixel_Art_FLUX.safetensors",
  "Eldritch_Comics_for_Flux_1.1.safetensors",
  "Stained_Glass_Style.safetensors"
)

Write-Host "`n=== Moving LoRAs to ComfyUI ===" -ForegroundColor Cyan
$moved = 0
foreach ($f in $expected) {
  $from = Join-Path $src $f
  $to   = Join-Path $dest $f
  if (Test-Path $to) {
    Write-Host "  [already there] $f" -ForegroundColor Green
    $moved++
    continue
  }
  if (Test-Path $from) {
    $size = [math]::Round((Get-Item $from).Length / 1MB, 1)
    if ($size -lt 1) {
      Write-Host "  [SKIP — too small ($size MB), still downloading?] $f" -ForegroundColor Yellow
      continue
    }
    Move-Item -Path $from -Destination $to -Force
    Write-Host "  [moved $size MB] $f" -ForegroundColor Green
    $moved++
  } else {
    Write-Host "  [not found yet] $f — still downloading or check filename" -ForegroundColor Red
  }
}

Write-Host ""
if ($moved -eq $expected.Count) {
  Write-Host "All LoRAs in place! Restarting server to activate..." -ForegroundColor Green
  # Kill + restart just the FastAPI server (ComfyUI and Ollama stay running)
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'server\.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
  Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c cd /d C:\Users\rvn92\Documents\mtg_deck_builder && set PYTHONIOENCODING=utf-8 && C:\Python314\python.exe server.py >> server.log 2>&1" `
    -WindowStyle Minimized `
    -WorkingDirectory "C:\Users\rvn92\Documents\mtg_deck_builder"
  Write-Host "Server restarted. Open http://localhost:8000 — all new styles should show Ready!" -ForegroundColor Cyan
} else {
  Write-Host "$moved / $($expected.Count) LoRAs in place. Re-run when downloads finish." -ForegroundColor Yellow
  Write-Host "Then restart the server (stop_app.bat → start_app.bat) to pick them up."
}
