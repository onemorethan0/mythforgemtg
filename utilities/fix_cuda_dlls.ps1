# Fix CUDA 12.x DLL accessibility for ONNXRuntime
# Copies CUDA 12 runtime DLLs from nvidia pip packages to ONNXRuntime's directory
# so that ReActor can find them at runtime.

$venvSitePackages = 'C:\Users\rvn92\Documents\ComfyUI\.venv\Lib\site-packages'
$onnxDir = "$venvSitePackages\onnxruntime\capi"

Write-Host "Copying CUDA 12 DLLs to ONNXRuntime directory..." -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $onnxDir)) {
    Write-Host "ERROR: ONNXRuntime capi directory not found at: $onnxDir" -ForegroundColor Red
    exit 1
}

$nvidiaRoot = "$venvSitePackages\nvidia"
if (-not (Test-Path $nvidiaRoot)) {
    Write-Host "ERROR: nvidia packages not installed" -ForegroundColor Red
    exit 1
}

$nvidiaDirs = Get-ChildItem $nvidiaRoot -Directory
$copyCount = 0

foreach ($dir in $nvidiaDirs) {
    $binDir = Join-Path $dir.FullName "bin"
    if (Test-Path $binDir) {
        $dlls = Get-ChildItem $binDir -Filter '*.dll'
        foreach ($dll in $dlls) {
            $destPath = Join-Path $onnxDir $dll.Name
            if (-not (Test-Path $destPath)) {
                Copy-Item $dll.FullName $destPath -Force
                Write-Host "  Copied: $($dll.Name)" -ForegroundColor Green
                $copyCount++
            } else {
                Write-Host "  Skipped (exists): $($dll.Name)" -ForegroundColor Yellow
            }
        }
    }
}

Write-Host ""
Write-Host "Total DLLs copied: $copyCount" -ForegroundColor Green

# Verify critical DLLs
$criticalDlls = @('cublasLt64_12.dll', 'cublas64_12.dll', 'cudart64_12.dll', 'cudnn64_9.dll')
Write-Host ""
Write-Host "Verifying critical DLLs:" -ForegroundColor Cyan
foreach ($dll in $criticalDlls) {
    $path = Join-Path $onnxDir $dll
    if (Test-Path $path) {
        Write-Host "  [OK] $dll" -ForegroundColor Green
    } else {
        Write-Host "  [MISSING] $dll" -ForegroundColor Red
    }
}
