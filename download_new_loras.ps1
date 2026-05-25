<#
.SYNOPSIS
  Download new genre LoRAs for the MTG Deck Builder art styles.
  Run this script — it opens each CivitAI download link in Chrome (where you're
  already logged in).  Save each file to:
    C:\Users\rvn92\Documents\ComfyUI\models\loras\

  After downloading, restart the server (stop_app.bat → start_app.bat) and the
  new art styles will show "✓ Ready" in the style selector.
#>

$loraDir = "C:\Users\rvn92\Documents\ComfyUI\models\loras"
Write-Host "`n=== MTG Deck Builder — New Genre LoRA Downloader ===" -ForegroundColor Cyan
Write-Host "Save location: $loraDir`n" -ForegroundColor Yellow

# Table of LoRAs to download
# Format: [label, direct-download-url, expected-filename, civitai-model-page]
$loras = @(
  # --- Gothic Horror ---
  @{
    label    = "Gothic Horror — Dark Haunted Fantasy v5 HD+"
    page     = "https://civitai.com/models/849375"
    direct   = "https://civitai.com/api/download/models/978542"
    filename = "Dark_Haunted_Fantasy_v5.safetensors"
    style    = "Gothic Horror"
  },
  @{
    label    = "Gothic Horror — Dark Gothic Horror Atmosphere"
    page     = "https://civitai.com/models/1128317"
    direct   = "https://civitai.com/api/download/models/1268321"
    filename = "Dark_Gothic_Horror_Eerie_Shadows_of_Macabre_Fantasy_Worlds.safetensors"
    style    = "Gothic Horror"
  },

  # --- Watercolor ---
  @{
    label    = "Watercolor FLUX"
    page     = "https://civitai.com/models/840424"
    direct   = "https://civitai.com/api/download/models/940271"
    filename = "WATERCOLOR-lora.TA_trained.safetensors"
    style    = "Watercolor"
  },

  # --- Steampunk ---
  @{
    label    = "Steampunk Illustration FLUX"
    page     = "https://civitai.com/models/799887"
    direct   = "https://civitai.com/api/download/models/894436"
    filename = "SteampunkIllustration_v1.safetensors"
    style    = "Steampunk"
  },

  # --- Oil Painting ---
  @{
    label    = "Oil Painting FLUX (Renaissance)"
    page     = "https://civitai.com/models/849568"
    direct   = "https://civitai.com/api/download/models/1027956"
    filename = "oil_painting_flux-h.safetensors"
    style    = "Oil Painting"
  },

  # --- Pixel Art ---
  @{
    label    = "Pixel Art Illustrations FLUX"
    page     = "https://civitai.com/models/683579"
    direct   = "https://civitai.com/api/download/models/765098"
    filename = "Pixel_Art_FLUX.safetensors"
    style    = "Pixel Art"
  },

  # --- Eldritch Horror ---
  @{
    label    = "Eldritch Comics FLUX v1.1"
    page     = "https://civitai.com/models/671064"
    direct   = "https://civitai.com/api/download/models/792184"
    filename = "Eldritch_Comics_for_Flux_1.1.safetensors"
    style    = "Eldritch Horror"
  },

  # --- Stained Glass ---
  @{
    label    = "Stained Glass FLUX"
    page     = "https://civitai.com/models/553811"
    direct   = "https://civitai.com/api/download/models/771546"
    filename = "StainedGlassFlux.safetensors"
    style    = "Stained Glass"
  },
  @{
    label    = "Stained Glass Style Flux1.D"
    page     = "https://civitai.com/models/1007585"
    direct   = "https://civitai.com/api/download/models/1129251"
    filename = "Stained_Glass_Style.safetensors"
    style    = "Stained Glass"
  }
)

Write-Host "Checking which LoRAs are already downloaded..." -ForegroundColor Gray
$toDownload = $loras | Where-Object { -not (Test-Path (Join-Path $loraDir $_.filename)) }
$alreadyHave = $loras | Where-Object { (Test-Path (Join-Path $loraDir $_.filename)) }

foreach ($l in $alreadyHave) {
  Write-Host "  [✓ exists] $($l.filename)" -ForegroundColor Green
}

if ($toDownload.Count -eq 0) {
  Write-Host "`nAll LoRAs already downloaded! Restart the server to activate them." -ForegroundColor Green
  exit 0
}

Write-Host "`nAttempting direct downloads (requires CivitAI session cookie)..." -ForegroundColor Cyan

foreach ($l in $toDownload) {
  $dest = Join-Path $loraDir $l.filename
  Write-Host "`n  Downloading: $($l.label)" -ForegroundColor Yellow
  Write-Host "  → $dest"
  try {
    # Try with system IE cookies (works if Chrome has shared cookie store)
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("User-Agent", "Mozilla/5.0")
    $wc.DownloadFile($l.direct, $dest)
    $size = (Get-Item $dest).Length
    if ($size -lt 50000) {
      # Probably got an HTML login page, not a real model file
      Remove-Item $dest -Force
      throw "Response too small ($size bytes) — likely a login redirect"
    }
    Write-Host "  [✓ downloaded] $([math]::Round($size/1MB,1)) MB" -ForegroundColor Green
  } catch {
    Write-Host "  [! direct failed] $_" -ForegroundColor Red
    Write-Host "  Opening CivitAI page in Chrome — click Download there." -ForegroundColor Yellow
    Start-Process "chrome.exe" $l.page
    Write-Host "  IMPORTANT: rename the downloaded file to: $($l.filename)" -ForegroundColor Cyan
    Write-Host "  Save to: $loraDir"
    Start-Sleep -Seconds 2
  }
}

Write-Host "`n=== Done ===" -ForegroundColor Cyan
Write-Host "After all files are in place, restart the server:" -ForegroundColor Yellow
Write-Host "  stop_app.bat  →  start_app.bat" -ForegroundColor White
Write-Host "Then rebuild a deck with the new styles — they'll show ✓ Ready.`n"
