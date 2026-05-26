# ═══════════════════════════════════════════════════════════════════════════════
# MTG Commander Deck Builder — Service Paths Configuration
#
# Edit these paths if your services are installed in different locations.
# All paths will be automatically resolved as absolute, so relative paths work too.
# ═══════════════════════════════════════════════════════════════════════════════

# ── Python Executables ──────────────────────────────────────────────────────────
# The Python interpreter to use for the deck builder server
$global:PythonExe = "C:\Python314\python.exe"

# The Python venv for ComfyUI (ComfyUI has its own isolated environment)
$global:ComfyPythonExe = "C:\Users\rvn92\Documents\ComfyUI\.venv\Scripts\python.exe"

# ── ComfyUI Configuration ───────────────────────────────────────────────────────
# Path to ComfyUI's main.py entry point
$global:ComfyMainPy = "E:\Games\comfy\ComfyUI\resources\ComfyUI\main.py"

# ComfyUI base directory (where models, input, output folders live)
$global:ComfyBaseDir = "C:\Users\rvn92\Documents\ComfyUI"

# ComfyUI port (change only if port 8188 is already in use)
$global:ComfyPort = 8188

# ── Deck Builder Server ─────────────────────────────────────────────────────────
# Root directory for the MTG deck builder project
$global:DeckBuilderDir = "C:\Users\rvn92\Documents\mtg_deck_builder"

# Port for the FastAPI backend (change only if 8000 is already in use)
$global:ServerPort = 8000

# Log file for the FastAPI server
$global:ServerLogFile = "$global:DeckBuilderDir\server.log"

# ── Service Health Check URLs ───────────────────────────────────────────────────
$global:OllamaHealthUrl = "http://127.0.0.1:11434/api/tags"
$global:ComfyHealthUrl = "http://127.0.0.1:$($global:ComfyPort)/system_stats"
$global:ServerHealthUrl = "http://127.0.0.1:$($global:ServerPort)/api/playstyles"

# ── Application URLs ────────────────────────────────────────────────────────────
$global:AppUrl = "http://localhost:$($global:ServerPort)"
$global:ComfyUrl = "http://localhost:$($global:ComfyPort)"
$global:OllamaUrl = "http://localhost:11434"

# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATION: Check that all required executables and files exist
# ═══════════════════════════════════════════════════════════════════════════════

function Test-ConfigPaths {
    $missing = @()

    if (-not (Test-Path $global:PythonExe)) {
        $missing += "Python interpreter: $($global:PythonExe)"
    }
    if (-not (Test-Path $global:ComfyPythonExe)) {
        $missing += "ComfyUI Python venv: $($global:ComfyPythonExe)"
    }
    if (-not (Test-Path $global:ComfyMainPy)) {
        $missing += "ComfyUI main.py: $($global:ComfyMainPy)"
    }
    if (-not (Test-Path $global:ComfyBaseDir)) {
        $missing += "ComfyUI base directory: $($global:ComfyBaseDir)"
    }
    if (-not (Test-Path $global:DeckBuilderDir)) {
        $missing += "Deck builder directory: $($global:DeckBuilderDir)"
    }

    if ($missing.Count -gt 0) {
        Write-Host "`n[ERROR] Configuration paths are invalid or missing:" -ForegroundColor Red
        foreach ($m in $missing) {
            Write-Host "  ✗ $m" -ForegroundColor Red
        }
        Write-Host "`nEdit paths_config.ps1 to correct the paths and try again.`n" -ForegroundColor Yellow
        return $false
    }
    return $true
}
